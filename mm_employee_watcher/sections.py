"""Per-document work "sections" for warehouse screens (Picking, Packing,
Putaway, Receiving).

The moment a staff member starts working on a document, a section (an
Employee Work Session referencing that document) is running for them:

* Only one section runs per employee. Starting a different document parks the
  running one (status Paused, no longer primary) - its timer stops - and
  coming back to the parked document resumes the same section.
* A document is worked by one person at a time. If another employee has an
  open section on it, the second person is told who is on it and is not
  allowed to start.
* Finishing the document (submit) completes its sections.

Nothing is stored on the Pick List / Delivery Note / Stock Entry itself.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime

from mm_employee_watcher import api as tracker_api
from mm_employee_watcher.state_machine import (
	OPEN_SESSION_STATUSES,
	SESSION_ACTIVE,
	SESSION_BLOCKED,
	SESSION_EXTENDED,
	SESSION_PAUSED,
)
from mm_employee_watcher.utils import (
	STATUS_WORKING,
	duty_state,
	get_active_session,
	get_employee_for_user,
	is_tracking_enabled,
	set_status,
)


def _open():
	return ["in", list(OPEN_SESSION_STATUSES)]


def find_other_worker(reference_doctype, reference_name, employee):
	"""Another employee's open section on this document, if any."""
	rows = frappe.get_all(
		"Employee Work Session",
		filters={
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"status": _open(),
			"employee": ["!=", employee],
		},
		fields=["name", "employee", "employee_name", "status", "work_activity"],
		order_by="creation desc",
		limit=1,
	)
	return rows[0] if rows else None


def _my_section(employee, reference_doctype, reference_name):
	rows = frappe.get_all(
		"Employee Work Session",
		filters={
			"employee": employee,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"status": _open(),
		},
		pluck="name",
		order_by="creation desc",
		limit=1,
	)
	return frappe.get_doc("Employee Work Session", rows[0]) if rows else None


def park_session(session, reason=None):
	"""Set a section aside: its timer stops and it stops being the employee's
	primary session, so another one can start. Resume it with unpark_session."""
	if session.status in (SESSION_ACTIVE, SESSION_EXTENDED):
		session.status = SESSION_PAUSED
		session.is_primary = 0
		session.save(ignore_permissions=True)
		tracker_api._log_session_event(session, "Pause", remarks=reason)
	elif session.is_primary:
		session.is_primary = 0
		session.save(ignore_permissions=True)


def unpark_session(session):
	"""Make a parked (or blocked) section the running one again."""
	was_blocked = session.status == SESSION_BLOCKED
	session.status = SESSION_ACTIVE
	session.is_primary = 1
	session.blocked_reason = None
	if not session.target_end_time or get_datetime(session.target_end_time) < add_to_date(now_datetime(), minutes=5):
		minutes = frappe.db.get_value("Work Activity Master", session.work_activity, "default_duration_minutes") or 60
		session.target_end_time = add_to_date(now_datetime(), minutes=int(minutes))
	session.save(ignore_permissions=True)
	tracker_api._log_session_event(session, "Unblocked" if was_blocked else "Resume")
	set_status(session.employee, STATUS_WORKING, session.name)


def park_current_session(employee, reason=None):
	current = get_active_session(employee)
	if current:
		park_session(current, reason)
	return current.name if current else None


def _link_queue_item(session, work_activity, reference_doctype, reference_name):
	"""If this document is waiting in the pool, take it off the pool."""
	item = frappe.db.get_value(
		"Employee Work Queue",
		{
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"work_activity": work_activity,
			"status": "Pending",
		},
		["name", "employee"],
		as_dict=True,
	)
	if not item or (item.employee and item.employee != session.employee):
		return
	frappe.db.set_value(
		"Employee Work Queue",
		item.name,
		{"employee": session.employee, "status": "Assigned", "assigned_at": now_datetime()},
	)
	session.db_set("queue_item", item.name)
	tracker_api.publish_pool_change()


def blocked_message(other, reference_name):
	who = other.get("employee_name") or other.get("employee")
	state = _("abhi kaam kar raha hai") if other.get("status") != SESSION_PAUSED else _("ne kaam beech mein roka hai")
	return _("{0} par {1} {2}. Pehle unse ya supervisor se baat karein.").format(reference_name, who, state)


@frappe.whitelist(methods=["POST"])
def enter_section(work_activity, reference_doctype, reference_name):
	"""Start, resume or keep running this employee's section on a document.

	Returns {"action": "started" | "resumed" | "running"} on success,
	{"blocked": True, "message", "by", "by_name"} when someone else is on the
	document, or {"tracking": False} / {"skipped": True} when tracking does not
	apply (tracking off, or outside their shift)."""
	employee = get_employee_for_user()
	if not employee or not is_tracking_enabled(employee):
		return {"tracking": False}

	other = find_other_worker(reference_doctype, reference_name, employee)
	if other:
		return {
			"tracking": True,
			"blocked": True,
			"by": other.employee,
			"by_name": other.employee_name or other.employee,
			"message": blocked_message(other, reference_name),
		}

	duty = duty_state(employee)
	if not duty["on_duty"]:
		return {"tracking": True, "skipped": True, "reason": duty["reason"]}

	current = get_active_session(employee)
	mine = _my_section(employee, reference_doctype, reference_name)
	if mine:
		if current and current.name == mine.name:
			return {"tracking": True, "action": "running", "session": mine.name}
		if current:
			park_session(current, _("Switched to {0}").format(reference_name))
		unpark_session(mine)
		return {"tracking": True, "action": "resumed", "session": mine.name}

	if current:
		park_session(current, _("Switched to {0}").format(reference_name))
	session = tracker_api._create_session(
		employee,
		work_activity,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		source_app="WMS",
		description=_("{0} {1}").format(reference_doctype, reference_name),
	)
	_link_queue_item(session, work_activity, reference_doctype, reference_name)
	return {"tracking": True, "action": "started", "session": session.name}


def complete_reference_sessions(reference_doctype, reference_name, remarks=None):
	"""The document was submitted: finish every open section on it."""
	names = frappe.get_all(
		"Employee Work Session",
		filters={"reference_doctype": reference_doctype, "reference_name": reference_name, "status": _open()},
		pluck="name",
	)
	for name in names:
		tracker_api._complete_session(frappe.get_doc("Employee Work Session", name), remarks=remarks)
	return len(names)


def parked_sessions(employee):
	"""Sections the employee left half-done (they can resume them)."""
	return frappe.get_all(
		"Employee Work Session",
		filters={"employee": employee, "status": SESSION_PAUSED, "is_primary": 0},
		fields=["name", "work_activity", "reference_doctype", "reference_name", "start_time"],
		order_by="modified desc",
		limit=20,
	)


@frappe.whitelist(methods=["POST"])
def resume_parked(work_session):
	"""Go back to a section that was set aside."""
	session = frappe.get_doc("Employee Work Session", work_session)
	employee = get_employee_for_user()
	if session.employee != employee:
		frappe.throw(_("This work section belongs to another employee"), frappe.PermissionError)
	if session.status not in OPEN_SESSION_STATUSES:
		frappe.throw(_("This work section is already finished"))
	if session.reference_doctype:
		other = find_other_worker(session.reference_doctype, session.reference_name, employee)
		if other:
			frappe.throw(blocked_message(other, session.reference_name))
	current = get_active_session(employee)
	if current and current.name != session.name:
		park_session(current, _("Switched to {0}").format(session.reference_name or session.work_activity))
	unpark_session(session)
	return {"ok": True, "reference_doctype": session.reference_doctype, "reference_name": session.reference_name}
