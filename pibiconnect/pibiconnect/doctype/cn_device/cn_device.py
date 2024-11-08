import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime
from pibiconnect.pibiconnect.api import manage_alert

class CNDevice(Document):
    pass