import frappe
from frappe import _
from frappe.model.document import Document


class WorkShift(Document):
	def validate(self):
		if self.start_time == self.end_time:
			frappe.throw(_("Shift start and end time cannot be the same"))
		days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
		off = [d.strip()[:3].title() for d in (self.weekly_off or "").replace(";", ",").split(",") if d.strip()]
		if any(d.lower() not in days for d in off):
			frappe.throw(_("Weekly Off must be days like Sun, Mon"))
		self.weekly_off = ", ".join(off)
