"""0.4.1 - Picking is not zone-wise for now.

Picking tasks are handed out by priority and age only. `zone_aware` stays
available on Work Activity Master to switch zone preference on later.
"""

import frappe


def execute():
	if frappe.db.exists("Work Activity Master", "Picking"):
		frappe.db.set_value("Work Activity Master", "Picking", "zone_aware", 0)
