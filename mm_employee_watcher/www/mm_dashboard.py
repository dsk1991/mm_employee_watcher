import frappe


def get_context(context):
	context.no_cache = 1
	# Requires a logged-in session (default whitelist behaviour) — see
	# README "Wall-display dashboard" for how to set up a read-only kiosk
	# login so a TV browser can stay signed in permanently.
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/mm_dashboard"
		raise frappe.Redirect
