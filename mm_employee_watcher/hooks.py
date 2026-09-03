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
# Adds the per-user "Enable Work Tracking" checkbox on the User doctype
# (requirement #4) — a Custom Field, not a core field, so it survives
# framework upgrades.

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
}

# Scheduled tasks
# ---------------

scheduler_events = {
	"cron": {
		# every minute: notify once for sessions whose target_end_time has passed
		"* * * * *": [
			"mm_employee_watcher.tasks.check_expired_sessions",
		],
		# every 5 minutes: mark employees with a stale heartbeat as OFFLINE
		"*/5 * * * *": [
			"mm_employee_watcher.tasks.check_offline_employees",
		],
	},
}

# Fixtures
# --------
# fixtures = ["Work Activity Master"]
