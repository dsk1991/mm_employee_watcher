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

	mm_employee_watcher.ensure_work_bar();
	mm_employee_watcher._last_interaction = Date.now();
	$(document).on("mousemove.mm_watcher keydown.mm_watcher click.mm_watcher touchstart.mm_watcher", function () {
		mm_employee_watcher._last_interaction = Date.now();
		if (mm_employee_watcher._idle_reported && document.visibilityState === "visible") {
			mm_employee_watcher._idle_reported = false;
			frappe.call({ method: "mm_employee_watcher.api.heartbeat", args: { active: 1 }, freeze: false });
		}
	});
	mm_employee_watcher.check_status();
	mm_employee_watcher.bind_desktop_activity_tracking();
	setInterval(mm_employee_watcher.tick_work_bar, 1000);

	frappe.realtime.on("mm_employee_watcher:session_expired", function (data) {
		mm_employee_watcher.show_expiry_dialog(data);
	});
	frappe.realtime.on("mm_employee_watcher:status_update", function () {
		mm_employee_watcher.check_status(true);
	});
	frappe.realtime.on("mm_employee_watcher:section_required", function (data) {
		mm_employee_watcher.check_status(true);
		mm_employee_watcher.show_start_section_dialog(data && data.next_schedule);
	});
	frappe.realtime.on("mm_employee_watcher:section_expired", function (data) {
		mm_employee_watcher.show_section_expiry_dialog(data);
	});
	frappe.realtime.on("mm_employee_watcher:section_mismatch", function (data) {
		frappe.msgprint({
			title: __("Change work section"),
			indicator: "orange",
			message: __("Your active section is {0}. End it before starting {1} work.", [
				data.active_section,
				data.required_section,
			]),
		});
	});

	// Keep the offline watchdog honest: this Desk tab counts as "alive"
	// only while it's actually open.
	setInterval(function () {
		if (!mm_employee_watcher._tracking_active) return;
		if (document.visibilityState !== "visible") return;
		var active = Date.now() - mm_employee_watcher._last_interaction < 5 * 60 * 1000;
		mm_employee_watcher._idle_reported = !active;
		frappe.call({
			method: "mm_employee_watcher.api.heartbeat",
			args: { active: active ? 1 : 0 },
			// silent — no need to spam the console every 4 minutes
			freeze: false,
		});
	}, 4 * 60 * 1000);
	setInterval(function () {
		if (!mm_employee_watcher._tracking_active || mm_employee_watcher._idle_reported) return;
		if (document.visibilityState !== "visible") return;
		if (Date.now() - mm_employee_watcher._last_interaction < 5 * 60 * 1000) return;
		mm_employee_watcher._idle_reported = true;
		frappe.call({
			method: "mm_employee_watcher.api.heartbeat",
			args: { active: 0 },
			freeze: false,
		});
	}, 60 * 1000);
};

mm_employee_watcher.check_status = function (silent) {
	frappe.call({
		method: "mm_employee_watcher.api.get_my_status",
		callback: function (r) {
			var status = r.message;
			if (!status || !status.employee || status.tracking === false) {
				mm_employee_watcher._tracking_active = false;
				mm_employee_watcher.render_work_bar(null);
				return;
			}
			mm_employee_watcher._tracking_active = true;
			mm_employee_watcher._status = status;
			mm_employee_watcher.render_work_bar(status);

			if (status.section_expired && status.section) {
				mm_employee_watcher.show_section_expiry_dialog({
					section_session: status.section.name,
					work_section: status.section.work_section,
					target_end_time: status.section.target_end_time,
				});
			} else if (status.expired && status.session) {
				mm_employee_watcher.show_expiry_dialog({
					work_session: status.session.name,
					work_activity: status.session.work_activity,
					target_qty: status.session.target_qty,
					completed_qty: status.session.completed_qty,
					target_end_time: status.session.target_end_time,
				});
			} else if (!status.current_section_session) {
				if (!silent) mm_employee_watcher.show_start_section_dialog(status.next_schedule);
			} else if (
				status.status === "IDLE" &&
				!status.current_session &&
				(!status.section || status.section.section_type === "Work")
			) {
				mm_employee_watcher.show_work_now_dialog();
			}
		},
	});
};

