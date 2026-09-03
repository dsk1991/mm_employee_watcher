app_name = "mm_employee_watcher"
app_title = "MM Employee Watcher"
app_publisher = "Modern Marwar"
app_description = "Smart Employee Work Watcher — real-time employee work state across ERPNext, WMS and mobile apps"
app_email = "dileepsinghkheechee@gmail.com"
app_license = "MIT"
required_apps = ["frappe"]

# Includes in <head>
# ------------------

# app_include_css = "/assets/mm_employee_watcher/css/mm_employee_watcher.css"
# app_include_js = "/assets/mm_employee_watcher/js/smart_work_bar.js"

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
