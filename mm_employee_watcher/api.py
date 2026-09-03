"""Whitelisted API surface.

Every client — ERPNext Desk header bar, WMS, the Android HHT app — talks to
the watcher only through these methods, so all of them read/write exactly
the same state. See docs/backend-architecture.md section 5.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, add_to_date, flt, cint

from mm_employee_watcher.mm_employee_watcher.utils import (
	STATUS_WORKING,
	STATUS_IDLE,
	STATUS_BREAK,
	STATUS_BLOCKED,
	SESSION_ACTIVE,
	SESSION_EXTENDED,
	SESSION_BLOCKED,
	SESSION_COMPLETED,
	SESSION_CANCELLED,
	get_active_session,
	get_or_create_status,
	set_status,
	log_event,
)


def _get_employee_for_user(employee=None):
	"""Resolve the acting Employee: an explicit employee (supervisor/HHT
	acting on someone's behalf) or the logged-in user's own Employee."""
	if employee:
		return employee
	employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user})
	if not employee:
		frappe.throw(_("No Employee record linked to this user"))
	return employee


@frappe.whitelist()
def start_work(
	work_activity: str,
	employee: str | None = None,
	target_qty: float | None = None,
	target_minutes: int | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	source_app: str = "ERPNext",
):
	"""Start a new Primary Active Work session. Refuses if the employee
	already has one open — enforces 'one primary active work at a time'
	at the API layer (the DocType also validates this server-side)."""
	employee = _get_employee_for_user(employee)

	existing = get_active_session(employee)
	if existing:
		frappe.throw(
			_("{0} already has an active session ({1}). Complete, extend or block it first.").format(
				employee, existing.name
			)
		)

	activity = frappe.get_doc("Work Activity Master", work_activity)
	minutes = cint(target_minutes) or cint(activity.default_duration_minutes) or 60

	session = frappe.get_doc(
		{
			"doctype": "Employee Work Session",
			"employee": employee,
			"work_activity": work_activity,
			"source_app": source_app,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"status": SESSION_ACTIVE,
			"is_primary": 1,
			"start_time": now_datetime(),
			"target_end_time": add_to_date(now_datetime(), minutes=minutes),
			"target_qty": target_qty,
			"completed_qty": 0,
		}
	)
	session.insert(ignore_permissions=True)

	log_event(employee, session.name, "Start")
	set_status(employee, STATUS_WORKING, session.name)
	return session.as_dict()


@frappe.whitelist()
def complete_work(work_session: str, completed_qty: float | None = None, remarks: str | None = None):
	"""Employee taps Done (or an integration hook calls this automatically
	when the source WMS/production document finishes)."""
	session = frappe.get_doc("Employee Work Session", work_session)
	session.status = SESSION_COMPLETED
	session.actual_end_time = now_datetime()
	if completed_qty is not None:
		session.completed_qty = flt(completed_qty)
	if remarks:
		session.notes = remarks
	session.save(ignore_permissions=True)

	log_event(session.employee, session.name, "Complete", qty=session.completed_qty, remarks=remarks)
	set_status(session.employee, STATUS_IDLE, None)
	return {"next_work": get_next_work(session.employee)}


@frappe.whitelist()
def extend_work(work_session: str, minutes: int):
	"""Extend the current target_end_time by 15 / 30 / 60 / custom minutes."""
	minutes = cint(minutes)
	session = frappe.get_doc("Employee Work Session", work_session)
	session.target_end_time = add_to_date(session.target_end_time, minutes=minutes)
	session.extended_minutes = cint(session.extended_minutes) + minutes
	session.status = SESSION_EXTENDED
	session.save(ignore_permissions=True)

	log_event(session.employee, session.name, "Extend", remarks=f"+{minutes} min")
	set_status(session.employee, STATUS_WORKING, session.name)
	return session.as_dict()


@frappe.whitelist()
def pause_work(work_session: str, reason: str | None = None):
	session = frappe.get_doc("Employee Work Session", work_session)
	log_event(session.employee, session.name, "Pause", remarks=reason)
	set_status(session.employee, STATUS_IDLE, session.name)
	return {"ok": True}


@frappe.whitelist()
def resume_work(work_session: str):
	session = frappe.get_doc("Employee Work Session", work_session)
	log_event(session.employee, session.name, "Resume")
	set_status(session.employee, STATUS_WORKING, session.name)
	return {"ok": True}


@frappe.whitelist()
def mark_blocked(work_session: str, reason: str):
	session = frappe.get_doc("Employee Work Session", work_session)
	session.status = SESSION_BLOCKED
	session.blocked_reason = reason
	session.save(ignore_permissions=True)

	log_event(session.employee, session.name, "Blocked", remarks=reason)
	set_status(session.employee, STATUS_BLOCKED, session.name)
	return {"ok": True}


@frappe.whitelist()
def mark_break(employee: str | None = None, reason: str | None = None):
	"""Authorized lunch/tea break — a distinct state from IDLE."""
	employee = _get_employee_for_user(employee)
	set_status(employee, STATUS_BREAK, None)
	return {"ok": True}


@frappe.whitelist()
def get_my_status(employee: str | None = None):
	"""What the Smart Work Bar polls/subscribes to in every app."""
	employee = _get_employee_for_user(employee)
	status = frappe.db.get_value(
		"Employee Current Status",
		{"employee": employee},
		["status", "current_session", "status_since"],
		as_dict=True,
	)
	if not status:
		return {"employee": employee, "status": "OFFLINE", "current_session": None}

	result = {"employee": employee, **status}
	if status.current_session:
		result["session"] = frappe.get_doc("Employee Work Session", status.current_session).as_dict()
	return result


@frappe.whitelist()
def get_next_work(employee: str | None = None):
	"""Next Employee Work Queue item for this employee, by priority — used
	both by the 'you are free, next priority work is X' prompt and by the
	Work Bar when idle."""
	employee = _get_employee_for_user(employee)
	next_item = frappe.get_all(
		"Employee Work Queue",
		filters={"employee": employee, "status": "Pending"},
		fields=["name", "work_activity", "reference_doctype", "reference_name", "target_qty", "priority"],
		order_by="priority desc, creation asc",
		limit=1,
	)
	return next_item[0] if next_item else None


@frappe.whitelist()
def heartbeat(employee: str | None = None):
	"""Called periodically by every connected client so the offline
	watchdog can tell a genuinely idle employee from a dropped connection."""
	employee = _get_employee_for_user(employee)
	status = get_or_create_status(employee)
	status.db_set("last_heartbeat", now_datetime(), update_modified=False)
	return {"ok": True, "server_time": now_datetime()}