mm_employee_watcher.ensure_work_bar = function () {
	if (document.getElementById("mm-work-bar")) return;
	frappe.dom.set_style(`
		#mm-work-bar {
			position: fixed; left: 12px; right: 12px; bottom: 10px; z-index: 1040;
			display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
			padding: 10px 14px; border-radius: 10px; color: #fff;
			background: #172033; box-shadow: 0 5px 22px rgba(0,0,0,.28);
			font-size: 13px;
		}
		#mm-work-bar.mm-missing { background: #7f1d1d; }
		#mm-work-bar .mm-label { color: #a9b5ca; font-size: 10px; text-transform: uppercase; }
		#mm-work-bar .mm-value { font-weight: 700; }
		#mm-work-bar .mm-clock { font-variant-numeric: tabular-nums; color: #fde68a; }
		#mm-work-bar .mm-spacer { flex: 1; }
		#mm-work-bar button { white-space: nowrap; }
		@media (max-width: 700px) {
			#mm-work-bar { left: 5px; right: 5px; bottom: 5px; gap: 8px; }
			#mm-work-bar .mm-reference { display: none; }
		}
	`);
	$("body").append('<div id="mm-work-bar" style="display:none"></div>');
};

mm_employee_watcher.escape = function (value) {
	return $("<div>").text(value || "").html();
};

mm_employee_watcher.countdown = function (value) {
	if (!value) return "--:--:--";
	var parsed = Date.parse(String(value).replace(" ", "T"));
	if (Number.isNaN(parsed)) return "--:--:--";
	var seconds = Math.floor((parsed - Date.now()) / 1000);
	var overdue = seconds < 0;
	seconds = Math.abs(seconds);
	var h = String(Math.floor(seconds / 3600)).padStart(2, "0");
	var m = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
	var s = String(seconds % 60).padStart(2, "0");
	return (overdue ? __("Overdue") + " " : "") + h + ":" + m + ":" + s;
};

mm_employee_watcher.render_work_bar = function (status) {
	var bar = $("#mm-work-bar");
	if (!status) {
		bar.hide();
		return;
	}
	var section = status.section || null;
	var session = status.session || null;
	var next = status.next_schedule || null;
	bar.toggleClass("mm-missing", !section);

	var sectionName = section ? section.work_section : (next ? next.work_section : __("No section active"));
	var workName = session ? session.work_activity : (section && section.section_type === "Break" ? __("Break") : __("Please start new work"));
	var reference = session && session.reference_name
		? '<span class="mm-reference">' + mm_employee_watcher.escape(session.reference_name) + "</span>"
		: "";
	var sectionClock = section ? mm_employee_watcher.countdown(section.target_end_time) : "--:--:--";
	var workClock = session ? mm_employee_watcher.countdown(session.target_end_time) : "--:--:--";

	var html =
		'<span><span class="mm-label">' + __("Section") + '</span><br><span class="mm-value">' + mm_employee_watcher.escape(sectionName) + "</span></span>" +
		'<span><span class="mm-label">' + __("Section Time") + '</span><br><span class="mm-value mm-clock" data-mm-section-clock>' + sectionClock + "</span></span>" +
		'<span><span class="mm-label">' + __("Work") + '</span><br><span class="mm-value">' + mm_employee_watcher.escape(workName) + "</span> " + reference + "</span>" +
		'<span><span class="mm-label">' + __("Work Time") + '</span><br><span class="mm-value mm-clock" data-mm-work-clock>' + workClock + "</span></span>" +
		'<span class="mm-spacer"></span>';
	if (!section) {
		html += '<button class="btn btn-sm btn-light" data-mm-start-section>' + __("Start Section") + "</button>";
	} else if (section.section_type !== "Break") {
		if (!session) html += '<button class="btn btn-sm btn-success" data-mm-start-work>' + __("Start Work") + "</button>";
		if (session) html += '<button class="btn btn-sm btn-light" data-mm-end-work>' + __("End Work") + "</button>";
		html += '<button class="btn btn-sm btn-outline-light" data-mm-end-section>' + __("End Section") + "</button>";
	} else {
		html += '<button class="btn btn-sm btn-light" data-mm-end-section>' + __("End Break") + "</button>";
	}

	bar.html(html).show();
	bar.find("[data-mm-start-section]").on("click", function () {
		mm_employee_watcher.show_start_section_dialog(next);
	});
	bar.find("[data-mm-start-work]").on("click", function () {
		mm_employee_watcher.show_work_now_dialog(next);
	});
	bar.find("[data-mm-end-work]").on("click", mm_employee_watcher.show_end_work_dialog);
	bar.find("[data-mm-end-section]").on("click", mm_employee_watcher.show_end_section_dialog);
};

