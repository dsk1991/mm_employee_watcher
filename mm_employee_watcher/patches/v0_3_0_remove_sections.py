"""0.3.0 - drop the Work Section subsystem.

Sections (Work Section Master / Employee Section Session / Employee Section
Schedule) are gone: the watcher now tracks a single flat work session per
employee. This patch removes the three DocTypes, their tables, the now-orphan
section columns on the surviving tables, and the retired scheduler jobs.

Every step is best-effort and idempotent: a migrate must never fail because
some leftover was already cleaned up (or never existed). Section history is
not migrated anywhere - it is dropped.
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

RETIRED_JOBS = (
	"mm_employee_watcher.tasks.check_expired_sections",
	"mm_employee_watcher.tasks.notify_due_section_schedules",
)


def _safe(label, fn):
	try:
		fn()
	except Exception as exc:
		# Never fail the migrate over leftover cleanup - the app code no longer
		# references sections at all. Surface it in the console and Error Log.
		print(f"  v0_3_0_remove_sections: skipped '{label}' ({exc.__class__.__name__}: {exc})")
		frappe.log_error(title=f"v0_3_0_remove_sections: {label}", message=frappe.get_traceback())


def execute():
	# 1. Drop orphan section columns from the surviving tables.
	for doctype, columns in ORPHAN_COLUMNS.items():
		table = f"tab{doctype}"
		if not frappe.db.exists("DocType", doctype):
			continue
		for column in columns:
			def drop(table=table, column=column, doctype=doctype):
				if frappe.db.has_column(doctype, column):
					frappe.db.sql_ddl(f"ALTER TABLE `{table}` DROP COLUMN `{column}`")
			_safe(f"drop {table}.{column}", drop)

	# 2. Remove the section DocTypes and their tables.
	for doctype in SECTION_DOCTYPES:
		def remove(doctype=doctype):
			if frappe.db.exists("DocType", doctype):
				frappe.delete_doc("DocType", doctype, force=True, ignore_missing=True)
			frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{doctype}`")
		_safe(f"delete doctype {doctype}", remove)

	# 3. Clean up metadata other apps / earlier installs may have hung off them.
	_safe("delete Custom Field", lambda: frappe.db.delete("Custom Field", {"dt": ("in", SECTION_DOCTYPES)}))
	_safe("delete Property Setter", lambda: frappe.db.delete("Property Setter", {"doc_type": ("in", SECTION_DOCTYPES)}))
	_safe("delete DocField", lambda: frappe.db.delete("DocField", {"parent": ("in", SECTION_DOCTYPES)}))

	# 4. Retire the section scheduler jobs.
	_safe(
		"delete Scheduled Job Type",
		lambda: frappe.db.delete("Scheduled Job Type", {"method": ("in", RETIRED_JOBS)}),
	)

	frappe.clear_cache()
