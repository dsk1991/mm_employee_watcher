"""Public RPC entry point for the employee watcher dashboard.

The dashboard implementation lives in the app module package, while Frappe's
web page calls ``mm_employee_watcher.dashboard.get_dashboard_data``. Re-export
the whitelisted method here so both the canonical and older nested paths work.
"""

from .mm_employee_watcher.dashboard import get_dashboard_data


__all__ = ["get_dashboard_data"]
