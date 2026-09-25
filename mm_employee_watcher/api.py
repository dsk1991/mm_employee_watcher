"""Whitelisted API surface.

Every client — ERPNext Desk floating work widget/popup, WMS, the Android
HHT app — talks to the watcher only through these methods, so all of them
read/write exactly the same state. See docs/backend-architecture.md section 5.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, add_to_date, flt, cint, get_datetime, getdate, time_diff_in_seconds, today

from mm_employee_watcher import timing
from mm_employee_watcher.utils import (
	STATUS_WORKING,
	STATUS_IDLE,
	STATUS_BREAK,
	STATUS_BLOCKED,
	SESSION_ACTIVE,
	SESSION_EXTENDED,
	SESSION_PAUSED,
	SESSION_BLOCKED,
	SESSION_COMPLETED,
	SESSION_CANCELLED,
	get_active_session,
	get_or_create_status,
	get_employee_for_user,
	is_tracking_enabled,
	publish_status,
	set_status,
	log_event,
	duty_state,
	get_work_shift,
	last_punch,
	STATUS_OFF_DUTY,
)

MANAGER_ROLES = {"System Manager", "Employee Watcher Manager"}
OPEN_SESSION_STATUSES = {SESSION_ACTIVE, SESSION_EXTENDED, SESSION_PAUSED, SESSION_BLOCKED}

# The employee-facing "what work are you starting?" prompt (Desk widget,
# mobile PWA, Staff App) no longer asks the employee to pick a Work Activity
# Master — they only describe the work in free text. Every session created
# that way is filed under this one generic activity instead.
GENERAL_WORK_ACTIVITY = "General Work"

DESKTOP_ACTIVITY_MAP = {
	"Sales Invoice": "Sales Invoice Creation",
	"Payment Entry": "Payment Entry",
}
ALLOWED_DESKTOP_EVENTS = {
	"Screen Opened",
	"Document Created",
	"Document Submitted",
	"Report Viewed",
}


def _has_manager_role():
	return bool(MANAGER_ROLES.intersection(frappe.get_roles()))


def _get_employee_for_user(employee=None):
	"""Resolve the acting Employee: an explicit employee (supervisor/HHT
	acting on someone's behalf) or the logged-in user's own Employee
	(requirement #2 — Employee master is linked to User via user_id, so a
	plain login is enough to know who this is). An ordinary employee may
	never use this argument to impersonate another employee."""
	acting_employee = get_employee_for_user()
	if employee:
		if employee == acting_employee:
			return employee
		if not _has_manager_role():
			frappe.throw(_("You cannot act on behalf of another employee"), frappe.PermissionError)
		if not frappe.db.exists("Employee", {"name": employee, "status": "Active"}):
			frappe.throw(_("Employee {0} is not active").format(employee))
		return employee
	if not acting_employee:
		frappe.throw(_("No active Employee record linked to this user"))
	return acting_employee


def _get_session_for_actor(work_session):
	"""Return a session only when the caller owns it or is a watcher manager."""
	session = frappe.get_doc("Employee Work Session", work_session)
	acting_employee = get_employee_for_user()
	if session.employee != acting_employee and not _has_manager_role():
		frappe.throw(_("You cannot change another employee's work session"), frappe.PermissionError)
	return session


def _log_session_event(session, event_type, qty=None, remarks=None):
	log_event(
		session.employee,
		session.name,
		event_type,
		qty=qty,
		remarks=remarks,
		source_app=session.source_app,
		reference_doctype=session.reference_doctype,
		reference_name=session.reference_name,
	)


def _require_session_status(session, allowed_statuses, action):
	if session.status not in allowed_statuses:
		frappe.throw(
			_("Cannot {0} a work session with status {1}").format(action, session.status)
		)


def _create_session(
	employee,
	work_activity,
	target_qty=None,
	minutes=None,
	reference_doctype=None,
	reference_name=None,
	source_app="ERPNext",
	description=None,
	queue_item=None,
):
	"""Shared by start_work() and the auto-chain in complete_work() — one
	code path for 'open a new Primary Active Work session'."""
	activity = frappe.get_doc("Work Activity Master", work_activity)
	if not frappe.has_permission("Work Activity Master", "read", doc=activity):
		frappe.throw(_("You do not have permission to use this work activity"), frappe.PermissionError)

	minutes = cint(minutes) if minutes is not None else cint(activity.default_duration_minutes) or 60
	if minutes <= 0:
		frappe.throw(_("Duration must be greater than zero minutes"))
	if target_qty is not None and flt(target_qty) < 0:
		frappe.throw(_("Target Qty cannot be negative"))
	if bool(reference_doctype) != bool(reference_name):
		frappe.throw(_("Reference DocType and Reference Name must be provided together"))
	if reference_doctype and not frappe.db.exists(reference_doctype, reference_name):
		frappe.throw(_("Referenced {0} {1} does not exist").format(reference_doctype, reference_name))
	if reference_doctype and not frappe.has_permission(reference_doctype, "read", doc=reference_name):
		frappe.throw(_("You do not have permission to use the referenced document"), frappe.PermissionError)

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
			"notes": description,
			"queue_item": queue_item,
		}
	)
	session.insert(ignore_permissions=True)

	_log_session_event(session, "Start")
	set_status(employee, STATUS_WORKING, session.name)
	return session


@frappe.whitelist()
def start_work(
	work_activity: str | None = None,
	employee: str | None = None,
	target_qty: float | None = None,
	target_minutes: int | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	source_app: str = "ERPNext",
	description: str | None = None,
):
	"""Start a new Primary Active Work session — from the Desk 'Work Now'
	popup, WMS, or the HHT app. Refuses if the employee already has one
	open (the DocType also validates this server-side).

	The employee-facing prompt only asks "what exactly will you do?" — it
	does not pass work_activity, so this defaults to GENERAL_WORK_ACTIVITY.
	WMS/HHT integrations that already know their activity keep passing it
	explicitly."""
	employee = _get_employee_for_user(employee)
	description = (description or "").strip()
	if not description:
		frappe.throw(_("Work Description is required"))

	if not is_tracking_enabled(employee):
		frappe.throw(_("Work tracking is disabled for this user"))

	existing = get_active_session(employee)
	if existing:
		frappe.throw(
			_("{0} already has an active session ({1}). Complete, extend or block it first.").format(
				employee, existing.name
			)
		)

	session = _create_session(
		employee,
		work_activity or GENERAL_WORK_ACTIVITY,
		target_qty=target_qty,
		minutes=target_minutes,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		source_app=source_app,
		description=description,
	)
	return session.as_dict()


@frappe.whitelist()
def start_reference_work(
	work_activity: str,
	reference_doctype: str,
	reference_name: str,
	target_qty: float | None = None,
	target_minutes: int | None = None,
	source_app: str = "WMS",
):
	"""Idempotent WMS/HHT start endpoint keyed by employee + reference.

	A repeated mobile tap returns the existing matching session instead of
	creating a duplicate. A different open primary session remains a hard
	conflict and must be completed or cancelled explicitly.
	"""
	employee = _get_employee_for_user()
	if not is_tracking_enabled(employee):
		return {"tracking": False, "created": False, "session": None}

	existing = get_active_session(employee)
	if existing:
		if (
			existing.work_activity == work_activity
			and existing.reference_doctype == reference_doctype
			and existing.reference_name == reference_name
		):
			return {"tracking": True, "created": False, "session": existing.as_dict()}
		if (
			existing.work_activity == work_activity
			and not existing.reference_doctype
			and not existing.reference_name
		):
			if not frappe.db.exists(reference_doctype, reference_name):
				frappe.throw(_("Referenced {0} {1} does not exist").format(reference_doctype, reference_name))
			if not frappe.has_permission(reference_doctype, "read", doc=reference_name):
				frappe.throw(_("You do not have permission to use the referenced document"), frappe.PermissionError)
			existing.reference_doctype = reference_doctype
			existing.reference_name = reference_name
			existing.source_app = source_app
			if target_qty is not None:
				existing.target_qty = flt(target_qty)
			existing.save(ignore_permissions=True)
			_log_session_event(existing, "Screen Opened", remarks=_("Linked WMS document"))
			publish_status(employee)
			return {
				"tracking": True,
				"created": False,
				"adopted_reference": True,
				"session": existing.as_dict(),
			}

	completed = frappe.get_all(
		"Employee Work Session",
		filters={
			"employee": employee,
			"work_activity": work_activity,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"status": SESSION_COMPLETED,
		},
		fields=["name"],
		order_by="creation desc",
		limit=1,
	)
	if completed:
		return {
			"tracking": True,
			"created": False,
			"completed": True,
			"session": frappe.get_doc("Employee Work Session", completed[0].name).as_dict(),
		}
	if existing:
		frappe.throw(
			_("You already have active work {0} ({1}). Finish it before starting {2}.").format(
				existing.work_activity, existing.name, reference_name
			)
		)

	session = _create_session(
		employee,
		work_activity,
		target_qty=target_qty,
		minutes=target_minutes,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		source_app=source_app,
	)
	return {"tracking": True, "created": True, "session": session.as_dict()}


def _apply_time_accounting(session):
	"""Fill waiting / working / paused seconds on a session that is ending.
	Never blocks completing the work — accounting problems are only logged."""
	try:
		start = get_datetime(session.start_time)
		end = get_datetime(session.actual_end_time)
		events = frappe.get_all(
			"Employee Work Log",
			filters={"work_session": session.name},
			fields=["event_type", "event_time"],
			order_by="event_time asc, creation asc",
			as_list=True,
		)
		parts = timing.compute_time_breakdown(events, start, end)
		session.working_seconds = int(parts["working"])
		session.paused_seconds = int(parts["paused"])
		if session.queue_item:
			queued_at = frappe.db.get_value("Employee Work Queue", session.queue_item, "creation")
			session.waiting_seconds = int(timing.waiting_seconds(queued_at, start))
	except Exception:
		frappe.log_error(title="MM Employee Watcher time accounting failed", message=frappe.get_traceback())


def _complete_session(session, completed_qty=None, remarks=None):
	"""Close a work session and drop the employee to IDLE. Queued work is
	never auto-started — the employee picks the next task from their queue
	in the widget."""
	if session.status == SESSION_COMPLETED:
		return {"already_completed": True}
	_require_session_status(session, OPEN_SESSION_STATUSES, _("complete"))

	session.status = SESSION_COMPLETED
	session.actual_end_time = now_datetime()
	_apply_time_accounting(session)
	if completed_qty is not None:
		completed_qty = flt(completed_qty)
		if completed_qty < 0:
			frappe.throw(_("Completed Qty cannot be negative"))
		session.completed_qty = completed_qty
	if remarks:
		session.notes = remarks
	session.save(ignore_permissions=True)

	if session.queue_item and frappe.db.exists("Employee Work Queue", session.queue_item):
		frappe.db.set_value("Employee Work Queue", session.queue_item, "status", "Completed")

	_log_session_event(session, "Complete", qty=session.completed_qty, remarks=remarks)
	set_status(session.employee, STATUS_IDLE, None)

	return {"already_completed": False}


@frappe.whitelist()
def complete_work(work_session: str, completed_qty: float | None = None, remarks: str | None = None):
	"""Employee taps Done (or an integration hook calls this when the source
	WMS/production document finishes). The employee then goes IDLE and picks
	their next task from the queue — nothing auto-starts."""
	return _complete_session(_get_session_for_actor(work_session), completed_qty, remarks)


@frappe.whitelist()
def end_work(work_session: str, remarks: str | None = None, completed_qty: float | None = None):
	"""Employee taps 'End Work' on the floating widget and types what they
	actually did. Same effect as complete_work — a clearer name for the
	Desk-side end-of-work prompt."""
	remarks = (remarks or "").strip()
	if not remarks:
		frappe.throw(_("Please describe what you worked on"))
	return _complete_session(_get_session_for_actor(work_session), completed_qty, remarks)


@frappe.whitelist()
def complete_reference_work(
	reference_doctype: str,
	reference_name: str,
	completed_qty: float | None = None,
	remarks: str | None = None,
):
	"""Idempotently complete the caller's open WMS/HHT reference session."""
	employee = _get_employee_for_user()
	rows = frappe.get_all(
		"Employee Work Session",
		filters={
			"employee": employee,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"status": ["in", list(OPEN_SESSION_STATUSES)],
		},
		fields=["name"],
		order_by="creation desc",
		limit=1,
	)
	if not rows:
		completed = frappe.get_all(
			"Employee Work Session",
			filters={
				"employee": employee,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"status": SESSION_COMPLETED,
			},
			fields=["name"],
			order_by="creation desc",
			limit=1,
		)
		if completed:
			return {"already_completed": True, "work_session": completed[0].name}
		frappe.throw(_("No open work session found for {0} {1}").format(reference_doctype, reference_name))
	result = _complete_session(frappe.get_doc("Employee Work Session", rows[0].name), completed_qty, remarks)
	result["work_session"] = rows[0].name
	return result


@frappe.whitelist()
def update_progress(work_session: str, completed_qty: float):
	"""Update live progress from WMS without allowing cross-employee writes."""
	session = _get_session_for_actor(work_session)
	_require_session_status(session, OPEN_SESSION_STATUSES, _("update"))
	completed_qty = flt(completed_qty)
	if completed_qty < 0:
		frappe.throw(_("Completed Qty cannot be negative"))
	session.completed_qty = completed_qty
	session.save(ignore_permissions=True)
	_log_session_event(session, "Progress Updated", qty=completed_qty)
	publish_status(session.employee)
	return {"ok": True, "completed_qty": session.completed_qty}


@frappe.whitelist()
def extend_work(work_session: str, minutes: int):
	"""Extend the current target_end_time by 15 / 30 / 60 / custom minutes."""
	minutes = cint(minutes)
	if minutes <= 0:
		frappe.throw(_("Extension must be greater than zero minutes"))
	session = _get_session_for_actor(work_session)
	_require_session_status(session, {SESSION_ACTIVE, SESSION_EXTENDED}, _("extend"))
	session.target_end_time = add_to_date(session.target_end_time, minutes=minutes)
	session.extended_minutes = cint(session.extended_minutes) + minutes
	session.status = SESSION_EXTENDED
	session.expiry_notified_at = None
	session.save(ignore_permissions=True)

	_log_session_event(session, "Extend", remarks=f"+{minutes} min")
	set_status(session.employee, STATUS_WORKING, session.name)
	return session.as_dict()


@frappe.whitelist()
def pause_work(work_session: str, reason: str | None = None):
	session = _get_session_for_actor(work_session)
	_require_session_status(session, {SESSION_ACTIVE, SESSION_EXTENDED}, _("pause"))
	session.status = SESSION_PAUSED
	session.save(ignore_permissions=True)
	_log_session_event(session, "Pause", remarks=reason)
	set_status(session.employee, STATUS_IDLE, session.name)
	return {"ok": True}


@frappe.whitelist()
def resume_work(work_session: str):
	session = _get_session_for_actor(work_session)
	_require_session_status(session, {SESSION_PAUSED, SESSION_BLOCKED}, _("resume"))
	was_blocked = session.status == SESSION_BLOCKED
	session.status = SESSION_ACTIVE
	session.blocked_reason = None
	session.save(ignore_permissions=True)
	_log_session_event(session, "Unblocked" if was_blocked else "Resume")
	set_status(session.employee, STATUS_WORKING, session.name)
	return {"ok": True}


@frappe.whitelist()
def mark_blocked(work_session: str, reason: str):
	if not (reason or "").strip():
		frappe.throw(_("Blocked reason is required"))
	session = _get_session_for_actor(work_session)
	_require_session_status(
		session, {SESSION_ACTIVE, SESSION_EXTENDED, SESSION_PAUSED}, _("block")
	)
	session.status = SESSION_BLOCKED
	session.blocked_reason = reason.strip()
	session.save(ignore_permissions=True)

	_log_session_event(session, "Blocked", remarks=reason)
	set_status(session.employee, STATUS_BLOCKED, session.name)
	return {"ok": True}


@frappe.whitelist()
def mark_break(employee: str | None = None, reason: str | None = None, minutes: int | None = None):
	"""Authorized lunch/tea break — a distinct state from IDLE. Also the
	escape hatch from the forced 'Work Now' popup. `minutes` is the planned
	break length; once it passes, check_break_overrun() flips the employee to
	IDLE so the idle nag/alert takes over."""
	employee = _get_employee_for_user(employee)
	minutes = cint(minutes) or 15
	session = get_active_session(employee)
	if session and session.status in {SESSION_ACTIVE, SESSION_EXTENDED}:
		session.status = SESSION_PAUSED
		session.save(ignore_permissions=True)
		_log_session_event(session, "Pause", remarks=reason or _("Authorized break"))
	elif session and session.status == SESSION_BLOCKED:
		frappe.throw(_("Resolve or complete the blocked work before starting a break"))
	log_event(
		employee,
		session.name if session else None,
		"Break Start",
		remarks=_("{0} ({1} min)").format(reason or _("Authorized break"), minutes),
		source_app="ERPNext",
	)
	set_status(employee, STATUS_BREAK, session.name if session else None)
	break_until = add_to_date(now_datetime(), minutes=minutes)
	frappe.db.set_value(
		"Employee Current Status",
		{"employee": employee},
		"break_until",
		break_until,
		update_modified=False,
	)
	return {"ok": True, "break_until": break_until, "minutes": minutes}


@frappe.whitelist()
def get_my_queue(employee: str | None = None):
	"""Everything still pending in this employee's work queue, so they can
	see what's assigned and pick the next task themselves."""
	employee = _get_employee_for_user(employee)
	return frappe.get_all(
		"Employee Work Queue",
		filters={"employee": employee, "status": ["in", ["Pending", "Assigned"]]},
		fields=[
			"name",
			"work_activity",
			"target_qty",
			"priority",
			"status",
			"instructions",
			"reference_doctype",
			"reference_name",
			"for_date",
			"schedule",
		],
		order_by="priority desc, for_date asc, creation asc",
	)


@frappe.whitelist()
def start_queue_item(queue_item: str, target_minutes: int | None = None):
	"""Start one specific queued task the employee picked."""
	employee = _get_employee_for_user()
	item = frappe.get_doc("Employee Work Queue", queue_item)
	if item.employee != employee and not _has_manager_role():
		frappe.throw(_("This queue item belongs to another employee"), frappe.PermissionError)
	if item.status not in ("Pending", "Assigned"):
		frappe.throw(_("This queue item is already {0}").format(item.status))
	if not is_tracking_enabled(employee):
		frappe.throw(_("Work tracking is disabled for this user"))
	if get_active_session(employee):
		frappe.throw(_("Finish your current work before starting a queued task"))

	session = _create_session(
		employee,
		item.work_activity,
		target_qty=item.target_qty,
		minutes=target_minutes,
		reference_doctype=item.reference_doctype,
		reference_name=item.reference_name,
		description=(item.instructions or item.work_activity),
		queue_item=item.name,
	)
	frappe.db.set_value("Employee Work Queue", item.name, "status", "Assigned")
	return session.as_dict()


def _cancel_session(session, remarks=None):
	"""Close an open session without counting it as completed work (task
	released, reassigned, or its document was cancelled) and free the
	employee if this was their current work."""
	if session.status not in OPEN_SESSION_STATUSES:
		return False
	session.status = SESSION_CANCELLED
	session.actual_end_time = now_datetime()
	_apply_time_accounting(session)
	if remarks:
		session.notes = remarks
	session.save(ignore_permissions=True)
	current = frappe.db.get_value("Employee Current Status", {"employee": session.employee}, "current_session")
	if current == session.name:
		set_status(session.employee, STATUS_IDLE, None)
	return True


def _employee_zones(employee):
	if not frappe.db.has_column("Employee", "mm_zones"):
		return []
	raw = frappe.db.get_value("Employee", employee, "mm_zones") or ""
	return [z.strip() for z in raw.replace("\n", ",").split(",") if z.strip()]


@frappe.whitelist()
def claim_next_work(work_activity: str | None = None, park_current: int = 0):
	"""One tap for the worker: take the next task and start its timer.

	Own assigned (Pending) items come first; otherwise the best unassigned
	item in the shared pool (priority, then the employee's own zones, then
	oldest). If the employee is already working, that session is returned —
	one active work per employee. The pool row is locked while claiming so
	two workers can never get the same task. `work_activity` limits the
	search to one kind of work (e.g. the Pick List screen asks for Picking)."""
	employee = _get_employee_for_user()
	if not is_tracking_enabled(employee):
		frappe.throw(_("Work tracking is disabled for this user"))

	existing = get_active_session(employee)
	if existing and (not cint(park_current) or (work_activity and existing.work_activity == work_activity)):
		return {"claimed": False, "session": existing.as_dict(), **_reference_of(existing)}

	fields = ["name", "work_activity", "priority", "zone", "creation", "employee"]
	scope = {"work_activity": work_activity} if work_activity else {}
	zones = _employee_zones(employee)
	taken = []
	chosen = None
	for _attempt in range(5):
		skip = {"name": ["not in", taken]} if taken else {}
		mine = frappe.get_all(
			"Employee Work Queue",
			filters={"employee": employee, "status": "Pending", "reference_name": ["is", "set"], **scope, **skip},
			fields=fields,
		)
		candidate = timing.pick_next(mine)
		if not candidate:
			pool = frappe.get_all(
				"Employee Work Queue",
				filters={"status": "Pending", "employee": ["is", "not set"], "reference_name": ["is", "set"], **scope, **skip},
				fields=fields,
			)
			candidate = timing.pick_next(pool, zones)
		if not candidate:
			break
		# lock just this row and make sure nobody claimed it a moment ago
		locked = frappe.db.sql(
			"SELECT name FROM `tabEmployee Work Queue` WHERE name=%s AND status='Pending' FOR UPDATE",
			candidate["name"],
		)
		if locked:
			chosen = candidate
			break
		taken.append(candidate["name"])
	if not chosen:
		return {"claimed": False, "session": None, "empty": True}

	item = frappe.get_doc("Employee Work Queue", chosen["name"])
	if existing:
		# switching: set the running section aside so it can be resumed later
		from mm_employee_watcher.sections import park_session

		park_session(existing, _("Switched to {0}").format(item.reference_name or item.work_activity))
	session = _create_session(
		employee,
		item.work_activity,
		target_qty=item.target_qty,
		reference_doctype=item.reference_doctype,
		reference_name=item.reference_name,
		source_app="WMS",
		description=(item.instructions or item.work_activity),
		queue_item=item.name,
	)
	item.db_set({"employee": employee, "status": "Assigned", "assigned_at": now_datetime()})
	publish_pool_change()
	return {"claimed": True, "session": session.as_dict(), **_reference_of(session)}


def _reference_of(session):
	return {
		"reference_doctype": session.reference_doctype,
		"reference_name": session.reference_name,
		"queue_item": session.queue_item,
	}


def publish_pool_change():
	"""Tell dashboards the pool changed (claim / release / new task)."""
	frappe.publish_realtime(event="mm_employee_watcher:dashboard_update", message={"pool": True})


@frappe.whitelist()
def release_work(queue_item: str, reason: str | None = None):
	"""Put a claimed task back in the pool (worker can't do it, or a manager
	takes it away). The running timer is discarded, not counted as done."""
	item = frappe.get_doc("Employee Work Queue", queue_item)
	if item.employee != get_employee_for_user() and not _has_manager_role():
		frappe.throw(_("This queue item belongs to another employee"), frappe.PermissionError)
	if item.status != "Assigned":
		frappe.throw(_("Only claimed work can be released"))
	_release_item(item, reason)
	return {"ok": True}


def _release_item(item, reason=None):
	for name in frappe.get_all(
		"Employee Work Session",
		filters={"queue_item": item.name, "status": ["in", list(OPEN_SESSION_STATUSES)]},
		pluck="name",
	):
		_cancel_session(frappe.get_doc("Employee Work Session", name), reason)
	item.db_set({"employee": None, "status": "Pending", "assigned_at": None})
	publish_pool_change()


@frappe.whitelist()
def reassign_work(queue_item: str, employee: str):
	"""Manager moves a task to a specific employee's own queue."""
	if not _has_manager_role():
		frappe.throw(_("Only a watcher manager can reassign work"), frappe.PermissionError)
	if not frappe.db.exists("Employee", {"name": employee, "status": "Active"}):
		frappe.throw(_("Employee {0} is not active").format(employee))
	item = frappe.get_doc("Employee Work Queue", queue_item)
	if item.status not in ("Pending", "Assigned"):
		frappe.throw(_("This queue item is already {0}").format(item.status))
	if item.status == "Assigned":
		_release_item(item, _("Reassigned"))
	item.db_set({"employee": employee, "status": "Pending"})
	publish_pool_change()
	return {"ok": True}


@frappe.whitelist()
def get_reference_work(reference_doctype: str, reference_name: str):
	"""Task state and times for one document (Pick List, ...): used by the
	PWA/board to show who has it and its waiting/working time."""
	if not frappe.has_permission(reference_doctype, "read", doc=reference_name):
		frappe.throw(_("You do not have permission to use the referenced document"), frappe.PermissionError)
	item = frappe.get_all(
		"Employee Work Queue",
		filters={"reference_doctype": reference_doctype, "reference_name": reference_name},
		fields=["name", "work_activity", "employee", "status", "creation", "assigned_at"],
		order_by="creation desc",
		limit=1,
	)
	sessions = frappe.get_all(
		"Employee Work Session",
		filters={"reference_doctype": reference_doctype, "reference_name": reference_name},
		fields=[
			"name",
			"employee",
			"employee_name",
			"work_activity",
			"status",
			"start_time",
			"actual_end_time",
			"waiting_seconds",
			"working_seconds",
			"paused_seconds",
		],
		order_by="creation desc",
		limit=5,
	)
	return {"queue_item": item[0] if item else None, "sessions": sessions}


@frappe.whitelist()
def list_work_activities():
	"""Work Activity Master names for the mobile worker page's Start Work
	picker. Any logged-in user — no role assumptions, since the mobile page
	can't use a Desk Link field's own permission-aware lookup."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in"), frappe.PermissionError)
	return frappe.get_all("Work Activity Master", fields=["name"], order_by="name asc")


@frappe.whitelist()
def record_screen_view(reference_doctype: str, reference_name: str):
	"""Passive audit trail: the employee opened a saved document on Desk.

	Only writes an Employee Work Log row (tied to the current work session if
	one is open). It never creates or switches a work session — this is for
	the 'what did they actually touch today' view, not the work timer.
	"""
	employee = get_employee_for_user()
	if not employee or not is_tracking_enabled(employee):
		return {"tracking": False}
	if not frappe.db.exists(reference_doctype, reference_name):
		return {"ok": False}

	today_start = get_datetime(today())
	already = frappe.db.exists(
		"Employee Work Log",
		{
			"employee": employee,
			"event_type": "Screen Opened",
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"event_time": [">=", today_start],
		},
	)
	if already:
		return {"ok": True, "duplicate": True}

	work = get_active_session(employee)
	log_event(
		employee,
		work.name if work else None,
		"Screen Opened",
		remarks=_("Opened {0} {1}").format(reference_doctype, reference_name),
		source_app="ERPNext",
		reference_doctype=reference_doctype,
		reference_name=reference_name,
	)
	return {"ok": True}


def _record_heartbeat(employee):
	status = get_or_create_status(employee)
	status.db_set("last_heartbeat", now_datetime(), update_modified=False)
	if status.status != "OFFLINE":
		return status

	session = get_active_session(employee)
	if session and session.status == SESSION_BLOCKED:
		return set_status(employee, STATUS_BLOCKED, session.name)
	if session and session.status == SESSION_PAUSED:
		return set_status(employee, STATUS_IDLE, session.name)
	if session:
		return set_status(employee, STATUS_WORKING, session.name)
	return set_status(employee, STATUS_IDLE, None)


@frappe.whitelist()
def get_my_status(employee: str | None = None):
	"""What the Desk popup / floating work widget reads on load. Returns
	employee: None when this user has no linked Employee, or tracking: 0
	when tracking is off for them — the caller should stay silent then."""
	employee = _get_employee_for_user(employee) if employee else get_employee_for_user()
	if not employee:
		return {"employee": None}

	tracking = is_tracking_enabled(employee)
	if not tracking:
		return {"employee": employee, "tracking": False}
	status_doc = _record_heartbeat(employee)
	status = {
		"status": status_doc.status,
		"current_session": status_doc.current_session,
		"status_since": status_doc.status_since,
		"break_until": status_doc.break_until,
	}

	result = {
		"employee": employee,
		"employee_name": status_doc.employee_name or employee,
		"tracking": tracking,
		**status,
	}
	duty = duty_state(employee)
	result.update(
		{"on_duty": duty["on_duty"], "duty_reason": duty["reason"], "punched_in": duty["punched_in"], "shift": duty["shift"]}
	)
	if status["current_session"]:
		session = frappe.get_doc("Employee Work Session", status["current_session"])
		result["session"] = session.as_dict()
		result["expired"] = bool(
			session.status in {SESSION_ACTIVE, SESSION_EXTENDED}
			and session.target_end_time
			and get_datetime(session.target_end_time) < now_datetime()
		)
	return result


@frappe.whitelist()
def get_next_work(employee: str | None = None):
	"""Next Employee Work Queue item for this employee, by priority — used
	both by the 'next priority work' prompt and the Desk 'Work Now' popup."""
	employee = _get_employee_for_user(employee)
	items = frappe.get_all(
		"Employee Work Queue",
		filters={"employee": employee, "status": "Pending"},
		fields=[
			"name",
			"work_activity",
			"reference_doctype",
			"reference_name",
			"target_qty",
			"priority",
		],
		order_by="priority desc, creation asc",
		limit=1,
	)
	return items[0] if items else None


@frappe.whitelist()
def heartbeat(employee: str | None = None, active: int = 1):
	"""Called periodically by every connected client so the offline
	watchdog can tell a genuinely idle employee from a dropped connection."""
	employee = _get_employee_for_user(employee)
	if not is_tracking_enabled(employee):
		return {"ok": True, "tracking": False, "server_time": now_datetime()}
	if not cint(active):
		status = get_or_create_status(employee)
		status.db_set("last_heartbeat", now_datetime(), update_modified=False)
		session = get_active_session(employee)
		if status.status not in {STATUS_IDLE, STATUS_BREAK, "OFF DUTY"}:
			if session:
				_log_session_event(session, "Idle Start", remarks=_("No recent Desk activity"))
			set_status(employee, STATUS_IDLE, session.name if session else None)
	else:
		status = _record_heartbeat(employee)
		session = get_active_session(employee)
		if session and session.status in {SESSION_ACTIVE, SESSION_EXTENDED} and status.status != STATUS_WORKING:
			_log_session_event(session, "Idle End", remarks=_("Desk activity resumed"))
			set_status(employee, STATUS_WORKING, session.name)
	return {"ok": True, "tracking": True, "server_time": now_datetime()}


@frappe.whitelist()
def record_desktop_activity(
	work_activity: str,
	action: str,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	description: str | None = None,
):
	"""Passive audit trail for Desk navigation (Sales Invoice / Payment Entry
	/ report screens). This never creates, switches, or completes a work
	session — only the employee's own explicit Start Work / End Work does
	that. It just writes one Employee Work Log row, attached to whatever
	session (if any) is currently open, so clicking around Desk can't spawn
	a flood of auto-completed sessions."""
	if action not in ALLOWED_DESKTOP_EVENTS:
		frappe.throw(_("Unsupported desktop activity event"))
	# Fires from passive Desk navigation for every logged-in user, tracked or
	# not — it must never throw for someone with no linked Employee or with
	# tracking off, or every route change pops an error.
	employee = get_employee_for_user()
	if not employee or not is_tracking_enabled(employee):
		return {"tracking": False}

	if reference_doctype and reference_name and action in {"Document Created", "Document Submitted"}:
		duplicate = frappe.db.exists(
			"Employee Work Log",
			{
				"employee": employee,
				"event_type": action,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
			},
		)
		if duplicate:
			return {"tracking": True, "duplicate": True}

	work = get_active_session(employee)
	matching = work if (work and work.work_activity == work_activity) else None

	if matching and action == "Document Submitted":
		matching.completed_qty = flt(matching.completed_qty) + 1
		matching.save(ignore_permissions=True)

	log_event(
		employee,
		matching.name if matching else None,
		action,
		qty=matching.completed_qty if (matching and action == "Document Submitted") else None,
		remarks=description,
		source_app="ERPNext",
		reference_doctype=reference_doctype if reference_name else None,
		reference_name=reference_name,
	)
	return {
		"tracking": True,
		"work_session": matching.name if matching else None,
		"completed_qty": matching.completed_qty if matching else None,
	}


def record_document_activity(doc, method=None):
	"""Non-blocking ERPNext document hook for supported business documents."""
	work_activity = DESKTOP_ACTIVITY_MAP.get(doc.doctype)
	if not work_activity or frappe.session.user == "Guest":
		return
	action = "Document Submitted" if method == "on_submit" else "Document Created"
	try:
		record_desktop_activity(
			work_activity=work_activity,
			action=action,
			reference_doctype=doc.doctype,
			reference_name=doc.name,
			description=_("{0} {1}").format(action, doc.name),
		)
	except Exception:
		# Tracking must never block a valid invoice or payment transaction.
		frappe.log_error(
			title="MM Employee Watcher document tracking failed",
			message=frappe.get_traceback(),
		)


@frappe.whitelist()
def get_my_dashboard(days: int = 7):
	"""The logged-in employee's own work numbers, assigned work and tips for
	the PWA "My Work" screen. Only their own data is ever returned. Logins
	without an Employee, or with work tracking off, get {"tracking": False}
	so the PWA can show a plain message instead of an error."""
	employee = get_employee_for_user()
	if not employee:
		return {"tracking": False, "reason": "no_employee"}
	if not is_tracking_enabled(employee):
		return {"tracking": False, "reason": "disabled", "employee": employee, "attendance": _attendance_summary(employee)}
	days = min(max(cint(days) or 7, 1), 31)
	now = now_datetime()
	today_start = get_datetime(today())
	period_start = add_to_date(today_start, days=-(days - 1))

	sessions = frappe.get_all(
		"Employee Work Session",
		filters={"employee": employee, "start_time": [">=", period_start]},
		fields=[
			"name", "work_activity", "status", "start_time", "actual_end_time", "target_end_time",
			"working_seconds", "paused_seconds", "waiting_seconds", "completed_qty", "reference_name",
		],
		order_by="start_time desc",
		limit=500,
	)
	done = [s for s in sessions if s.status == SESSION_COMPLETED]
	today_done = [s for s in done if get_datetime(s.start_time) >= today_start]

	def total(rows, key):
		return sum(cint(r.get(key)) for r in rows)

	timed = [s for s in done if s.actual_end_time and s.target_end_time]
	on_time_pct = None
	if len(timed) >= 3:
		on_time = sum(1 for s in timed if get_datetime(s.actual_end_time) <= get_datetime(s.target_end_time))
		on_time_pct = round(100.0 * on_time / len(timed), 1)

	by_day = {}
	for offset in range(days):
		day = getdate(add_to_date(period_start, days=offset))
		by_day[str(day)] = {"date": str(day), "sessions": 0, "working_min": 0}
	for s in done:
		key = str(getdate(s.start_time))
		if key in by_day:
			by_day[key]["sessions"] += 1
			by_day[key]["working_min"] += round(cint(s.working_seconds) / 60)

	by_activity = {}
	for s in done:
		row = by_activity.setdefault(s.work_activity, {"activity": s.work_activity, "sessions": 0, "working_min": 0, "waiting_min": 0})
		row["sessions"] += 1
		row["working_min"] += round(cint(s.working_seconds) / 60)
		row["waiting_min"] += round(cint(s.waiting_seconds) / 60)
	activities = sorted(by_activity.values(), key=lambda r: -r["working_min"])
	for row in activities:
		row["avg_min"] = round(row["working_min"] / row["sessions"], 1) if row["sessions"] else 0

	status_row = frappe.db.get_value(
		"Employee Current Status",
		{"employee": employee},
		["status", "status_since", "idle_since"],
		as_dict=True,
	) or {}
	idle_minutes = 0
	if status_row.get("status") == STATUS_IDLE:
		since = status_row.get("idle_since") or status_row.get("status_since")
		if since:
			idle_minutes = max(0, int(time_diff_in_seconds(now, get_datetime(since)) // 60))

	from mm_employee_watcher.sections import parked_sessions

	assigned = get_my_queue(employee)
	pool_count = len(
		frappe.get_all(
			"Employee Work Queue",
			filters={"status": "Pending", "employee": ["is", "not set"]},
			pluck="name",
			limit=200,
		)
	)

	working_total = round(total(done, "working_seconds") / 60)
	stats = {
		"status": status_row.get("status"),
		"idle_minutes": idle_minutes,
		"assigned_count": len(assigned),
		"top_assigned": assigned[0]["work_activity"] if assigned else None,
		"pool_count": pool_count,
		"today_sessions": len(today_done),
		"today_working_min": round(total(today_done, "working_seconds") / 60),
		"today_paused_min": round(total(today_done, "paused_seconds") / 60),
		"period_sessions": len(done),
		"on_time_pct": on_time_pct,
		"avg_working_min": round(working_total / len(done), 1) if done else 0,
	}
	return {
		"tracking": True,
		"attendance": _attendance_summary(employee),
		"parked": parked_sessions(employee),
		"employee": employee,
		"days": days,
		"today": {
			"sessions": stats["today_sessions"],
			"working_min": stats["today_working_min"],
			"paused_min": stats["today_paused_min"],
		},
		"period": {
			"sessions": len(done),
			"working_min": working_total,
			"paused_min": round(total(done, "paused_seconds") / 60),
			"avg_working_min": stats["avg_working_min"],
			"avg_waiting_min": round(total(done, "waiting_seconds") / 60 / len(done), 1) if done else 0,
			"on_time_pct": on_time_pct,
		},
		"by_day": list(by_day.values()),
		"by_activity": activities[:8],
		"assigned": assigned,
		"pool_count": pool_count,
		"idle_minutes": idle_minutes,
		"status": status_row.get("status"),
		"suggestions": timing.build_suggestions(stats),
		"recent": [
			{"activity": s.work_activity, "reference": s.reference_name, "end": s.actual_end_time, "working_min": round(cint(s.working_seconds) / 60)}
			for s in done[:8]
		],
	}


# ---------------------------------------------------------------------------
# Attendance: Punch In / Punch Out with the phone's location
# ---------------------------------------------------------------------------


def _attendance_settings():
	cfg = frappe.db.get_singles_dict("MM Watcher Settings") or {}
	return {
		"needs_location": cint(cfg.get("punch_requires_location", 1)),
		"geofence": cint(cfg.get("geofence_enabled", 0))
		and flt(cfg.get("geofence_latitude")) != 0
		and flt(cfg.get("geofence_longitude")) != 0,
		"block": cint(cfg.get("geofence_block", 0)),
		"lat": flt(cfg.get("geofence_latitude")),
		"lng": flt(cfg.get("geofence_longitude")),
		"radius": cint(cfg.get("geofence_radius_m", 200)) or 200,
	}


def _attendance_summary(employee):
	duty = duty_state(employee)
	cfg = _attendance_settings()
	since = add_to_date(get_datetime(today()), days=-1)
	punches = frappe.get_all(
		"Employee Punch",
		filters={"employee": employee, "punch_time": [">=", since]},
		fields=["log_type", "punch_time", "within_geofence", "distance_m"],
		order_by="punch_time asc",
		limit=20,
	)
	shift = get_work_shift(employee)
	return {
		"punched_in": duty["punched_in"],
		"on_duty": duty["on_duty"],
		"reason": duty["reason"],
		"shift": (
			{
				"name": shift.name,
				"start": str(shift.start_time),
				"end": str(shift.end_time),
				"weekly_off": shift.weekly_off or "",
			}
			if shift
			else None
		),
		"needs_location": bool(cfg["needs_location"]),
		"geofence": bool(cfg["geofence"]),
		"punches": [
			{
				"log_type": p.log_type,
				"time": str(p.punch_time),
				"inside": cint(p.within_geofence),
				"distance_m": round(flt(p.distance_m)) if p.distance_m else None,
			}
			for p in punches
		],
	}


@frappe.whitelist()
def get_punch_status():
	"""Shift, punch state and today's punches for the logged-in employee."""
	employee = get_employee_for_user()
	if not employee:
		return {"employee": None}
	return {"employee": employee, **_attendance_summary(employee)}


@frappe.whitelist(methods=["POST"])
def punch(
	log_type: str,
	latitude: float | None = None,
	longitude: float | None = None,
	accuracy: float | None = None,
	note: str | None = None,
	device: str | None = None,
):
	"""Punch In or Out from the phone. The location (from the browser's GPS)
	is stored with the punch; if an office point is set in MM Watcher
	Settings the punch is marked Inside / Outside and can be refused."""
	employee = _get_employee_for_user()
	log_type = (log_type or "").upper()
	if log_type not in ("IN", "OUT"):
		frappe.throw(_("Punch type must be IN or OUT"))
	cfg = _attendance_settings()
	lat = flt(latitude) if latitude not in (None, "") else None
	lng = flt(longitude) if longitude not in (None, "") else None
	if cfg["needs_location"] and (lat is None or lng is None):
		frappe.throw(_("Punch ke liye location zaroori hai. Phone mein location allow karke dobara try karein."))

	duty = duty_state(employee)
	if log_type == "IN" and duty["punched_in"]:
		frappe.throw(_("Aap pehle se Punch In hain"))
	if log_type == "OUT" and not duty["punched_in"]:
		frappe.throw(_("Aap abhi Punch In nahi hain"))

	distance = None
	inside = 0
	if cfg["geofence"] and lat is not None and lng is not None:
		distance = timing.haversine_m(lat, lng, cfg["lat"], cfg["lng"])
		inside = 1 if distance <= cfg["radius"] else 0
		if log_type == "IN" and cfg["block"] and not inside:
			frappe.throw(
				_("Aap allowed jagah se {0} m door hain. Office ke paas jakar Punch In karein.").format(round(distance))
			)

	if log_type == "OUT":
		current = get_active_session(employee)
		if current and current.status in (SESSION_ACTIVE, SESSION_EXTENDED, SESSION_BLOCKED):
			frappe.throw(
				_("Pehle apna chalta kaam ({0}) khatam ya pause karein, phir Punch Out karein").format(
					current.work_activity
				)
			)

	doc = frappe.get_doc(
		{
			"doctype": "Employee Punch",
			"employee": employee,
			"log_type": log_type,
			"punch_time": now_datetime(),
			"shift": duty["shift"],
			"source": "PWA",
			"device": (device or "")[:300],
			"latitude": lat,
			"longitude": lng,
			"accuracy_m": flt(accuracy) if accuracy not in (None, "") else None,
			"distance_m": round(distance, 1) if distance is not None else None,
			"within_geofence": inside,
			"note": note,
		}
	).insert(ignore_permissions=True)

	_mirror_to_hrms_checkin(doc)
	if is_tracking_enabled(employee):
		if log_type == "IN":
			status_doc = get_or_create_status(employee)
			if status_doc.status in ("OFFLINE", STATUS_OFF_DUTY):
				set_status(employee, STATUS_IDLE, None)
		else:
			set_status(employee, STATUS_OFF_DUTY, None)
	return {
		"ok": True,
		"log_type": log_type,
		"inside": bool(inside) if cfg["geofence"] else None,
		"distance_m": round(distance) if distance is not None else None,
		**_attendance_summary(employee),
	}


def _mirror_to_hrms_checkin(punch_doc):
	"""If HRMS is installed, also create its Employee Checkin so its attendance
	tools see the punch. Best effort: never fails the punch."""
	if not frappe.db.exists("DocType", "Employee Checkin"):
		return
	try:
		values = {
			"doctype": "Employee Checkin",
			"employee": punch_doc.employee,
			"log_type": punch_doc.log_type,
			"time": punch_doc.punch_time,
			"device_id": "MM Staff PWA",
		}
		meta = frappe.get_meta("Employee Checkin")
		if meta.has_field("latitude") and punch_doc.latitude is not None:
			values["latitude"] = punch_doc.latitude
			values["longitude"] = punch_doc.longitude
		frappe.get_doc(values).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="MM Employee Watcher HRMS checkin mirror failed", message=frappe.get_traceback())
