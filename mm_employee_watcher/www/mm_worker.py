import frappe


def get_context(context):
	context.no_cache = 1
	# Requires a logged-in session, same as any other Desk page — an
	# unauthenticated visitor is bounced to /login. See README "Mobile
	# tracker (PWA)" for how staff add this to their home screen.
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/mm_worker"
		raise frappe.Redirect

	# Set explicitly (rather than relying on the page reaching into
	# frappe.session inside Jinja) so the JS has a real CSRF token to send.
	context.csrf_token = frappe.local.session.data.get("csrf_token", "")
