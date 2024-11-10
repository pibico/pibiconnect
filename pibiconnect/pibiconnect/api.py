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
def manage_alert(sensor_var=None, value=None, command=None, reason=None, datadate=None, doc=None, **kwargs):
    """
    Manage alerts by logging them and sending notifications.
    """
    try:
        # Log initial parameters
        frappe.logger().debug(f"""
        Initial parameters:
        sensor_var: {sensor_var}
        value: {value}
        command: {command}
        reason: {reason}
        datadate: {datadate}
        doc: {doc}
        kwargs: {kwargs}
        raw_data: {frappe.request.get_data() if frappe.request else 'No request data'}
        form_dict: {frappe.local.form_dict if hasattr(frappe.local, 'form_dict') else 'No form dict'}
        """)

        # Extract parameters from form_dict if not provided in function call
        if hasattr(frappe.local, 'form_dict'):
            sensor_var = sensor_var or frappe.local.form_dict.get('sensor_var')
            value = value or frappe.local.form_dict.get('value')
            command = command or frappe.local.form_dict.get('command')
            reason = reason or frappe.local.form_dict.get('reason')
            datadate = datadate or frappe.local.form_dict.get('datadate')
            doc = doc or frappe.local.form_dict.get('doc')

        # Log final parameters
        frappe.logger().debug(f"""
        Final parameters:
        sensor_var: {sensor_var}
        value: {value}
        command: {command}
        reason: {reason}
        datadate: {datadate}
        doc: {doc}
        """)

        # Input validation with specific messages
        missing_params = []
        if not sensor_var: missing_params.append("sensor_var")
        if not value: missing_params.append("value")
        if not command: missing_params.append("command")
        if not reason: missing_params.append("reason")
        if not datadate: missing_params.append("datadate")
        if not doc: missing_params.append("doc")

        if missing_params:
            error_msg = f"Missing required parameters: {', '.join(missing_params)}"
            frappe.logger().error(error_msg)
            frappe.throw(_(error_msg))

        if command not in ['high', 'low']:
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

        changes_made = False

        if alert_log:
            alert_log = frappe.get_doc("CN Alert Log", alert_log_name)
            if alert_log.alert_log_item:
                do_start = True
                for row in alert_log.alert_log_item:
                    if row.sensor_var == sensor_var:
                        if not row.to_time and reason == 'finish':
                            do_start = False
                            row.to_time = parsed_date
                            changes_made = True
                            break  # Exit loop after finding matching item

                if do_start and reason == 'start':
                    alert_log.append("alert_log_item", {
                        'sensor_var': sensor_var,
                        'from_time': parsed_date,
                        'value': str(value),
                        'alert_type': command,
                        'by_email': 'Email' in alert_channel,
                        'by_sms': 'SMS' in alert_channel
                    })
                    changes_made = True

            if changes_made:
                alert_log.save()
        else:
            # Create new alert log
            alert_log = frappe.get_doc({
                "doctype": "CN Alert Log",
                "device": device_doc.name,
                "date": parsed_date.strftime("%Y-%m-%d"),
                "alert_log_item": [{
                    'sensor_var': sensor_var,
                    'from_time': parsed_date,
                    'value': str(value),
                    'alert_type': command,
                    'by_email': 'Email' in alert_channel,
                    'by_sms': 'SMS' in alert_channel
                }]
            })
            alert_log.insert()
            changes_made = True

        if changes_made and reason == 'finish':
            # Update the corresponding CN Alert Item to deactivate the alert
            alert_item = frappe.db.get_value(
                'CN Alert Item',
                {'parent': doc, 'sensor_var': sensor_var},
                ['name', 'active_low', 'active_high'],
                as_dict=True
            )

            if alert_item:
                alert_item_doc = frappe.get_doc('CN Alert Item', alert_item.name)
                if command == 'low':
                    alert_item_doc.active_low = 0
                elif command == 'high':
                    alert_item_doc.active_high = 0
                alert_item_doc.last_alert_time = parsed_date
                alert_item_doc.save()

        frappe.db.commit()

        # Format date for messages
        date_alert = parsed_date.strftime("%d/%m/%y %H:%M")

        # Prepare messages
        base_message = f"""
        Este mensaje se ha generado por el Sistema de Monitoreo de Alarmas Automaticas de pibiConnect.
        Hora del lugar: {date_alert}.
        Estás recibiendo este mensaje porque se te ha registrado para recibir alarmas de pibiConnect.
        Para evitar recibir estas alertas, por favor solicitalo al Administrador del Sistema.
        """

        html_message = f"""
        <p>Este mensaje se ha generado por el Sistema de Monitoreo de Alarmas Automáticas de pibiConnect.</p>
        <p>Hora del lugar: {date_alert}.</p>
        <p>Estás recibiendo este mensaje porque se te ha registrado para recibir alarmas de pibiConnect.</p>
        <p>Para evitar recibir estas alertas, por favor solicitalo al Administrador del Sistema.</p>
        """

        # Generate alert text
        if reason == 'start':
            subject = f"PROBLEMA - {device_doc.place}: Alerta iniciada en {device_doc.alias}"
            alert_text = f"{sensor_var} {'high' if command == 'high' else 'low'} con {value}{uom} a {date_alert}. Compruebalo."
        else:
            subject = f"RECUPERACIÓN - {device_doc.place}: Alerta finalizada en {device_doc.alias}"
            alert_text = f"{sensor_var} {'high' if command == 'high' else 'low'} finalizada con {value}{uom} a {date_alert}. Compruebalo."

        # Send notifications
        if email_recipients:
            email_text = f"[Email pibiConnect]: {alert_text} en {device_doc.alias} ({device_doc.place})<br>{html_message}"
            email_args = {
                'recipients': email_recipients,
                'sender': None,
                'subject': subject,
                'message': cstr(email_text),
                'header': [_('pibiConnect Alert Information'), 'blue'],
                'delayed': False,
                'retry': 3
            }
            frappe.enqueue(method=frappe.sendmail, queue='short', timeout=300, now=True, **email_args)  
            
        if sms_recipients:
            sms_text = f"[SMS pibiConnect]: {alert_text} en {device_doc.alias} ({device_doc.place})\n{base_message}"
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