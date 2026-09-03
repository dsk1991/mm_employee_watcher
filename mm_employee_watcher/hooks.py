app_name = "mm_employee_watcher"
app_title = "MM Employee Watcher"
app_publisher = "Modern Marwar"
app_description = "Smart Employee Work Watcher — real-time employee work state across ERPNext, WMS and mobile apps"
app_email = "dileepsinghkheechee@gmail.com"
app_license = "MIT"

# Built for ERPNext v16 / Frappe Framework v16. Employee/User live in the
# "hrms" app (HR was split out of erpnext from v14 onward) — if your bench
# still keeps Employee inside "erpnext" instead, drop "hrms" below and add
# "erpnext" instead.
required_apps = ["frappe", "hrms"]

# Includes in <head>
# ------------------
# Loads on every Desk page: shows the "Work Now" popup when the logged-in
# employee has no active session, and the Done/Extend/Blocked popup when
# their session's target time expires. See public/js/mm_watcher.js.

app_include_js = "/assets/mm_employee_watcher/js/mm_watcher.js"

# Install
# -------
# Adds the per-user "Enable Work Tracking" checkbox on the User doctype
# (requirement #4) — a Custom Field, not a core field, so it survives
# framework upgrades.

after_install = "mm_employee_watcher.mm_employee_watcher.install.after_install"

# Doc events
# ----------
# Hook into other apps' documents here to auto-complete the matching
# Employee Work Session when the real operational document finishes
# (Packing Job / Pick List / Putaway / Job Card). Left empty in this
# foundation cut — see docs/backend-architecture.md section 4.
#
# doc_events = {
#     "Delivery Note": {
#         "on_submit": "mm_employee_watcher.mm_employee_watcher.integrations.wms.on_packing_complete",
#     },
# }

# Scheduled tasks
# ---------------

scheduler_events = {
	"cron": {
		# every minute: close sessions whose target_end_time has passed
		"* * * * *": [
			"mm_employee_watcher.mm_employee_watcher.tasks.check_expired_sessions",
		],
		# every 5 minutes: mark employees with a stale heartbeat as OFFLINE
		"*/5 * * * *": [
			"mm_employee_watcher.mm_employee_watcher.tasks.check_offline_employees",
		],
	},
}

# Fixtures
# --------
# fixtures = ["Work Activity Master"]
