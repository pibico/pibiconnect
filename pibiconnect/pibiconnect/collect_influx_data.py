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
        return utc_dt.isoformat()

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
            
            logger.debug(f"Fetched {len(readings)} readings for {hostname}/{sensor_var} "
                      f"from {last_run} to {self.tz.get_system_now()}")
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
            return fields
        except Exception as e:
            logger.error(f"Error fetching fields for {hostname}: {str(e)}")
            return []
            
class DeviceManager:
    def __init__(self, influx_fetcher: InfluxDataFetcher, tz_handler: TimezoneHandler):
        self.influx = influx_fetcher
        self.tz = tz_handler

    def update_device_data(self, device_doc: 'frappe.model.document.Document', last_run: datetime) -> None:
        """Update device data for readings since last run"""
        try:
            needs_save = False
            device_name = device_doc.name
            hostname = device_doc.hostname
            window_readings = 0  # Track readings in current window
            
            # Get available fields from InfluxDB
            available_fields = self.influx.get_available_fields(hostname)
            if not available_fields:
                logger.warning(f"No fields found for device {device_name}")
                return

            # Process each data item
            for data_item in device_doc.get('data_item', []):
                if data_item.sensor_var not in available_fields:
                    continue

                # Get last recorded time or use last run time
                start_time = get_datetime(data_item.last_recorded) if data_item.last_recorded else last_run
                if start_time.tzinfo is None:
                    start_time = self.tz.system_timezone.localize(start_time)

                # Fetch readings since last recorded time
                readings = self.influx.fetch_latest_readings(
                    hostname,
                    data_item.sensor_var,
                    start_time
                )

                if readings:
                    window_readings += len(readings)
                    if self._process_readings(device_doc, data_item, readings):
                        needs_save = True

            # Update connection status if no new data
            if window_readings == 0 and device_doc.connected:
                device_doc.connected = 0
                needs_save = True
                logger.info(f"Device {device_name} marked as disconnected due to no new data")
            elif window_readings > 0:
                logger.info(f"Device {device_name} processed {window_readings} readings in current window")

            if needs_save:
                device_doc.flags.ignore_permissions = True
                device_doc.save()
                logger.info(f"Updated device document for {device_name}")

        except Exception as e:
            logger.error(f"Error updating device {device_doc.name}: {str(e)}")
            frappe.log_error(message=str(e), title=f"Device Update Error - {device_doc.name}")

    def _update_data_items(self, device_doc: 'frappe.model.document.Document', 
                          available_fields: List[str]) -> bool:
        """Update data_items in device document"""
        try:
            existing_fields = {item.sensor_var for item in device_doc.get('data_item', [])}
            items_added = False

            for field in available_fields:
                if field not in existing_fields:
                    if not frappe.db.exists("CN Sensor Var", field):
                        continue

                    uom = frappe.db.get_value("CN Sensor Var", field, "uom") or "Unknown"
                    device_doc.append('data_item', {
                        'sensor_var': field,
                        'uom': uom
                    })
                    items_added = True

            if items_added:
                device_doc.flags.ignore_permissions = True
                device_doc.save()

            return items_added

        except Exception as e:
            logger.error(f"Error updating data items for {device_doc.name}: {str(e)}")
            return False

    def _process_readings(self, device_doc: 'frappe.model.document.Document', 
                         data_item: Dict, readings: List[Dict]) -> bool:
        """Process readings and update data_item and device connection status"""
        try:
            values = []
            latest_time = None

            for reading in readings:
                try:
                    value = float(reading['value'])
                    values.append(value)
                    latest_time = reading['timestamp']  # Already in system timezone
                except (ValueError, TypeError):
                    continue

            if not values or not latest_time:
                return False

            # Calculate statistics for this time window
            reading_count = len(values)  # Number of readings in this window
            latest_value = values[-1]
            window_avg = sum(values) / reading_count
            window_max = max(values)
            window_min = min(values)
            
            needs_update = False

            if reading_count > 0:
                # Update data_item with latest value and timestamp
                data_item.value = str(latest_value)
                data_item.last_recorded = self.tz.format_for_frappe(latest_time)
                
                # Keep running statistics in data_item
                if not data_item.reading:
                    data_item.reading = 0
                data_item.reading += reading_count

                # Update device connection status
                formatted_time = self.tz.format_for_frappe(latest_time)
                current_connected_at = get_datetime(device_doc.connected_at) if device_doc.connected_at else None

                if (not device_doc.connected or 
                    not current_connected_at or 
                    formatted_time > current_connected_at):
                    
                    device_doc.connected = 1
                    device_doc.connected_at = formatted_time

                # Create log entry for this time window
                self._create_log_entry(
                    device_doc.name,
                    data_item.sensor_var,
                    data_item.uom,
                    latest_value,
                    latest_time,
                    reading_count,
                    window_avg,
                    window_max,
                    window_min
                )
                
                needs_update = True
                
                logger.info(f"Device {device_doc.name} sensor {data_item.sensor_var}: "
                          f"Processed {reading_count} new readings. "
                          f"Window stats: avg={window_avg:.2f}, max={window_max:.2f}, "
                          f"min={window_min:.2f}")

            return needs_update

        except Exception as e:
            logger.error(f"Error processing readings for {device_doc.name}: {str(e)}")
            return False

    def _create_log_entry(self, device: str, sensor_var: str, uom: str, 
                         value: float, timestamp: datetime, reading_count: int,
                         avg_value: float, max_value: float, min_value: float) -> None:
        """Create log entry for the current time window"""
        try:
            # Use system timezone for log date
            system_dt = self.tz.format_for_frappe(timestamp)
            log_date = system_dt.date()
            
            # Find existing log doc for the day
            log_name = frappe.db.exists("CN Device Log", {
                "device": device,
                "date": log_date
            })

            if log_name:
                log_doc = frappe.get_doc("CN Device Log", log_name)
            else:
                log_doc = frappe.new_doc("CN Device Log")
                log_doc.device = device
                log_doc.date = log_date

            # Determine chart type based on sensor variable
            chart_type = self._get_chart_type(sensor_var)

            # Add new log item with window statistics
            log_doc.append("log_item", {
                "sensor_var": sensor_var,
                "uom": uom,
                "value": str(value),
                "data_date": system_dt,
                "chart_type": chart_type,
                "reading": reading_count,
                "average": avg_value,
                "maximum": max_value,
                "minimum": min_value
            })

            log_doc.flags.ignore_permissions = True
            log_doc.save()

            logger.info(f"Created log entry for device {device} on {log_date} "
                      f"with {reading_count} readings for {sensor_var}")

        except Exception as e:
            logger.error(f"Error creating log entry for device {device}: {str(e)}")
            frappe.log_error(message=str(e), title=f"Log Entry Error - {device}")

    def _get_chart_type(self, sensor_var: str) -> str:
        """Determine chart type based on sensor variable"""
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

        # Process each device
        for device in devices:
            try:
                device_doc = frappe.get_doc('CN Device', device.name)
                device_manager.update_device_data(device_doc, last_run)
            except Exception as e:
                logger.error(f"Error processing device {device.name}: {str(e)}")
                continue

        # Update last run time
        update_last_run_time(current_run)
        
        frappe.db.commit()
        logger.info(f"Successfully completed data collection. Processed {len(devices)} devices")

    except Exception as e:
        logger.error(f"Error in data collection: {str(e)}")
        frappe.log_error(message=str(e), title="Data Collection Error")
        frappe.db.rollback()
    finally:
        if influx_fetcher and influx_fetcher.client:
            influx_fetcher.client.close()

if __name__ == "__main__":
    collect_influx_data()