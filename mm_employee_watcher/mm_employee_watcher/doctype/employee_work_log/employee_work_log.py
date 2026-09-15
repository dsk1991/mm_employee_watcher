import frappe
from frappe.model.document import Document


class EmployeeWorkLog(Document):
	"""Append-only audit trail: entries are never edited once created.

	Deletion is allowed (gated by the DocType's own permissions, System
	Manager only) so a log entry that is blocking deletion of the document
	it references (Sales Invoice, Payment Entry, ...) can be cleared out of
	the way instead of being permanently stuck."""

	def before_save(self):
		if not self.is_new():
			frappe.throw("Employee Work Log entries cannot be modified once created.")
