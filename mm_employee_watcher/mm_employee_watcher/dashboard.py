"""Data for the wall-display Supervisor Dashboard (www/mm_dashboard.html).

One whitelisted call the page's JS re-fetches every 30 seconds — see
docs/backend-architecture.md section 6.
"""

import frappe
from frappe import _
from frappe.utils import get_datetime, getdate, now_datetime, time_diff_in_seconds, today

from mm_employee_watcher.utils import is_tracking_enabled, pair_state_durations

ONGOING = ("Active", "Extended", "Paused", "Blocked")

# WORKING/BLOCKED employees are the ones a supervisor most needs to see
# first — blocked (needs help right now) even before working.
STATUS_ORDER = {"BLOCKED": 0, "WORKING": 1, "BREAK": 2, "IDLE": 3, "OFFLINE": 4, "OFF DUTY": 5}
DASHBOARD_ROLES = {"System Manager", "HR Manager", "Employee Watcher Manager", "Employee Watcher Viewer"}


MANAGE_ROLES = {"System Manager", "HR Manager", "Employee Watcher Manager"}


def _check_dashboard_permission():
	if not DASHBOARD_ROLES.intersection(frappe.get_roles()):
		frappe.throw(_("You do not have permission to view the employee dashboard"), frappe.PermissionError)


def _check_manage_permission():
	if not MANAGE_ROLES.intersection(frappe.get_roles()):
		frappe.throw(_("You do not have permission to manage the work queue"), frappe.PermissionError)


@frappe.whitelist()
def get_queue_form_data():
	"""Employee + activity lists for the dashboard's 'Add to queue' form."""
	_check_manage_permission()
	return {
		"employees": frappe.get_all(
			"Employee",
			filters={"status": "Active"},
			fields=["name", "employee_name", "department"],
			order_by="employee_name asc",
		),
		"activities": frappe.get_all(
			"Work Activity Master", fields=["name"], order_by="name asc"
		),
	}


@frappe.whitelist()
def add_queue_item(
	employee: str,
	work_activity: str,
	instructions: str | None = None,
	target_qty: float | None = None,
	priority: int | None = None,
	for_date: str | None = None,
):
	"""Add one pending task to an employee's work queue from the dashboard.
	It stays Pending until the employee starts it — nothing auto-starts."""
	_check_manage_permission()
	if not frappe.db.exists("Employee", {"name": employee, "status": "Active"}):
		frappe.throw(_("{0} is not an active employee").format(employee))
	if not frappe.db.exists("Work Activity Master", work_activity):
		frappe.throw(_("Unknown work activity {0}").format(work_activity))

	doc = frappe.get_doc(
		{
			"doctype": "Employee Work Queue",
			"employee": employee,
			"work_activity": work_activity,
			"instructions": instructions,
			"target_qty": frappe.utils.flt(target_qty) or None,
			"priority": frappe.utils.cint(priority),
			"for_date": for_date or frappe.utils.today(),
			"status": "Pending",
		}
	)
	doc.insert(ignore_permissions=True)
	# Nudge only an idle employee's widget to refresh its queue list; never
	# interrupt someone who is already working.
	current = frappe.db.get_value("Employee Current Status", {"employee": employee}, "status")
	user = frappe.db.get_value("Employee", employee, "user_id")
	if user and current in (None, "IDLE", "OFFLINE"):
		frappe.publish_realtime(
			event="mm_employee_watcher:status_update", message={"employee": employee}, user=user
		)
	return {"ok": True, "name": doc.name}


