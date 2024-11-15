import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

class CNAlertItem(Document):
    def validate(self):
        """
        Validate method to handle changes in alert states
        """
        if self.flags.in_alert_processing:
            return

        try:
            self.flags.in_alert_processing = True
            old_doc = self.get_doc_before_save()
            
            if not old_doc:
                return
                
            changes_made = False
            
            # Check for high alert changes
            if self.active_high != old_doc.active_high:
                self.handle_alert_state_change(
                    "high",
                    self.active_high,
                    self.high_value
                )
                changes_made = True

            # Check for low alert changes
            if self.active_low != old_doc.active_low:
                self.handle_alert_state_change(
                    "low",
                    self.active_low,
                    self.low_value
                )
                changes_made = True

            # Update last alert time if changes were made
            if changes_made:
                self.last_alert_time = now_datetime()

        finally:
            self.flags.in_alert_processing = False

    def handle_alert_state_change(self, command, is_active, value):
        """
        Handle the state change for a specific alert type
        """
        reason = "start" if is_active else "finish"
        # Use format without seconds
        current_time = now_datetime().strftime("%Y-%m-%d %H:%M")

        return {
            "sensor_var": self.sensor_var,
            "value": value,
            "command": command,
            "reason": reason,
            "datadate": current_time,
            "doc": self.parent
        }