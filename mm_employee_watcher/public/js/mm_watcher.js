// MM Employee Watcher — Desk-side popups.
//
// Requirement #3: if the logged-in employee has no active work, show a
// "Work Now" popup as soon as ERPNext Desk opens.
// Requirement #6: that popup's UI is a simple form — Work, Description,
// Start Time, Duration, Target Qty.
// Also handles the "target time is up" popup (Done / Extend / Blocked)
// fired by the server's check_expired_sessions scheduled job.

frappe.provide("mm_employee_watcher");

$(document).on("app_ready", function () {
	mm_employee_watcher.init();
});

mm_employee_watcher.init = function () {
	if (frappe.session.user === "Guest") return;

	mm_employee_watcher.check_status();

	frappe.realtime.on("mm_employee_watcher:session_expired", function (data) {
		mm_employee_watcher.show_expiry_dialog(data);
	});

	// Keep the offline watchdog honest: this Desk tab counts as "alive"
	// only while it's actually open.
	setInterval(function () {
		frappe.call({
			method: "mm_employee_watcher.mm_employee_watcher.api.heartbeat",
			// silent — no need to spam the console every 4 minutes
			freeze: false,
		});
	}, 4 * 60 * 1000);
};

mm_employee_watcher.check_status = function () {
	frappe.call({
		method: "mm_employee_watcher.mm_employee_watcher.api.get_my_status",
		callback: function (r) {
			var status = r.message;
			if (!status || !status.employee) return; // no Employee linked to this user
			if (status.tracking === false) return; // requirement #4: tracking off for this user

			if (status.status === "IDLE" && !status.current_session) {
				mm_employee_watcher.show_work_now_dialog();
			}
		},
	});
};

// Requirement #3 + #6: the "Work Now" popup.
mm_employee_watcher.show_work_now_dialog = function (suggestion) {
	if (mm_employee_watcher._dialog_open) return;
	mm_employee_watcher._dialog_open = true;

	function render(suggestion) {
		var d = new frappe.ui.Dialog({
			title: __("Work Now"),
			fields: [
				{
					fieldname: "work_activity",
					label: __("Work"),
					fieldtype: "Link",
					options: "Work Activity Master",
					reqd: 1,
					default: suggestion ? suggestion.work_activity : null,
				},
				{
					fieldname: "description",
					label: __("Work Description"),
					fieldtype: "Small Text",
				},
				{ fieldtype: "Column Break" },
				{
					fieldname: "start_time",
					label: __("Start Time"),
					fieldtype: "Datetime",
					default: frappe.datetime.now_datetime(),
					read_only: 1,
				},
				{
					fieldname: "duration_minutes",
					label: __("Duration (minutes)"),
					fieldtype: "Int",
					default: 60,
					description: __("Used to compute the End Time target."),
				},
				{
					fieldname: "target_qty",
					label: __("Target Qty"),
					fieldtype: "Float",
					default: suggestion ? suggestion.target_qty : null,
				},
			],
			primary_action_label: __("Start Work"),
			primary_action: function (values) {
				frappe.call({
					method: "mm_employee_watcher.mm_employee_watcher.api.start_work",
					args: {
						work_activity: values.work_activity,
						target_qty: values.target_qty,
						target_minutes: values.duration_minutes,
						reference_doctype: suggestion ? suggestion.reference_doctype : null,
						reference_name: suggestion ? suggestion.reference_name : null,
					},
					callback: function () {
						frappe.show_alert({ message: __("Work started"), indicator: "green" });
						d.hide();
					},
				});
			},
		});
		d.onhide = function () {
			mm_employee_watcher._dialog_open = false;
		};
		d.show();
	}

	if (suggestion !== undefined) {
		render(suggestion);
	} else {
		frappe.call({
			method: "mm_employee_watcher.mm_employee_watcher.api.get_next_work",
			callback: function (r) {
				render(r.message);
			},
		});
	}
};

// Fires when the server's expiry sweep finds this employee's active
// session past its target time. Employee picks Done / Extend / Blocked.
mm_employee_watcher.show_expiry_dialog = function (data) {
	var d = new frappe.ui.Dialog({
		title: __("Time's up: {0}", [data.work_activity]),
		fields: [
			{
				fieldname: "info",
				fieldtype: "HTML",
				options:
					"<p>" +
					__("Target time for this work is over.") +
					" " +
					__("Target Qty: {0}, Completed so far: {1}", [
						data.target_qty || 0,
						data.completed_qty || 0,
					]) +
					"</p>",
			},
			{
				fieldname: "completed_qty",
				label: __("Completed Qty"),
				fieldtype: "Float",
				default: data.completed_qty,
			},
			{
				fieldname: "extend_minutes",
				label: __("Extend by (minutes — leave 0 for no extension)"),
				fieldtype: "Int",
				default: 0,
			},
			{
				fieldname: "blocked_reason",
				label: __("Blocked reason (leave blank if not blocked)"),
				fieldtype: "Small Text",
			},
		],
		primary_action_label: __("Submit"),
		primary_action: function (values) {
			if (values.blocked_reason) {
				frappe.call({
					method: "mm_employee_watcher.mm_employee_watcher.api.mark_blocked",
					args: { work_session: data.work_session, reason: values.blocked_reason },
					callback: function () {
						d.hide();
					},
				});
			} else if (values.extend_minutes) {
				frappe.call({
					method: "mm_employee_watcher.mm_employee_watcher.api.extend_work",
					args: { work_session: data.work_session, minutes: values.extend_minutes },
					callback: function () {
						frappe.show_alert({
							message: __("Extended by {0} minutes", [values.extend_minutes]),
							indicator: "blue",
						});
						d.hide();
					},
				});
			} else {
				frappe.call({
					method: "mm_employee_watcher.mm_employee_watcher.api.complete_work",
					args: { work_session: data.work_session, completed_qty: values.completed_qty },
					callback: function (r) {
						d.hide();
						var res = r.message || {};
						if (res.auto_started) {
							// Requirement #5: next queued work picked up automatically.
							frappe.show_alert({
								message: __("Next work started: {0}", [res.auto_started.work_activity]),
								indicator: "green",
							});
						} else {
							// Nothing queued — let them pick manually (requirement #3).
							mm_employee_watcher.show_work_now_dialog(res.next_work);
						}
					},
				});
			}
		},
	});
	d.show();
};
