import frappe
from frappe.model.document import Document


class EmployeePunch(Document):
	"""One Punch In / Punch Out with the phone's location. Written only by
	mm_employee_watcher.api.punch, never edited by hand."""

	pass
