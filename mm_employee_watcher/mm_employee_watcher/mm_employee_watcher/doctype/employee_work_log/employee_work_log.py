import frappe
from frappe.model.document import Document


class EmployeeWorkLog(Document):
	"""Append-only audit trail. Never edited after creation."""

	def on_update(self):
		if not self.is_new():
			frappe.throw("Employee Work Log entries cannot be modified once created.")
