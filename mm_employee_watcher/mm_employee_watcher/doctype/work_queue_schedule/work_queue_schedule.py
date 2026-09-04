import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate


class WorkQueueSchedule(Document):
	def validate(self):
		if self.recurrence == "Weekly" and not self.weekday:
			frappe.throw(_("Pick a Day of Week for a weekly schedule"))
		if self.recurrence == "Monthly" and not (1 <= cint(self.day_of_month) <= 31):
			frappe.throw(_("Day of Month must be between 1 and 31"))
		if self.recurrence == "Specific Dates":
			self._parse_specific_dates()
		if not self.department and not self.assignees:
			frappe.throw(_("Add at least one assignee, or set a Whole Department"))

	def _parse_specific_dates(self):
		dates = []
		for line in (self.specific_dates or "").splitlines():
			line = line.strip()
			if not line:
				continue
			try:
				dates.append(getdate(line))
			except Exception:
				frappe.throw(_("'{0}' is not a valid YYYY-MM-DD date").format(line))
		return dates
