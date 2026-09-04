"""Public RPC entry point for the employee watcher dashboard.

The dashboard implementation lives in the app module package, while Frappe's
web page calls ``mm_employee_watcher.dashboard.get_dashboard_data``. Re-export
the whitelisted methods here so both the canonical and older nested paths work.
"""

from .mm_employee_watcher.dashboard import (
	add_queue_item,
	get_dashboard_data,
	get_dashboard_history,
	get_employee_detail,
	get_queue_form_data,
)


__all__ = [
	"add_queue_item",
	"get_dashboard_data",
	"get_dashboard_history",
	"get_employee_detail",
	"get_queue_form_data",
]