mm_employee_watcher.tick_work_bar = function () {
	var status = mm_employee_watcher._status;
	if (!status) return;
	if (status.section) {
		$("#mm-work-bar [data-mm-section-clock]").text(
			mm_employee_watcher.countdown(status.section.target_end_time)
		);
	}
	if (status.session) {
		$("#mm-work-bar [data-mm-work-clock]").text(
			mm_employee_watcher.countdown(status.session.target_end_time)
		);
	}
};

mm_employee_watcher.show_start_section_dialog = function (schedule) {
	if (mm_employee_watcher._section_dialog_open) return;
	mm_employee_watcher._section_dialog_open = true;
	var d = new frappe.ui.Dialog({
		title: __("Please start new work"),
		fields: [
			{
				fieldname: "work_section",
				label: __("Work Section"),
				fieldtype: "Link",
				options: "Work Section Master",
				reqd: 1,
				default: schedule ? schedule.work_section : null,
				get_query: function () { return { filters: { enabled: 1 } }; },
			},
			{
				fieldname: "target_minutes",
				label: __("Section Duration (minutes)"),
				fieldtype: "Int",
				default: 120,
				hidden: !!schedule,
			},
			{
				fieldname: "notes",
				label: __("Section Note"),
				fieldtype: "Small Text",
				default: schedule ? schedule.notes : null,
			},
		],
		primary_action_label: __("Start Section"),
		primary_action: function (values) {
			frappe.call({
				method: "mm_employee_watcher.api.start_section",
				args: {
					work_section: values.work_section,
					schedule: schedule ? schedule.name : null,
					target_minutes: values.target_minutes,
					source_app: "ERPNext",
					notes: values.notes,
				},
				callback: function (r) {
					d.hide();
					frappe.show_alert({ message: __("Section started"), indicator: "green" });
					mm_employee_watcher.check_status(true);
					var result = r.message || {};
					if (result.section && result.section.section_type !== "Break") {
						mm_employee_watcher.show_work_now_dialog({
							work_activity: result.suggested_work_activity,
						});
					}
				},
			});
		},
	});
	d.onhide = function () { mm_employee_watcher._section_dialog_open = false; };
	d.show();
};

mm_employee_watcher.show_end_work_dialog = function () {
	var status = mm_employee_watcher._status || {};
	if (!status.session) return;
	var d = new frappe.ui.Dialog({
		title: __("End Work: {0}", [status.session.work_activity]),
		fields: [
			{
				fieldname: "completed_qty",
				label: __("Completed Qty"),
				fieldtype: "Float",
				default: status.session.completed_qty || 0,
			},
			{
				fieldname: "remarks",
				label: __("Completion Remarks"),
				fieldtype: "Small Text",
			},
		],
		primary_action_label: __("End Work"),
		primary_action: function (values) {
			frappe.call({
				method: "mm_employee_watcher.api.complete_work",
				args: {
					work_session: status.session.name,
					completed_qty: values.completed_qty,
					remarks: values.remarks,
				},
				callback: function () {
					d.hide();
					frappe.show_alert({ message: __("Work completed. Please start new work."), indicator: "green" });
					mm_employee_watcher.check_status(true);
					setTimeout(function () { mm_employee_watcher.show_work_now_dialog(); }, 250);
				},
			});
		},
	});
	d.show();
};

