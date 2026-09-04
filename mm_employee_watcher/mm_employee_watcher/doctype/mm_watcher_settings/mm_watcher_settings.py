import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class MMWatcherSettings(Document):
	def validate(self):
		for field in ("idle_alert_minutes", "overdue_alert_minutes", "blocked_alert_minutes"):
			if cint(self.get(field)) < 0:
				frappe.throw(_("{0} cannot be negative").format(self.meta.get_label(field)))
		seen = set()
		for row in self.alert_recipients or []:
			if row.user in seen:
				frappe.throw(_("{0} is listed twice in Alert Recipients").format(row.user))
			seen.add(row.user)
