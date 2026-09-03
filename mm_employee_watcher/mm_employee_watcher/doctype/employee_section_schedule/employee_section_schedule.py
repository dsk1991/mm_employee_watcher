import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime


class EmployeeSectionSchedule(Document):
	def validate(self):
		start = get_datetime(self.scheduled_start)
		end = get_datetime(self.scheduled_end)
		if end <= start:
			frappe.throw(_("Scheduled End must be after Scheduled Start"))

		if self.default_work_activity:
			activity_section = frappe.db.get_value(
				"Work Activity Master", self.default_work_activity, "work_section"
			)
			if activity_section and activity_section != self.work_section:
				frappe.throw(_("Default Work Activity must belong to the scheduled section"))

		if self.status in {"Cancelled", "Skipped"}:
			return
		overlaps = frappe.get_all(
			"Employee Section Schedule",
			filters=[
				["employee", "=", self.employee],
				["name", "!=", self.name or ""],
				["status", "not in", ["Cancelled", "Skipped"]],
				["scheduled_start", "<", self.scheduled_end],
				["scheduled_end", ">", self.scheduled_start],
			],
			pluck="name",
			limit=1,
		)
		if overlaps:
			frappe.throw(_("This employee already has an overlapping section schedule ({0})").format(overlaps[0]))
