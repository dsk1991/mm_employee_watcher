app_name = "mm_employee_watcher"
app_title = "MM Employee Watcher"
app_publisher = "Modern Marwar"
app_description = "Smart Employee Work Watcher — real-time employee work state across ERPNext, WMS and mobile apps"
app_email = "dileepsinghkheechee@gmail.com"
app_license = "MIT"

# Employee is provided by ERPNext. HRMS remains optional until attendance
# gating/reporting is enabled in a future release.
required_apps = ["frappe", "erpnext"]

# Includes in <head>
# ------------------
# Loads on every Desk page: a small WhatsApp-style floating work widget
# (bottom-right) with a live timer, a forced "Work Now" popup when the
# logged-in employee has no active session, an "End Work — what did you
# do?" prompt, and the Done/Extend/Blocked popup when their session's
# target time expires. See public/js/mm_employee_watcher.bundle.js.

app_include_js = "mm_employee_watcher.bundle.js"

# Install
# -------
# Adds the opt-in per-user "Enable Work Tracking" checkbox on the User
# doctype — a Custom Field, not a core field, so it survives framework
# upgrades. Tracking is OFF until this is ticked.

before_install = "mm_employee_watcher.install.before_install"
before_migrate = "mm_employee_watcher.install.before_migrate"
after_install = "mm_employee_watcher.install.after_install"
after_migrate = "mm_employee_watcher.install.after_migrate"

# Doc events
# ----------
# These events add document output to the employee's current work session. They
# are deliberately non-blocking: watcher failures never stop an accounting
# document from saving or submitting.

doc_events = {
	"Sales Invoice": {
		"after_insert": "mm_employee_watcher.api.record_document_activity",
		"on_submit": "mm_employee_watcher.api.record_document_activity",
	},
	"Payment Entry": {
		"after_insert": "mm_employee_watcher.api.record_document_activity",
		"on_submit": "mm_employee_watcher.api.record_document_activity",
	},
	# Warehouse work queue: which of these events create / complete / cancel
	# work is configured per Work Activity Master and switched on in MM
	# Watcher Settings ("Enable WMS Auto Queue"). Delivery Note and Purchase
	# Receipt rows are added with the Delivery and Putaway slices.
	"Pick List": {
		"after_insert": "mm_employee_watcher.wms_events.handle_document_event",
		"on_submit": "mm_employee_watcher.wms_events.handle_document_event",
		"on_cancel": "mm_employee_watcher.wms_events.handle_document_event",
	},
}

# Deletion
# --------
# Employee Work Log / Employee Work Session record every document a staff
# member opens via a Dynamic Link (reference_doctype/reference_name), which
# can point at any doctype (Pick List, Sales Invoice, ...). Frappe's delete
# check treats Dynamic Link the same as Link, so a tracking row for a draft
# Pick List blocked deleting that Pick List — and reopening it afterwards
# just recreated a fresh tracking row, recreating the same block. These are
# append-only activity logs, not relational data, so they are excluded from
# that check the same way core log doctypes (Comment, Version, ...) are.
ignore_links_on_delete = ["Employee Work Log", "Employee Work Session", "Employee Work Queue"]

# Scheduled tasks
# ---------------

scheduler_events = {
	"cron": {
		# every minute: session-expiry alerts, supervisor Idle/Overdue/Blocked
		# alerts, and break-overrun -> IDLE
		"* * * * *": [
			"mm_employee_watcher.tasks.check_expired_sessions",
			"mm_employee_watcher.tasks.raise_supervisor_alerts",
			"mm_employee_watcher.tasks.check_break_overrun",
		],
		# every 5 minutes: mark employees with a stale heartbeat as OFFLINE
		"*/5 * * * *": [
			"mm_employee_watcher.tasks.check_offline_employees",
		],
		# hourly: build queue items from due Work Queue Schedules (once/day each)
		"0 * * * *": [
			"mm_employee_watcher.tasks.build_scheduled_queues",
		],
		# nightly: purge old Work Log / cleared Alert / finished Queue rows
		"30 1 * * *": [
			"mm_employee_watcher.tasks.purge_old_records",
		],
	},
}

# Fixtures
# --------
# fixtures = ["Work Activity Master"]
