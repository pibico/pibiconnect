# File: pibiconnect/api.py

import frappe
from frappe import _
from frappe.utils import now_datetime, today, cstr
from frappe.utils.background_jobs import enqueue
from frappe.utils import getdate
from frappe.core.doctype.sms_settings.sms_settings import send_sms
import json
import datetime

@frappe.whitelist()
def get_alert_items():
    try:
        alert_items = frappe.db.sql("""
            SELECT
                device.name as device_name,
                device.hostname,
                device.sensor_type,
                alert_item.name as alert_item_name,
                alert_item.sensor_var,
                alert_item.low_value,
                alert_item.alert_low,
                alert_item.high_value,
                alert_item.alert_high,
                alert_item.alert_cooldown,
                alert_item.last_alert_time
            FROM
                `tabCN Device` as device
            INNER JOIN
                `tabCN Alert Item` as alert_item ON alert_item.parent = device.name
            WHERE
                device.disabled = 0
        """, as_dict=True)
        return alert_items
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), _("Error in get_alert_items"))
        return {"error": str(e)}

@frappe.whitelist()
def batch_update_alert_states(alert_item_name, updates):
    try:
        # Parse the updates JSON
        updates_dict = json.loads(updates)
        
        # Get the alert item document
        alert_doc = frappe.get_doc('CN Alert Item', alert_item_name)
        
        # Update fields
        valid_fields = ['active_low', 'active_high', 'last_alert_time']
        changes_made = False
        
        for field in valid_fields:
            if field in updates_dict:
                new_value = updates_dict[field]
                
                # Handle last_alert_time specially
                if field == 'last_alert_time' and new_value:
                    try:
                        if isinstance(new_value, (int, float)):
                            dt = datetime.datetime.fromtimestamp(new_value, tz=datetime.timezone.utc)
                            new_value = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except Exception as e:
                        frappe.log_error(f"Error converting timestamp: {str(e)}")
                        continue
                # Convert boolean values
                elif isinstance(new_value, bool):
                    new_value = 1 if new_value else 0
                
                if getattr(alert_doc, field) != new_value:
                    setattr(alert_doc, field, new_value)
                    changes_made = True
        
        if changes_made:
            # Save the document which will trigger validation
            alert_doc.save()
            
            frappe.db.commit()
            
            return {
                "message": "Alert states updated successfully",
                "alert_item": alert_item_name,
                "updated_fields": list(updates_dict.keys())
            }
            
        return {
            "message": "No updates required",
            "alert_item": alert_item_name
        }
        
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(
            frappe.get_traceback(), 
            f"Error in batch_update_alert_states: {alert_item_name}"
        )
        return {"error": str(e)}

