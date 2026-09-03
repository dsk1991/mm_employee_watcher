"""0.3.0 — drop the Work Section subsystem.

Sections (Work Section Master / Employee Section Session / Employee Section
Schedule) are gone: the watcher now tracks a single flat work session per
employee. This patch removes the three DocTypes, their tables, and the
now-orphan section columns on the surviving tables. Section history is not
migrated anywhere — it is dropped.
"""

import frappe

SECTION_DOCTYPES = (
	"Employee Section Schedule",
	"Employee Section Session",
	"Work Section Master",
)

# table -> columns that used to point at a section
ORPHAN_COLUMNS = {
	"Employee Work Session": ("work_section", "section_session"),
	"Employee Work Log": ("work_section", "section_session"),
	"Employee Work Queue": ("work_section",),
	"Employee Current Status": ("current_section", "current_section_session"),
	"Work Activity Master": ("work_section",),
}


def execute():
	for doctype, columns in ORPHAN_COLUMNS.items():
		table = f"tab{doctype}"
		if not frappe.db.table_exists(table):
			continue
		for column in columns:
			if frappe.db.has_column(doctype, column):
				frappe.db.sql_ddl(f"ALTER TABLE `{table}` DROP COLUMN `{column}`")

	for doctype in SECTION_DOCTYPES:
		if frappe.db.exists("DocType", doctype):
			frappe.delete_doc("DocType", doctype, force=True, ignore_missing=True)
		frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{doctype}`")

	# Property Setters / Custom Fields that other apps may have hung off the
	# removed doctypes would now be dangling — clear the obvious ones.
	frappe.db.delete("Custom Field", {"dt": ("in", SECTION_DOCTYPES)})
	frappe.db.delete("Property Setter", {"doc_type": ("in", SECTION_DOCTYPES)})

	frappe.clear_cache()
