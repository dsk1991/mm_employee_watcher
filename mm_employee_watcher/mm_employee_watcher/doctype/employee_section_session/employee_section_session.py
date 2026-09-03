import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime

from mm_employee_watcher.state_machine import OPEN_SECTION_STATUSES, ensure_section_transition


class EmployeeSectionSession(Document):
	def validate(self):
		self.validate_transition()
		self.validate_times()
		self.enforce_single_active_section()

	def validate_transition(self):
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			return
		try:
			ensure_section_transition(previous.status, self.status)
		except ValueError as exc:
			frappe.throw(_(str(exc)))

	def validate_times(self):
		if self.start_time and self.target_end_time:
			if get_datetime(self.target_end_time) <= get_datetime(self.start_time):
				frappe.throw(_("Section Target End Time must be after Start Time"))
		if self.actual_end_time and self.start_time:
			if get_datetime(self.actual_end_time) < get_datetime(self.start_time):
				frappe.throw(_("Section End Time cannot be before Start Time"))

	def enforce_single_active_section(self):
		if self.status not in OPEN_SECTION_STATUSES:
			return
		clashing = frappe.db.exists(
			"Employee Section Session",
			{
				"employee": self.employee,
				"status": ["in", list(OPEN_SECTION_STATUSES)],
				"name": ["!=", self.name or ""],
			},
		)
		if clashing:
			frappe.throw(
				_("{0} already has an active section ({1}). End it before starting another.").format(
					self.employee, clashing
				)
			)

