"""0.4.0 - warehouse work queue: configure Picking (and add Delivery).

Picking is created from a Pick List, completed when it is submitted,
cancelled with it, and hands over to Delivery. Idempotent; only fills in
fields that are still empty so a site's own edits survive.
"""

import frappe

ACTIVITIES = {
	"Picking": {
		"default_duration_minutes": 60,
		"is_document_linked": 1,
		"requires_manual_done": 0,
		"reference_doctype": "Pick List",
		"create_event": "After Insert",
		"complete_event": "On Submit",
		"cancel_event": "On Cancel",
		"follow_up_activity": "Delivery",
		"zone_aware": 1,
	},
	"Delivery": {"default_duration_minutes": 30},
}


def execute():
	for name in ("Delivery", "Picking"):
		values = ACTIVITIES[name]
		if not frappe.db.exists("Work Activity Master", name):
			frappe.get_doc({"doctype": "Work Activity Master", "activity_name": name, **values}).insert(
				ignore_permissions=True
			)
			continue
		doc = frappe.get_doc("Work Activity Master", name)
		changed = False
		for field, value in values.items():
			if field in ("default_duration_minutes", "requires_manual_done"):
				continue
			if not doc.get(field):
				doc.set(field, value)
				changed = True
		if changed:
			doc.save(ignore_permissions=True)
