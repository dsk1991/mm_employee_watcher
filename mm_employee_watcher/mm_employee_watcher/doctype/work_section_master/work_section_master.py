import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class WorkSectionMaster(Document):
	def validate(self):
		if cint(self.default_duration_minutes) <= 0:
			frappe.throw(_("Default Duration must be greater than zero minutes"))
		if self.section_qr_code:
			duplicate = frappe.db.exists(
				"Work Section Master",
				{
					"section_qr_code": self.section_qr_code,
					"name": ["!=", self.name or ""],
				},
			)
			if duplicate:
				frappe.throw(_("Section QR Code is already assigned to {0}").format(duplicate))