mm_employee_watcher.show_end_section_dialog = function () {
	var status = mm_employee_watcher._status || {};
	if (!status.section) return;
	var d = new frappe.ui.Dialog({
		title: __("End Section: {0}", [status.section.work_section]),
		fields: [
			{
				fieldname: "completed_qty",
				label: __("Current Work Completed Qty"),
				fieldtype: "Float",
				default: status.session ? status.session.completed_qty || 0 : 0,
				hidden: !status.session,
			},
			{
				fieldname: "reason",
				label: __("Section End Note"),
				fieldtype: "Small Text",
				reqd: 1,
			},
		],
		primary_action_label: __("End Section"),
		primary_action: function (values) {
			frappe.call({
				method: "mm_employee_watcher.api.end_section",
				args: {
					section_session: status.section.name,
					reason: values.reason,
					completed_qty: values.completed_qty,
					work_remarks: values.reason,
				},
				callback: function (r) {
					d.hide();
					mm_employee_watcher.check_status(true);
					frappe.msgprint(__("Section closed. Please start new work."));
					var result = r.message || {};
					setTimeout(function () {
						mm_employee_watcher.show_start_section_dialog(result.next_schedule);
					}, 250);
				},
			});
		},
	});
	d.show();
};

mm_employee_watcher.show_section_expiry_dialog = function (data) {
	if (!data || !data.section_session || mm_employee_watcher._expired_section === data.section_session) return;
	mm_employee_watcher._expired_section = data.section_session;
	var d = new frappe.ui.Dialog({
		title: __("Section time completed: {0}", [data.work_section]),
		fields: [
			{
				fieldname: "extend_minutes",
				label: __("Extend by minutes (0 to finish)"),
				fieldtype: "Int",
				default: 0,
			},
			{
				fieldname: "reason",
				label: __("Note / Reason"),
				fieldtype: "Small Text",
			},
		],
		primary_action_label: __("Submit"),
		primary_action: function (values) {
			if (values.extend_minutes) {
				frappe.call({
					method: "mm_employee_watcher.api.extend_section",
					args: { section_session: data.section_session, minutes: values.extend_minutes },
					callback: function () { d.hide(); mm_employee_watcher.check_status(true); },
				});
			} else {
				frappe.call({
					method: "mm_employee_watcher.api.end_section",
					args: { section_session: data.section_session, reason: values.reason || __("Target time completed") },
					callback: function (r) {
						d.hide();
						mm_employee_watcher.check_status(true);
						mm_employee_watcher.show_start_section_dialog((r.message || {}).next_schedule);
					},
				});
			}
		},
	});
	d.onhide = function () { mm_employee_watcher._expired_section = null; };
	d.show();
};

mm_employee_watcher.bind_desktop_activity_tracking = function () {
	if (!frappe.router || !frappe.router.on) return;
	function trackRoute() {
		var route = frappe.get_route() || [];
		var activity = null;
		var description = null;
		var referenceDoctype = null;
		var referenceName = null;
		if (route[0] === "Form" && (route[1] === "Sales Invoice" || route[1] === "Payment Entry")) {
			activity = route[1] === "Sales Invoice" ? "Sales Invoice Creation" : "Payment Entry";
			description = __("Opened {0} screen", [route[1]]);
			if (route[2] && !String(route[2]).toLowerCase().startsWith("new-")) {
				referenceDoctype = route[1];
				referenceName = route[2];
			}
		} else if (route[0] === "query-report" || route[0] === "report-view") {
			activity = "Report Viewing";
			description = __("Viewed report {0}", [route[1] || ""]);
		}
		if (!activity) return;
		var key = [activity, referenceDoctype || "", referenceName || "", description].join("|");
		if (mm_employee_watcher._last_route_activity === key) return;
		mm_employee_watcher._last_route_activity = key;
		frappe.call({
			method: "mm_employee_watcher.api.record_desktop_activity",
			args: {
				work_activity: activity,
				action: activity === "Report Viewing" ? "Report Viewed" : "Screen Opened",
				reference_doctype: referenceDoctype,
				reference_name: referenceName,
				description: description,
			},
			callback: function (r) {
				var result = r.message || {};
				if (result.requires_section) mm_employee_watcher.show_start_section_dialog(result.next_schedule);
				mm_employee_watcher.check_status(true);
			},
		});
	}
	frappe.router.on("change", trackRoute);
	setTimeout(trackRoute, 0);
};

