import frappe
from frappe.model.document import Document


class EmployeeWorkQueue(Document):
	def validate(self):
		if self.work_activity:
			self.work_section = frappe.db.get_value(
				"Work Activity Master", self.work_activity, "work_section"
			)
