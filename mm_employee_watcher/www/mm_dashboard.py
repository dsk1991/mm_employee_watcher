import frappe


def get_context(context):
	context.no_cache = 1
	# Requires a logged-in session (default whitelist behaviour) — see
	# README "Wall-display dashboard" for how to set up a read-only kiosk
	# login so a TV browser can stay signed in permanently.
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/mm_dashboard"
		raise frappe.Redirect

	# Set explicitly (rather than relying on the page reaching into
	# frappe.session inside Jinja) so the JS has a real CSRF token to send.
	context.csrf_token = frappe.local.session.data.get("csrf_token", "")
