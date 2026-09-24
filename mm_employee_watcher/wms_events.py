"""Document events that feed the warehouse work queue.

Which document creates / completes / cancels which work is data, not code:
each Work Activity Master row names its Reference DocType and the events
(create_event / complete_event / cancel_event) plus an optional follow-up
activity. Nothing is stored on the ERPNext documents themselves.

Everything here is gated by MM Watcher Settings > "Enable WMS Auto Queue"
and is non-blocking: a tracker error is logged and never stops a Pick List,
Delivery Note or Purchase Receipt from saving or submitting.
"""

from collections import Counter

import frappe
from frappe import _

METHOD_EVENT = {
	"after_insert": "After Insert",
	"on_submit": "On Submit",
	"on_cancel": "On Cancel",
}


def enabled():
	return bool(frappe.db.get_single_value("MM Watcher Settings", "wms_auto_queue_enabled"))


def source_key(activity, doc):
	return f"{activity}|{doc.doctype}|{doc.name}"


def handle_document_event(doc, method=None):
	"""Single entry point registered in hooks.py for every WMS document."""
	if method not in METHOD_EVENT or frappe.flags.in_import or frappe.flags.in_migrate:
		return
	try:
		if not enabled():
			return
		for activity in _activities_for(doc.doctype):
			_apply(activity, doc, method)
	except Exception:
		frappe.log_error(title="MM Employee Watcher WMS event failed", message=frappe.get_traceback())


def _activities_for(doctype):
	return frappe.get_all(
		"Work Activity Master",
		filters={"is_document_linked": 1, "reference_doctype": doctype},
		fields=["name", "create_event", "complete_event", "cancel_event", "follow_up_activity", "zone_aware"],
	)


def _apply(activity, doc, method):
	event = METHOD_EVENT[method]
	if method in ("after_insert", "on_submit") and activity.create_event == event:
		queue_document(activity.name, doc, zone_aware=activity.zone_aware)
	if method == "on_submit" and activity.complete_event == event:
		complete_document(activity, doc)
	if method == "on_cancel" and activity.cancel_event == event:
		cancel_document(activity.name, doc)


def queue_document(activity, doc, zone_aware=False):
	"""Put the document in the pool as Pending work, once (source_key)."""
	key = source_key(activity, doc)
	if frappe.db.exists("Employee Work Queue", {"source_key": key}):
		return None
	item = frappe.get_doc(
		{
			"doctype": "Employee Work Queue",
			"work_activity": activity,
			"status": "Pending",
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"instructions": _("{0} {1}").format(_(doc.doctype), doc.name),
			"zone": zone_for(doc) if zone_aware else None,
			"source_key": key,
		}
	).insert(ignore_permissions=True)
	from mm_employee_watcher.api import publish_pool_change

	publish_pool_change()
	return item.name


def complete_document(activity, doc):
	"""The document finished: stop the running timer(s), close the queue
	item and queue the follow-up work (e.g. Picking -> Delivery)."""
	from mm_employee_watcher.api import OPEN_SESSION_STATUSES, _complete_session, publish_pool_change

	for name in frappe.get_all(
		"Employee Work Session",
		filters={
			"work_activity": activity.name,
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"status": ["in", list(OPEN_SESSION_STATUSES)],
		},
		pluck="name",
	):
		_complete_session(frappe.get_doc("Employee Work Session", name))

	# never worked in the tracker (or a plain item still waiting): just close it
	for name in frappe.get_all(
		"Employee Work Queue",
		filters={"source_key": source_key(activity.name, doc), "status": ["in", ["Pending", "Assigned"]]},
		pluck="name",
	):
		frappe.db.set_value("Employee Work Queue", name, "status", "Completed")
	if activity.follow_up_activity:
		follow = frappe.db.get_value(
			"Work Activity Master", activity.follow_up_activity, ["zone_aware"], as_dict=True
		)
		queue_document(activity.follow_up_activity, doc, zone_aware=bool(follow and follow.zone_aware))
	publish_pool_change()


def cancel_document(activity_name, doc):
	"""The document was cancelled: drop its open timers and pending work."""
	from mm_employee_watcher.api import OPEN_SESSION_STATUSES, _cancel_session, publish_pool_change

	for name in frappe.get_all(
		"Employee Work Session",
		filters={
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"status": ["in", list(OPEN_SESSION_STATUSES)],
		},
		pluck="name",
	):
		_cancel_session(frappe.get_doc("Employee Work Session", name), _("Document cancelled"))
	for name in frappe.get_all(
		"Employee Work Queue",
		filters={
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"status": ["in", ["Pending", "Assigned"]],
		},
		pluck="name",
	):
		frappe.db.set_value("Employee Work Queue", name, "status", "Cancelled", update_modified=True)
	publish_pool_change()


def zone_for(doc):
	"""Most common Warehouse Rack zone among the document's rows (Pick List:
	confirmed rack, else suggested rack). None when there is no rack data."""
	zones = Counter()
	try:
		for row in doc.get("locations") or []:
			rack = row.get("custom_confirmed_rack") or row.get("custom_suggested_rack")
			if not rack:
				continue
			zone = frappe.db.get_value("Warehouse Rack", rack, "zone")
			if zone:
				zones[zone] += 1
	except Exception:
		return None
	return zones.most_common(1)[0][0] if zones else None
