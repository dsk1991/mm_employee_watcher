import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_datetime

from mm_employee_watcher.state_machine import OPEN_SESSION_STATUSES, ensure_transition



class EmployeeWorkSession(Document):
	def validate(self):
		self.validate_transition()
		self.validate_values()
		self.enforce_single_primary_session()

	def validate_transition(self):
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			return
		try:
			ensure_transition(previous.status, self.status)
		except ValueError as exc:
			frappe.throw(_(str(exc)))

	def validate_values(self):
		if bool(self.reference_doctype) != bool(self.reference_name):
			frappe.throw(_("Reference DocType and Reference Name must be provided together"))
		if flt(self.target_qty) < 0 or flt(self.completed_qty) < 0:
			frappe.throw(_("Target Qty and Completed Qty cannot be negative"))
		if self.start_time and self.target_end_time:
			if get_datetime(self.target_end_time) <= get_datetime(self.start_time):
				frappe.throw(_("Target End Time must be after Start Time"))

	def enforce_single_primary_session(self):
		"""Hard rule (design doc section 7, #1): an employee can have only
		one Primary Active Work session open at a time. Enforced here so
		it holds no matter which client (Desk, WMS, HHT, API) creates the
		session — not just a UI convention."""
		if not self.is_primary or self.status not in OPEN_SESSION_STATUSES:
			return

		clashing = frappe.db.exists(
			"Employee Work Session",
			{
				"employee": self.employee,
				"is_primary": 1,
				"status": ["in", list(OPEN_SESSION_STATUSES)],
				"name": ["!=", self.name or ""],
			},
		)
		if clashing:
			frappe.throw(
				_("{0} already has an active primary work session ({1}). Complete, extend or block it before starting another.").format(
					self.employee, clashing
				)
			)