// Requirement #3 + #6: the "Work Now" popup.
mm_employee_watcher.show_work_now_dialog = function (suggestion) {
	if (mm_employee_watcher._dialog_open) return;
	mm_employee_watcher._dialog_open = true;

	function render(suggestion) {
		var suggestedActivity = suggestion
			? (suggestion.work_activity || suggestion.default_work_activity || null)
			: null;
		var d = new frappe.ui.Dialog({
			title: __("Work Now"),
			fields: [
				{
					fieldname: "work_activity",
					label: __("Work"),
					fieldtype: "Link",
					options: "Work Activity Master",
					reqd: 1,
					default: suggestedActivity,
					get_query: function () {
						var section = mm_employee_watcher._status && mm_employee_watcher._status.current_section;
						return section ? { filters: { work_section: section } } : {};
					},
				},
				{
					fieldname: "description",
					label: __("Work Description"),
					fieldtype: "Small Text",
					reqd: 1,
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
				// Small Text controls may not copy the last typed characters into
				// `values` until the textarea loses focus. Read the live input so a
				// user who types and immediately clicks Start Work is not rejected.
				var descriptionControl = d.get_field("description");
				var description = String(
					descriptionControl && descriptionControl.$input
						? descriptionControl.$input.val()
						: values.description || ""
				).trim();
				if (!description) {
					frappe.msgprint(__("Work Description is required"));
					return;
				}
				frappe.call({
					method: "mm_employee_watcher.api.start_work",
					args: {
						work_activity: values.work_activity,
						target_qty: values.target_qty,
						target_minutes: values.duration_minutes,
						description: description,
						reference_doctype: suggestion ? suggestion.reference_doctype : null,
						reference_name: suggestion ? suggestion.reference_name : null,
					},
					callback: function () {
						frappe.show_alert({ message: __("Work started"), indicator: "green" });
						d.hide();
						mm_employee_watcher.check_status(true);
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
			method: "mm_employee_watcher.api.get_next_work",
			callback: function (r) {
				render(r.message);
			},
		});
	}
};

// Fires when the server's expiry sweep finds this employee's active
// session past its target time. Employee picks Done / Extend / Blocked.
mm_employee_watcher.show_expiry_dialog = function (data) {
	if (!data || !data.work_session) return;
	if (mm_employee_watcher._expiry_session === data.work_session) return;
	mm_employee_watcher._expiry_session = data.work_session;

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
					method: "mm_employee_watcher.api.mark_blocked",
					args: { work_session: data.work_session, reason: values.blocked_reason },
					callback: function () {
						d.hide();
					},
				});
			} else if (values.extend_minutes) {
				frappe.call({
					method: "mm_employee_watcher.api.extend_work",
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
					method: "mm_employee_watcher.api.complete_work",
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
							if (res.auto_start_failed) {
								frappe.msgprint(
									__("Work completed, but the next queue item could not start. Please ask a supervisor to check it.")
								);
							}
							// Nothing queued — let them pick manually (requirement #3).
							mm_employee_watcher.show_work_now_dialog(res.next_work);
						}
					},
				});
			}
		},
	});
	d.onhide = function () {
		mm_employee_watcher._expiry_session = null;
	};
	d.show();
};