@frappe.whitelist()
def manage_alert(sensor_var, value, cmd, reason, datadate, doc):
    """
    Manage alerts by logging them and sending notifications.
    """
    try:
        # Input validation
        if not all([sensor_var, value, cmd, reason, datadate, doc]):
            frappe.throw(_("All parameters are required"))

        if cmd not in ['high', 'low']:
            frappe.throw(_("Invalid command. Must be 'high' or 'low'"))

        if reason not in ['start', 'finish']:
            frappe.throw(_("Invalid reason. Must be 'start' or 'finish'"))

        # Validate device existence
        if not frappe.db.exists('CN Device', doc):
            frappe.throw(_("Device not found"))

        # Parse and validate datadate with flexible format handling
        try:
            if isinstance(datadate, str):
                # Try format with seconds first
                try:
                    parsed_date = datetime.datetime.strptime(datadate, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    # If that fails, try format without seconds
                    try:
                        parsed_date = datetime.datetime.strptime(datadate, '%Y-%m-%d %H:%M')
                    except ValueError:
                        frappe.throw(_("Invalid date format. Expected 'YYYY-MM-DD HH:MM[:SS]'"))
            else:
                parsed_date = datadate
        except Exception as e:
            frappe.throw(_("Invalid date format. Expected 'YYYY-MM-DD HH:MM[:SS]'"))

        # Fetch the device document
        device_doc = frappe.get_doc('CN Device', doc)
        
        # Get active warning channels
        channels = frappe.db.sql("""
            SELECT 
                channel_type,
                email,
                mobile
            FROM `tabCN Warning Item`
            WHERE 
                parent = %s 
                AND docstatus < 2 
                AND active = 1
        """, device_doc.name, as_dict=True)

        # Process channels
        alert_channel = []
        sms_recipients = []
        email_recipients = []

        for channel in channels:
            channel_type = channel.get('channel_type')
            if channel_type and channel_type not in alert_channel:
                alert_channel.append(channel_type)
                
            if channel_type == 'Email' and channel.get('email'):
                if channel['email'] not in email_recipients:
                    email_recipients.append(channel['email'])
                    
            if channel_type == 'SMS' and channel.get('mobile'):
                if channel['mobile'] not in sms_recipients:
                    sms_recipients.append(channel['mobile'])

        # Get UOM
        uom = frappe.db.get_value("CN Sensor Var", sensor_var, "uom") or ""

        # Prepare alert log
        alert_log_name = parsed_date.strftime("%y%m%d") + "_" + device_doc.name

        # Try to get existing log
        alert_log = frappe.get_all(
            "CN Alert Log",
            filters={"name": alert_log_name},
            limit=1
        )

        # Value coming is the threshold. Current Value is in data_item child table for sensor_var
        threshold = str(value)
        for item in device_doc.data_item:
          if item.sensor_var == sensor_var:
            value = str(item.value)

        if alert_log:
            alert_log = frappe.get_doc("CN Alert Log", alert_log_name)
            if alert_log.alert_log_item:  # Updated fieldname
                do_start = True
                for row in alert_log.alert_log_item:  # Updated fieldname
                    if row.sensor_var == sensor_var:
                        if not row.to_time and reason == 'finish':
                            do_start = False
                            row.to_time = parsed_date
                            row.save()
                            
                if do_start and reason == 'start':
                    alert_log.append("alert_log_item", {  # Updated fieldname
                        'sensor_var': sensor_var,
                        'from_time': parsed_date,
                        'value': str(value),
                        'alert_type': cmd,
                        'by_email': 'Email' in alert_channel,
                        'by_sms': 'SMS' in alert_channel
                    })
                    alert_log.save()
        else:
            # Create new alert log
            alert_log = frappe.get_doc({
                "doctype": "CN Alert Log",
                "device": device_doc.name,
                "date": parsed_date.strftime("%Y-%m-%d"),
                "alert_log_item": [{  # Updated fieldname
                    'sensor_var': sensor_var,
                    'from_time': parsed_date,
                    'value': str(value),
                    'alert_type': cmd,
                    'by_email': 'Email' in alert_channel,
                    'by_sms': 'SMS' in alert_channel
                }]
            })
            alert_log.insert()

        frappe.db.commit()

        # Format date for messages
        date_alert = parsed_date.strftime("%d/%m/%y %H:%M")

        # Prepare messages
        base_message = f"""
        This message is generated by Automatic Alarm Monitoring on pibiConnect.
        Site time: {date_alert}.
        You are receiving this message because you are registered to receive alarms from pibiConnect.
        To stop receiving these alerts, please disable or remove yourself from the recipients channel in the admin view.
        """

        html_message = f"""
        <p>This message is generated by Automatic Alarm Monitoring on pibiConnect.</p>
        <p>Site time: {date_alert}.</p>
        <p>You are receiving this message because you are registered to receive alarms from pibiConnect.</p>
        <p>To stop receiving these alerts, please disable or remove yourself from the recipients channel in the admin view.</p>
        """

        # Generate alert text
        if reason == 'start':
            subject = f"PROBLEM - {device_doc.place}: Alert Started on {device_doc.alias}"
            alert_text = f"{sensor_var} {'high' if cmd == 'high' else 'low'} by {value}{uom} at {date_alert}. Please check."
        else:
            subject = f"RECOVERY - {device_doc.place}: Alert Finished on {device_doc.alias}"
            alert_text = f"{sensor_var} {'high' if cmd == 'high' else 'low'} finished by {value}{uom} at {date_alert}. Please check."

        # Send notifications
        if email_recipients:
            email_text = f"[Email pibiConnect]: {alert_text} in {device_doc.alias} ({device_doc.place})<br>{html_message}"
            email_args = {
                'recipients': email_recipients,
                'sender': None,
                'subject': subject,
                'message': cstr(email_text),
                'header': [_('pibiConnect Alert Information'), 'blue'],
                'delayed': False,
                'retry':3
            }
            frappe.enqueue(method=frappe.sendmail,queue='short',timeout=300,now=True,**email_args)  
            
        if sms_recipients:
            sms_text = f"[SMS pibiConnect]: {alert_text} in {device_doc.alias} ({device_doc.place})\n{base_message}"
            frappe.enqueue(
                'frappe.core.doctype.sms_settings.sms_settings.send_sms',
                receiver_list=sms_recipients,
                msg=sms_text,
                now=True
            )

        return {
            "message": "Alert processed successfully",
            "alert_log": alert_log_name
        }

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(
            frappe.get_traceback(),
            f"Error in manage_alert: {str(e)}"
        )
        return {"error": str(e)}