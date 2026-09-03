import frappe
from frappe import _
from frappe.model.document import Document


ACTIVE_STATUSES = ("Active", "Extended", "Blocked")


class EmployeeWorkSession(Document):
	def validate(self):
		self.enforce_single_primary_session()

	def enforce_single_primary_session(self):
		"""Hard rule (design doc section 7, #1): an employee can have only
		one Primary Active Work session open at a time. Enforced here so
		it holds no matter which client (Desk, WMS, HHT, API) creates the
		session — not just a UI convention."""
		if not self.is_primary or self.status not in ACTIVE_STATUSES:
			return

		clashing = frappe.db.exists(
			"Employee Work Session",
			{
				"employee": self.employee,
				"is_primary": 1,
				"status": ["in", list(ACTIVE_STATUSES)],
				"name": ["!=", self.name or ""],
			},
		)
		if clashing:
			frappe.throw(
				_("{0} already has an active primary work session ({1}). Complete, extend or block it before starting another.").format(
					self.employee, clashing
				)
			)
