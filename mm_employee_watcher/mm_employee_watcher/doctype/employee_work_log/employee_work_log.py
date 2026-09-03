import frappe
from frappe.model.document import Document


class EmployeeWorkLog(Document):
	"""Append-only audit trail. Never edited after creation."""

	def before_save(self):
		if not self.is_new():
			frappe.throw("Employee Work Log entries cannot be modified once created.")

	def on_trash(self):
		frappe.throw("Employee Work Log entries cannot be deleted.")
