import frappe
from frappe import _
from influxdb_client import InfluxDBClient
from datetime import datetime, timedelta
import pytz
import logging
from typing import Dict, List, Optional, Any, Tuple
from frappe.utils import (
  now_datetime, get_datetime, add_to_date, get_datetime_str,
  get_system_timezone, convert_utc_to_system_timezone
)

# Configure logging
logging.basicConfig(
  level=logging.INFO,
  format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TimezoneHandler:
  """Handle timezone conversions between UTC and system timezone"""
  def __init__(self):
    self.system_timezone = pytz.timezone(get_system_timezone())
    self.utc = pytz.UTC

  def system_to_utc(self, dt: datetime) -> datetime:
    """Convert system timezone to UTC"""
    if dt.tzinfo is None:
      dt = self.system_timezone.localize(dt)
    return dt.astimezone(self.utc)

  def utc_to_system(self, dt: datetime) -> datetime:
    """Convert UTC to system timezone"""
    if dt.tzinfo is None:
      dt = self.utc.localize(dt)
    return dt.astimezone(self.system_timezone)

  def get_system_now(self) -> datetime:
    """Get current time in system timezone"""
    return self.utc_to_system(datetime.now(self.utc))

  def format_for_influx(self, dt: datetime) -> str:
    """Format datetime for InfluxDB query (always UTC)"""
    utc_dt = self.system_to_utc(dt) if dt.tzinfo != self.utc else dt
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

  def format_for_frappe(self, dt: datetime) -> datetime:
    """Format datetime for Frappe (system timezone, no tzinfo)"""
    system_dt = self.utc_to_system(dt) if dt.tzinfo == self.utc else dt
    return system_dt.replace(tzinfo=None)

class InfluxDBConfig:
  """Class to manage InfluxDB configuration"""
  def __init__(self):
    self.settings = frappe.get_single('CN Connect Settings')
    self.url = self.settings.influxdb_url
    self.token = self.settings.get_password('influxdb_token')
    self.bucket = self.settings.influxdb_bucket
    self.org = self.settings.influxdb_org
    self.validate()

  def validate(self) -> None:
    """Validate that all required configuration values are present"""
    missing = []
    for attr in ['url', 'token', 'bucket', 'org']:
      if not getattr(self, attr):
        missing.append(attr)
    if missing:
      raise ValueError(f"Missing InfluxDB configuration in CN Connect Settings: {', '.join(missing)}")
      
class InfluxDataFetcher:
  def __init__(self, tz_handler: TimezoneHandler):
    self.config = InfluxDBConfig()
    self.client = None
    self.query_api = None
    self.tz = tz_handler
    self._initialize_client()

  def _initialize_client(self):
    """Initialize InfluxDB client"""
    try:
      self.client = InfluxDBClient(
        url=self.config.url,
        token=self.config.token,
        org=self.config.org
      )
      self.query_api = self.client.query_api()
      logger.info("InfluxDB client initialized successfully")
    except Exception as e:
      logger.error(f"Failed to initialize InfluxDB client: {str(e)}")
      raise

  def fetch_latest_readings(self, hostname: str, sensor_var: str, last_run: datetime) -> List[Dict]:
    """Fetch readings from InfluxDB for a specific field within time window"""
    try:
      # Convert times to UTC for InfluxDB query
      utc_start = self.tz.format_for_influx(last_run)
      utc_end = self.tz.format_for_influx(self.tz.get_system_now())
      
      logger.info(f"Fetching data for {hostname}/{sensor_var} from {utc_start} to {utc_end}")
      
      query = f'''
        from(bucket: "{self.config.bucket}")
          |> range(start: {utc_start}, stop: {utc_end})
          |> filter(fn: (r) => r["_measurement"] == "sensor_data")
          |> filter(fn: (r) => r["hostname"] == "{hostname}")
          |> filter(fn: (r) => r["_field"] == "{sensor_var}")
          |> keep(columns: ["_time", "_value"])
          |> sort(columns: ["_time"])
      '''
      
      result = self.query_api.query(query)
      readings = []
      
      for table in result:
        for record in table.records:
          # Convert UTC timestamp to system timezone
          local_time = self.tz.utc_to_system(record.get_time())
          readings.append({
            'timestamp': local_time,
            'value': record.get_value()
          })
      
      logger.info(f"Fetched {len(readings)} readings for {hostname}/{sensor_var}")
      return readings

    except Exception as e:
      logger.error(f"Error fetching data for {hostname} - {sensor_var}: {str(e)}")
      return []

  def get_available_fields(self, hostname: str) -> List[str]:
    """Get available fields for a device"""
    try:
      query = f'''
        from(bucket: "{self.config.bucket}")
          |> range(start: -1h)
          |> filter(fn: (r) => r["_measurement"] == "sensor_data")
          |> filter(fn: (r) => r["hostname"] == "{hostname}")
          |> keep(columns: ["_field"])
          |> distinct(column: "_field")
      '''
      
      result = self.query_api.query(query)
      fields = []
      for table in result:
        for record in table.records:
          fields.append(record.get_value())
      
      logger.info(f"Found fields for {hostname}: {fields}")
      return fields
    except Exception as e:
      logger.error(f"Error fetching fields for {hostname}: {str(e)}")
      return []
      
class DeviceManager:
  def __init__(self, influx_fetcher: InfluxDataFetcher, tz_handler: TimezoneHandler):
    self.influx = influx_fetcher
    self.tz = tz_handler

  def update_device_data(self, device_doc: 'frappe.model.document.Document', last_run: datetime) -> None:
    try:
      if not device_doc.hostname or not device_doc.data_item:
        return

      device_name = device_doc.name
      hostname = device_doc.hostname
      window_readings = 0
      
      available_fields = [field.lower() for field in self.influx.get_available_fields(hostname)]
      if not available_fields:
        return

      # Get or create log for today
      current_date = now_datetime().date()
      log_filters = {
        'device': device_name,
        'date': current_date
      }

      log_name = frappe.db.exists('CN Device Log', log_filters)
      if log_name:
        log_doc = frappe.get_doc('CN Device Log', log_name)
      else:
        log_doc = frappe.get_doc({
          'doctype': 'CN Device Log',
          'device': device_name,
          'date': current_date,
          'log_item': []
        })
        log_doc.insert(ignore_permissions=True)
        frappe.db.commit()

      for data_item in device_doc.get('data_item', []):
        sensor_var = data_item.sensor_var.lower()
        
        if sensor_var not in available_fields:
          continue

        start_time = get_datetime(data_item.last_recorded) if data_item.last_recorded else last_run
        readings = self.influx.fetch_latest_readings(
          hostname,
          sensor_var,
          start_time
        )

        if readings:
          window_readings += len(readings)
          try:
            values = []
            latest_time = None

            for reading in readings:
              try:
                value = float(reading['value'])
                values.append(value)
                latest_time = reading['timestamp']
              except (ValueError, TypeError):
                continue

            if values and latest_time:
              reading_count = len(values)
              latest_value = values[-1]
              window_avg = sum(values) / reading_count
              window_max = max(values)
              window_min = min(values)
              latest_time_system = self.tz.format_for_frappe(latest_time)

              # Update data item with latest values and statistics
              frappe.db.set_value('CN Data Item', data_item.name, {
                'value': str(latest_value),
                'last_recorded': latest_time_system,
                'reading': (data_item.reading or 0) + reading_count,
                'average': window_avg,
                'maximum': window_max,
                'minimum': window_min
              }, update_modified=False)

              # Update device status
              frappe.db.set_value('CN Device', device_name, {
                'connected': 1,
                'connected_at': latest_time_system
              }, update_modified=False)

              # Update or create log item (only latest values, no statistics)
              existing_idx = None
              for idx, log_item in enumerate(log_doc.log_item):
                if log_item.sensor_var.lower() == sensor_var:
                  existing_idx = idx
                  break

              # If the item exists, append a new entry rather than replacing
              if existing_idx is not None:
                log_doc.append('log_item', {
                  'sensor_var': sensor_var,
                  'uom': data_item.uom,
                  'value': str(latest_value),
                  'data_date': latest_time_system,
                  'chart_type': self._get_chart_type(sensor_var)
                })
              else:
                # No need to check for existing entries, always append new log item
                log_doc.append('log_item', {
                  'sensor_var': sensor_var,
                  'uom': data_item.uom,
                  'value': str(latest_value),
                  'data_date': latest_time_system,
                  'chart_type': self._get_chart_type(sensor_var)
                })
              
              log_doc.save(ignore_permissions=True)
              frappe.db.commit()

          except Exception as e:
            logger.error(f"Error processing readings: {str(e)}")
            frappe.db.rollback()

      # Update device connection status if no new data
      if window_readings == 0 and device_doc.connected:
        frappe.db.set_value('CN Device', device_name, {
          'connected': 0,
          'connected_at': None
        }, update_modified=False)
        frappe.db.commit()

    except Exception as e:
      frappe.log_error(message=str(e), title=f"Device Update Error - {device_doc.name}")
      frappe.db.rollback()

  def _get_chart_type(self, sensor_var: str) -> str:
    sensor_var_lower = sensor_var.lower()
    if sensor_var_lower in ["temperature", "humidity", "pressure"]:
      return "area"
    elif sensor_var_lower in ["battery", "voltage"]:
      return "line"
    elif sensor_var_lower in ["motion", "presence"]:
      return "scatter"
    return "line"  # Default chart type

def get_last_run_time() -> datetime:
  """Get the last successful run time from CN Connect Settings"""
  try:
    settings = frappe.get_single('CN Connect Settings')
    last_run = settings.last_data_collection
    if last_run:
      return get_datetime(last_run)
  except Exception as e:
    logger.error(f"Error getting last run time: {str(e)}")
  
  # If no last run time, default to 1 hour ago
  return add_to_date(now_datetime(), hours=-1)

def update_last_run_time(run_time: datetime) -> None:
  """Update the last successful run time in CN Connect Settings"""
  try:
    settings = frappe.get_single('CN Connect Settings')
    settings.last_data_collection = run_time
    settings.save(ignore_permissions=True)
    frappe.db.commit()
  except Exception as e:
    logger.error(f"Error updating last run time: {str(e)}")
    frappe.db.rollback()

def collect_influx_data() -> None:
  """Main function to collect and process InfluxDB data"""
  influx_fetcher = None
  try:
    # Get last run time and current time
    last_run = get_last_run_time()
    current_run = now_datetime()
    
    logger.info(f"Starting data collection from {last_run} to {current_run}")

    # Initialize components
    tz_handler = TimezoneHandler()
    influx_fetcher = InfluxDataFetcher(tz_handler)
    device_manager = DeviceManager(influx_fetcher, tz_handler)

    # Get active devices
    devices = frappe.get_all(
      'CN Device',
      filters={'disabled': 0},
      fields=['name', 'hostname']
    )
    
    logger.info(f"Found {len(devices)} active devices")

    for device in devices:
      try:
        logger.info(f"Processing device {device.name}")
        device_doc = frappe.get_doc('CN Device', device.name)
        device_manager.update_device_data(device_doc, last_run)
      except Exception as e:
        logger.error(f"Error processing device {device.name}: {str(e)}")
        frappe.db.rollback()
        continue

    # Update last run time
    update_last_run_time(current_run)
    logger.info("Successfully completed data collection")

  except Exception as e:
    logger.error(f"Error in data collection: {str(e)}")
    frappe.log_error(message=str(e), title="Data Collection Error")
    frappe.db.rollback()
  finally:
    if influx_fetcher and influx_fetcher.client:
      influx_fetcher.client.close()

def test_influx_connection():
  """Test function to verify InfluxDB connection and data retrieval"""
  try:
    tz_handler = TimezoneHandler()
    fetcher = InfluxDataFetcher(tz_handler)
    
    devices = frappe.get_all('CN Device', 
                            filters={'disabled': 0}, 
                            fields=['name', 'hostname'])
    
    logger.info(f"Testing connection for {len(devices)} devices")
    
    for device in devices:
      logger.info(f"Testing device {device.name} ({device.hostname})")
      fields = fetcher.get_available_fields(device.hostname)
      logger.info(f"Available fields: {fields}")
      
      if fields:
        readings = fetcher.fetch_latest_readings(
          device.hostname,
          fields[0],
          add_to_date(now_datetime(), hours=-1)
        )
        logger.info(f"Found {len(readings)} readings in last hour")
        if readings:
          logger.info(f"Sample reading: {readings[0]}")
  
  except Exception as e:
    logger.error(f"Test failed: {str(e)}")
    raise

if __name__ == "__main__":
  collect_influx_data()