@frappe.whitelist()
def get_dashboard_data():
	_check_dashboard_permission()

	rows = frappe.get_all(
		"Employee Current Status",
		fields=[
			"employee",
			"employee_name",
			"status",
			"status_since",
			"current_session",
		],
	)

	now = now_datetime()

	# Today's Work Log event counts per employee, in one grouped query.
	counts_by_employee = {}
	for log in frappe.db.sql(
		"""
		select employee, event_type, count(name) as event_count
		from `tabEmployee Work Log`
		where event_time >= %s
		group by employee, event_type
		""",
		(f"{today()} 00:00:00",),
		as_dict=True,
	):
		counts_by_employee.setdefault(log.employee, {})[log.event_type] = log.event_count

	cards = []
	for row in rows:
		if not is_tracking_enabled(row.employee):
			continue
		card = {
			"employee": row.employee,
			"employee_name": row.employee_name or row.employee,
			"status": row.status,
			"since_minutes": (
				max(0, int(time_diff_in_seconds(now, row.status_since) // 60)) if row.status_since else None
			),
		}

		if row.current_session:
			session = frappe.db.get_value(
				"Employee Work Session",
				row.current_session,
				[
					"work_activity",
					"target_qty",
					"completed_qty",
					"target_end_time",
					"status",
					"extended_minutes",
					"blocked_reason",
					"source_app",
					"reference_doctype",
					"reference_name",
					"notes",
				],
				as_dict=True,
			)
			if session:
				card["work_activity"] = session.work_activity
				card["description"] = session.notes
				card["target_qty"] = session.target_qty
				card["completed_qty"] = session.completed_qty
				card["session_status"] = session.status
				card["extended_minutes"] = session.extended_minutes
				card["blocked_reason"] = session.blocked_reason
				card["source_app"] = session.source_app
				card["reference_doctype"] = session.reference_doctype
				card["reference_name"] = session.reference_name
				card["start_time"] = str(session.start_time) if session.start_time else None
				card["target_end_time"] = (
					str(session.target_end_time) if session.target_end_time else None
				)
				if session.target_end_time:
					card["remaining_minutes"] = int(
						time_diff_in_seconds(session.target_end_time, now) // 60
					)

		card["today_counts"] = counts_by_employee.get(row.employee, {})
		cards.append(card)

	# Pending queue count per employee.
	queue_by_employee = {}
	for q in frappe.db.sql(
		"""
		select employee, count(name) as n
		from `tabEmployee Work Queue`
		where status in ('Pending', 'Assigned')
		group by employee
		""",
		as_dict=True,
	):
		queue_by_employee[q.employee] = q.n
	for c in cards:
		c["queue_pending"] = queue_by_employee.get(c["employee"], 0)

	# Open supervisor alerts, per employee.
	alerts_by_employee = {}
	for a in frappe.get_all(
		"Employee Watcher Alert",
		filters={"status": "Open"},
		fields=["employee", "alert_type", "reason"],
	):
		alerts_by_employee.setdefault(a.employee, []).append(
			{"type": a.alert_type, "reason": a.reason}
		)
	for c in cards:
		c["open_alerts"] = alerts_by_employee.get(c["employee"], [])

	cards.sort(key=lambda c: (STATUS_ORDER.get(c["status"], 9), c["employee_name"]))

	counts = {}
	for c in cards:
		counts[c["status"]] = counts.get(c["status"], 0) + 1

	return {
		"generated_at": now,
		"cards": cards,
		"counts": counts,
		"open_alert_count": sum(len(v) for v in alerts_by_employee.values()),
	}


@frappe.whitelist()
def get_dashboard_history(day: str):
	"""Per-employee totals for a past day — worked / idle / break / blocked
	minutes, session count and qty done — so the wall dashboard can be
	back-dated. Cards link to the same drill-down for that day."""
	_check_dashboard_permission()
	day = getdate(day)
	start = f"{day} 00:00:00"
	end = f"{day} 23:59:59"
	cap = min(now_datetime(), get_datetime(end))

	sessions = frappe.get_all(
		"Employee Work Session",
		filters={"start_time": ["between", [start, end]]},
		fields=["employee", "employee_name", "status", "start_time", "actual_end_time", "completed_qty"],
	)
	logs = frappe.get_all(
		"Employee Work Log",
		filters={"event_time": ["between", [start, end]]},
		fields=["employee", "event_type", "event_time"],
		order_by="event_time asc",
	)

	names = {}
	agg = {}
	for s in sessions:
		names.setdefault(s.employee, s.employee_name or s.employee)
		a = agg.setdefault(s.employee, {"worked": 0.0, "idle": 0.0, "brk": 0.0, "blocked": 0.0, "sessions": 0, "qty": 0.0})
		a["sessions"] += 1
		a["qty"] += float(s.completed_qty or 0)
		finish = s.actual_end_time or (cap if s.status in ONGOING else None)
		if s.start_time and finish:
			a["worked"] += max(0, time_diff_in_seconds(finish, s.start_time))

	logs_by_emp = {}
	for row in logs:
		logs_by_emp.setdefault(row.employee, []).append(row)
	for emp, elogs in logs_by_emp.items():
		names.setdefault(emp, frappe.db.get_value("Employee", emp, "employee_name") or emp)
		a = agg.setdefault(emp, {"worked": 0.0, "idle": 0.0, "brk": 0.0, "blocked": 0.0, "sessions": 0, "qty": 0.0})
		d = pair_state_durations(elogs, cap)
		a["idle"] += d["idle"]
		a["brk"] += d["break"]
		a["blocked"] += d["blocked"]

	cards = []
	for emp, a in agg.items():
		if not is_tracking_enabled(emp):
			continue
		cards.append(
			{
				"employee": emp,
				"employee_name": names.get(emp, emp),
				"worked_minutes": int(a["worked"] // 60),
				"idle_minutes": int(a["idle"] // 60),
				"break_minutes": int(a["brk"] // 60),
				"blocked_minutes": int(a["blocked"] // 60),
				"sessions": a["sessions"],
				"qty": a["qty"],
			}
		)
	cards.sort(key=lambda c: -c["worked_minutes"])
	return {"day": str(day), "cards": cards}


@frappe.whitelist()
def get_employee_detail(employee: str, day: str | None = None):
	"""Everything one employee did on `day` (default: today) — every work
	session and every logged event — for the dashboard drill-down."""
	_check_dashboard_permission()

	day = day or today()
	start = f"{day} 00:00:00"
	end = f"{day} 23:59:59"
	now = now_datetime()

	status = frappe.db.get_value(
		"Employee Current Status",
		{"employee": employee},
		["employee_name", "status", "status_since", "current_session"],
		as_dict=True,
	) or {}

	ongoing_states = ("Active", "Extended", "Paused", "Blocked")
	sessions = frappe.get_all(
		"Employee Work Session",
		filters={"employee": employee, "start_time": ["between", [start, end]]},
		fields=[
			"name",
			"work_activity",
			"notes",
			"status",
			"start_time",
			"actual_end_time",
			"target_end_time",
			"target_qty",
			"completed_qty",
			"extended_minutes",
			"source_app",
			"reference_doctype",
			"reference_name",
		],
		order_by="start_time asc",
	)

	worked_seconds = 0
	for s in sessions:
		s["description"] = s.pop("notes", None)
		s["ongoing"] = s.status in ongoing_states
		finished = s.actual_end_time or (now if s["ongoing"] else None)
		if s.start_time and finished:
			secs = max(0, time_diff_in_seconds(finished, s.start_time))
			s["minutes"] = int(secs // 60)
			worked_seconds += secs
		else:
			s["minutes"] = None

	logs = frappe.get_all(
		"Employee Work Log",
		filters={"employee": employee, "event_time": ["between", [start, end]]},
		fields=[
			"event_type",
			"event_time",
			"work_session",
			"source_app",
			"reference_doctype",
			"reference_name",
			"qty",
			"remarks",
		],
		order_by="event_time desc",
		limit=400,
	)

	# --- Blocked / Idle / Break analysis for the day (single pass) ---
	cap = min(now, get_datetime(end))
	d = pair_state_durations(sorted(logs, key=lambda x: x.event_time), cap)
	idle_minutes = int(d["idle"] // 60)
	break_minutes = int(d["break"] // 60)
	blocked_minutes = int(d["blocked"] // 60)
	blocked_reasons = {r: int(s // 60) for r, s in d["blocked_reasons"].items() if s >= 60}

	alerts = frappe.get_all(
		"Employee Watcher Alert",
		filters={"employee": employee, "raised_at": ["between", [start, end]]},
		fields=["alert_type", "status", "raised_at", "cleared_at", "open_minutes", "reason"],
		order_by="raised_at desc",
	)

	return {
		"employee": employee,
		"employee_name": status.get("employee_name") or employee,
		"status": status.get("status"),
		"status_since": status.get("status_since"),
		"day": day,
		"worked_minutes": int(worked_seconds // 60),
		"session_count": len(sessions),
		"sessions": sessions,
		"logs": logs,
		"alerts": alerts,
		"blocked_minutes": blocked_minutes,
		"idle_minutes": idle_minutes,
		"break_minutes": break_minutes,
		"blocked_reasons": [
			{"reason": k, "minutes": v}
			for k, v in sorted(blocked_reasons.items(), key=lambda kv: -kv[1])
		],
	}
