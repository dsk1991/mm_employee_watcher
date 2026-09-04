// MM Employee Watcher — Desk-side floating work widget.
//
// Requirement: a small WhatsApp-style floating button (bottom-right) with a
// live timer for the current work. Click it for a panel with End Work /
// Extend / Blocked, or Start Work when idle.
// Requirement: when the employee opens ERPNext Desk with no active work, a
// forced "Work Now" popup asks what they are going to do — it will not close
// until work is started (or the employee marks a break).
// Requirement: ending work asks "what did you do?" (free text), then the
// next "Work Now" popup.
// Also handles the "target time is up" popup (Done / Extend / Blocked) fired
// by the server's check_expired_sessions scheduled job.

frappe.provide("mm_employee_watcher");

function mm_watcher_boot() {
	if (typeof frappe === "undefined" || !frappe.session) return;
	mm_employee_watcher.init();
}

$(document).on("app_ready", mm_watcher_boot);
// Fallback: if this bundle finished loading after `app_ready` already fired,
// boot anyway. init() is guarded so a double call is a no-op.
setTimeout(mm_watcher_boot, 3000);

mm_employee_watcher.init = function () {
	if (mm_employee_watcher._inited) return;
	if (frappe.session.user === "Guest") return;
	mm_employee_watcher._inited = true;

	mm_employee_watcher.ensure_widget();
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
	setInterval(mm_employee_watcher.tick, 1000);

	frappe.realtime.on("mm_employee_watcher:session_expired", function (data) {
		mm_employee_watcher.show_expiry_dialog(data);
	});
	frappe.realtime.on("mm_employee_watcher:status_update", function () {
		mm_employee_watcher.check_status(true);
	});
	frappe.realtime.on("mm_employee_watcher:work_required", function () {
		mm_employee_watcher.check_status(true);
		mm_employee_watcher.show_work_now_dialog();
	});
	// Supervisor alert toast — fires for the users listed in MM Watcher
	// Settings, whether or not they are tracked employees themselves.
	frappe.realtime.on("mm_employee_watcher:supervisor_alert", function (data) {
		if (!data) return;
		var label = { Idle: __("is idle"), Overdue: __("is over target time"), Blocked: __("is blocked") };
		frappe.show_alert(
			{
				message: "⚠ " + frappe.utils.escape_html(data.employee_name || data.employee) + " " +
					(label[data.alert_type] || data.alert_type) +
					(data.reason ? " — " + frappe.utils.escape_html(data.reason) : ""),
				indicator: "red",
			},
			12
		);
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

	// Nag: every 2 minutes, if the employee still has no active work, pop the
	// "Start Work" dialog again (BREAK is left alone — they chose that).
	setInterval(function () {
		if (!mm_employee_watcher._tracking_active) return;
		if (document.visibilityState !== "visible") return;
		if (mm_employee_watcher._dialog_open) return;
		var s = mm_employee_watcher._status;
		if (s && !s.current_session && s.status === "IDLE") {
			mm_employee_watcher.check_status();
		}
	}, 2 * 60 * 1000);
};

mm_employee_watcher.check_status = function (silent) {
	frappe.call({
		method: "mm_employee_watcher.api.get_my_status",
		callback: function (r) {
			var status = r.message;
			if (!status || !status.employee || status.tracking === false) {
				mm_employee_watcher._tracking_active = false;
				mm_employee_watcher._status = null;
				mm_employee_watcher.render_widget(null);
				return;
			}
			mm_employee_watcher._tracking_active = true;
			mm_employee_watcher._status = status;
			mm_employee_watcher.render_widget(status);

			if (status.expired && status.session) {
				mm_employee_watcher.show_expiry_dialog({
					work_session: status.session.name,
					work_activity: status.session.work_activity,
					target_qty: status.session.target_qty,
					completed_qty: status.session.completed_qty,
					target_end_time: status.session.target_end_time,
				});
			} else if (!status.current_session && status.status === "IDLE" && !silent) {
				mm_employee_watcher.show_work_now_dialog();
			}
		},
	});
};

// ---------------------------------------------------------------------------
// Floating widget
// ---------------------------------------------------------------------------

mm_employee_watcher.ensure_widget = function () {
	if (document.getElementById("mm-fab")) return;
	frappe.dom.set_style(`
		#mm-fab {
			position: fixed; right: 18px; bottom: 18px; z-index: 1050;
			width: 56px; height: 56px; border-radius: 50%; border: none;
			background: #25d366; color: #fff; cursor: pointer;
			display: flex; align-items: center; justify-content: center;
			font-size: 24px; line-height: 1;
			box-shadow: 0 4px 14px rgba(0,0,0,.3);
		}
		#mm-fab.mm-idle { background: #ef4444; animation: mm-pulse 1.6s infinite; }
		#mm-fab .mm-badge {
			position: absolute; top: -7px; right: -9px;
			background: #172033; color: #fde68a;
			font-size: 10px; font-weight: 700; padding: 2px 6px;
			border-radius: 10px; font-variant-numeric: tabular-nums;
		}
		#mm-fab.mm-idle .mm-badge { background: #7f1d1d; color: #fff; }
		#mm-fab .mm-badge.mm-over { background: #b91c1c; color: #fff; }
		/* Minimized: a small pill on the right edge that still shows the timer. */
		#mm-fab.mm-min {
			width: auto; min-width: 20px; height: 24px; right: 0; bottom: 26px;
			padding: 0 7px 0 9px; border-radius: 12px 0 0 12px;
			font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums;
			animation: none; box-shadow: -2px 3px 10px rgba(0,0,0,.28);
		}
		#mm-fab.mm-min .mm-badge {
			position: static; top: auto; right: auto;
			background: transparent; color: inherit; padding: 0; font-size: 11px;
			border-radius: 0;
		}
		#mm-fab.mm-over { background: #b91c1c; }
		@keyframes mm-pulse {
			0% { box-shadow: 0 0 0 0 rgba(239,68,68,.55); }
			70% { box-shadow: 0 0 0 14px rgba(239,68,68,0); }
			100% { box-shadow: 0 0 0 0 rgba(239,68,68,0); }
		}
		/* Side panel docked to the right edge. Visibility is the .mm-open
		   class only — render_widget never calls jQuery show()/hide() on it,
		   so re-rendering its contents can't force it back open. */
		#mm-fab-panel {
			position: fixed; right: 0; bottom: 88px; z-index: 1049;
			width: 280px; max-width: calc(100vw - 12px);
			background: var(--fg-color, #fff); color: var(--text-color, #1f272e);
			border: 1px solid var(--border-color, #e2e6e9); border-right: none;
			border-radius: 12px 0 0 12px; padding: 14px 16px; font-size: 13px;
			box-shadow: -6px 8px 30px rgba(0,0,0,.22);
			display: none;
		}
		#mm-fab-panel.mm-open { display: block; }
		#mm-fab-panel .mm-p-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
		#mm-fab-panel .mm-p-head .mm-p-title { font-size: 10px; letter-spacing: .5px; text-transform: uppercase; color: var(--text-muted, #6c7680); }
		#mm-fab-panel .mm-p-head .mm-p-min { border: none; background: transparent; cursor: pointer; font-size: 16px; line-height: 1; color: var(--text-muted, #6c7680); padding: 2px 6px; }
		#mm-fab-panel .mm-p-head .mm-p-min:hover { color: var(--text-color, #1f272e); }
		#mm-fab-panel .mm-p-act { font-weight: 700; font-size: 14px; }
		#mm-fab-panel .mm-p-desc { color: var(--text-muted, #6c7680); margin: 4px 0 8px; white-space: pre-wrap; }
		#mm-fab-panel .mm-p-clock { font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; margin: 6px 0; }
		#mm-fab-panel .mm-p-clock.mm-over { color: #b91c1c; }
		#mm-fab-panel .mm-p-since { color: var(--text-muted, #6c7680); font-size: 11px; margin-bottom: 10px; }
		#mm-fab-panel .mm-p-actions { display: flex; flex-wrap: wrap; gap: 6px; }
		#mm-fab-panel .mm-p-actions button { white-space: nowrap; }
	`);
	$("body").append('<button id="mm-fab" style="display:none"></button><div id="mm-fab-panel"></div>');
	try {
		mm_employee_watcher._minimized = localStorage.getItem("mm_watcher_min") === "1";
	} catch (e) {
		mm_employee_watcher._minimized = false;
	}
	$(document).on("click", "#mm-fab", function () {
		if (mm_employee_watcher._minimized) {
			mm_employee_watcher.set_minimized(false);
			$("#mm-fab-panel").addClass("mm-open");
		} else {
			$("#mm-fab-panel").toggleClass("mm-open");
		}
	});
	$(document).on("click", function (e) {
		if (!$(e.target).closest("#mm-fab-panel, #mm-fab").length) {
			$("#mm-fab-panel").removeClass("mm-open");
		}
	});
};

// Collapse the button to a thin sliver on the screen edge (remembered per
// browser). Clicking the sliver restores it.
mm_employee_watcher.set_minimized = function (min) {
	mm_employee_watcher._minimized = !!min;
	try {
		localStorage.setItem("mm_watcher_min", min ? "1" : "0");
	} catch (e) {
		/* private mode / storage blocked - state stays in memory only */
	}
	if (min) $("#mm-fab-panel").removeClass("mm-open");
	if (mm_employee_watcher._status) {
		mm_employee_watcher.render_widget(mm_employee_watcher._status);
	} else {
		$("#mm-fab").toggleClass("mm-min", !!min);
	}
};

mm_employee_watcher.escape = function (value) {
	return $("<div>").text(value || "").html();
};

mm_employee_watcher.countdown = function (value) {
	if (!value) return "--:--";
	var parsed = Date.parse(String(value).replace(" ", "T"));
	if (Number.isNaN(parsed)) return "--:--";
	var seconds = Math.floor((parsed - Date.now()) / 1000);
	var overdue = seconds < 0;
	seconds = Math.abs(seconds);
	var h = Math.floor(seconds / 3600);
	var m = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
	var s = String(seconds % 60).padStart(2, "0");
	var text = (h > 0 ? h + ":" : "") + m + ":" + s;
	return (overdue ? "-" : "") + text;
};

mm_employee_watcher.is_overdue = function (value) {
	if (!value) return false;
	var parsed = Date.parse(String(value).replace(" ", "T"));
	return !Number.isNaN(parsed) && parsed - Date.now() < 0;
};

mm_employee_watcher.render_widget = function (status) {
	var fab = $("#mm-fab");
	var panel = $("#mm-fab-panel");
	if (!status || status.tracking === false) {
		fab.hide();
		panel.removeClass("mm-open");
		return;
	}

	var session = status.session || null;
	var working = !!session;
	var mini = !!mm_employee_watcher._minimized;
	fab.toggleClass("mm-idle", !working);
	fab.toggleClass("mm-min", mini);

	var head =
		'<div class="mm-p-head"><span class="mm-p-title">' + __("Work Timer") + "</span>" +
		'<button class="mm-p-min" data-mm-min title="' + __("Minimize") + '">&#8211;</button></div>';

	if (working) {
		var over = mm_employee_watcher.is_overdue(session.target_end_time);
		var clock = mm_employee_watcher.countdown(session.target_end_time);
		fab.toggleClass("mm-over", over && mini);
		fab.html(
			(mini ? "" : "🤖") +
			'<span class="mm-badge' + (over && !mini ? " mm-over" : "") + '" data-mm-badge>' +
			clock +
			"</span>"
		).show();

		var startTxt = session.start_time
			? frappe.datetime.str_to_user(session.start_time)
			: "";
		panel.html(
			head +
			'<div class="mm-p-act">' + mm_employee_watcher.escape(session.work_activity) + "</div>" +
			'<div class="mm-p-desc">' + mm_employee_watcher.escape(session.notes || "") + "</div>" +
			'<div class="mm-p-clock' + (over ? " mm-over" : "") + '" data-mm-panel-clock>' +
			mm_employee_watcher.countdown(session.target_end_time) + "</div>" +
			'<div class="mm-p-since">' + __("Started") + ": " + mm_employee_watcher.escape(startTxt) + "</div>" +
			'<div class="mm-p-actions">' +
			'<button class="btn btn-sm btn-primary" data-mm-end>' + __("End Work") + "</button>" +
			'<button class="btn btn-sm btn-default" data-mm-ext="15">+15m</button>' +
			'<button class="btn btn-sm btn-default" data-mm-ext="30">+30m</button>' +
			'<button class="btn btn-sm btn-default" data-mm-block>' + __("Blocked") + "</button>" +
			"</div>"
		);
	} else {
		fab.removeClass("mm-over");
		fab.html(mini ? '<span data-mm-badge>&bull;</span>' : "🤖").show();
		panel.html(
			head +
			'<div class="mm-p-act">' + __("No work in progress") + "</div>" +
			'<div class="mm-p-desc">' + __("Start a new work to begin the timer.") + "</div>" +
			'<div class="mm-p-actions">' +
			'<button class="btn btn-sm btn-primary" data-mm-start>' + __("Start Work") + "</button>" +
			"</div>"
		);
	}

	panel.find("[data-mm-min]").on("click", function () {
		mm_employee_watcher.set_minimized(true);
	});
	panel.find("[data-mm-end]").on("click", mm_employee_watcher.show_end_work_dialog);
	panel.find("[data-mm-start]").on("click", function () {
		mm_employee_watcher.show_work_now_dialog();
	});
	panel.find("[data-mm-block]").on("click", mm_employee_watcher.show_blocked_dialog);
	panel.find("[data-mm-ext]").on("click", function () {
		var minutes = parseInt($(this).attr("data-mm-ext"), 10);
		if (!session) return;
		frappe.call({
			method: "mm_employee_watcher.api.extend_work",
			args: { work_session: session.name, minutes: minutes },
			callback: function () {
				frappe.show_alert({ message: __("Extended by {0} minutes", [minutes]), indicator: "blue" });
				mm_employee_watcher.check_status(true);
			},
		});
	});
};

mm_employee_watcher.tick = function () {
	var status = mm_employee_watcher._status;
	if (!status || !status.session) return;
	var end = status.session.target_end_time;
	var text = mm_employee_watcher.countdown(end);
	var over = mm_employee_watcher.is_overdue(end);
	var mini = !!mm_employee_watcher._minimized;
	$("#mm-fab [data-mm-badge]").text(text).toggleClass("mm-over", over && !mini);
	$("#mm-fab").toggleClass("mm-over", over && mini);
	$("#mm-fab-panel [data-mm-panel-clock]").text(text).toggleClass("mm-over", over);
};

// ---------------------------------------------------------------------------
// Dialogs
// ---------------------------------------------------------------------------

// Make a dialog un-dismissable: no close button, no backdrop click, no ESC.
// Call mm_employee_watcher.release_dialog(d) before d.hide() to let it close.
mm_employee_watcher.lock_dialog = function (d) {
	d._mm_locked = true;
	var closeBtn = d.get_close_btn ? d.get_close_btn() : d.$wrapper.find(".btn-modal-close");
	if (closeBtn && closeBtn.hide) closeBtn.hide();
	var modal = d.$wrapper;
	var data = modal.data("bs.modal");
	if (data) {
		data.options.backdrop = "static";
		data.options.keyboard = false;
	}
	modal.on("hide.bs.modal.mmlock", function (e) {
		if (d._mm_locked) {
			e.preventDefault();
			e.stopImmediatePropagation();
			return false;
		}
	});
};

mm_employee_watcher.release_dialog = function (d) {
	d._mm_locked = false;
	d.$wrapper.off("hide.bs.modal.mmlock");
};

// Forced "Work Now" popup — what will you do next?
mm_employee_watcher.show_work_now_dialog = function (suggestion) {
	if (mm_employee_watcher._dialog_open) return;
	mm_employee_watcher._dialog_open = true;

	function render(suggestion) {
		var suggestedActivity = suggestion
			? (suggestion.work_activity || suggestion.default_work_activity || null)
			: null;
		var d = new frappe.ui.Dialog({
			title: __("What work are you starting now?"),
			fields: [
				{
					fieldname: "work_activity",
					label: __("Work"),
					fieldtype: "Link",
					options: "Work Activity Master",
					reqd: 1,
					default: suggestedActivity,
				},
				{
					fieldname: "description",
					label: __("What exactly will you do?"),
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
					frappe.msgprint(__("Please describe the work"));
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
						mm_employee_watcher.release_dialog(d);
						d.hide();
						mm_employee_watcher.check_status(true);
					},
				});
			},
			secondary_action_label: __("I'm on a break"),
			secondary_action: function () {
				frappe.call({
					method: "mm_employee_watcher.api.mark_break",
					callback: function () {
						frappe.show_alert({ message: __("Marked as break"), indicator: "blue" });
						mm_employee_watcher.release_dialog(d);
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
		mm_employee_watcher.lock_dialog(d);
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

// End Work — what did you actually do?
mm_employee_watcher.show_end_work_dialog = function () {
	var status = mm_employee_watcher._status || {};
	if (!status.session) return;
	if (mm_employee_watcher._end_dialog_open) return;
	mm_employee_watcher._end_dialog_open = true;
	var d = new frappe.ui.Dialog({
		title: __("End Work: {0}", [status.session.work_activity]),
		fields: [
			{
				fieldname: "remarks",
				label: __("What did you do / complete?"),
				fieldtype: "Small Text",
				reqd: 1,
			},
			{
				fieldname: "completed_qty",
				label: __("Completed Qty (optional)"),
				fieldtype: "Float",
				default: status.session.completed_qty || 0,
			},
		],
		primary_action_label: __("End Work"),
		primary_action: function (values) {
			var control = d.get_field("remarks");
			var remarks = String(
				control && control.$input ? control.$input.val() : values.remarks || ""
			).trim();
			if (!remarks) {
				frappe.msgprint(__("Please describe what you worked on"));
				return;
			}
			frappe.call({
				method: "mm_employee_watcher.api.end_work",
				args: {
					work_session: status.session.name,
					remarks: remarks,
					completed_qty: values.completed_qty,
				},
				callback: function () {
					d.hide();
					frappe.show_alert({ message: __("Work ended"), indicator: "green" });
					$("#mm-fab-panel").removeClass("mm-open");
					mm_employee_watcher.check_status();
				},
			});
		},
	});
	d.onhide = function () {
		mm_employee_watcher._end_dialog_open = false;
	};
	d.show();
};

mm_employee_watcher.show_blocked_dialog = function () {
	var status = mm_employee_watcher._status || {};
	if (!status.session) return;
	var d = new frappe.ui.Dialog({
		title: __("Blocked: {0}", [status.session.work_activity]),
		fields: [
			{
				fieldname: "reason",
				label: __("What is blocking you?"),
				fieldtype: "Small Text",
				reqd: 1,
			},
		],
		primary_action_label: __("Mark Blocked"),
		primary_action: function (values) {
			frappe.call({
				method: "mm_employee_watcher.api.mark_blocked",
				args: { work_session: status.session.name, reason: values.reason },
				callback: function () {
					d.hide();
					$("#mm-fab-panel").removeClass("mm-open");
					mm_employee_watcher.check_status(true);
				},
			});
		},
	});
	d.show();
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
				fieldname: "remarks",
				label: __("What did you do? (needed to finish)"),
				fieldtype: "Small Text",
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
						mm_employee_watcher.check_status(true);
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
						mm_employee_watcher.check_status(true);
					},
				});
			} else {
				if (!values.remarks) {
					frappe.msgprint(__("Please describe what you worked on"));
					return;
				}
				frappe.call({
					method: "mm_employee_watcher.api.end_work",
					args: {
						work_session: data.work_session,
						remarks: values.remarks,
						completed_qty: values.completed_qty,
					},
					callback: function (r) {
						d.hide();
						var res = r.message || {};
						if (res.auto_started) {
							// Requirement #5: next queued work picked up automatically.
							frappe.show_alert({
								message: __("Next work started: {0}", [res.auto_started.work_activity]),
								indicator: "green",
							});
							mm_employee_watcher.check_status(true);
						} else {
							if (res.auto_start_failed) {
								frappe.msgprint(
									__("Work completed, but the next queue item could not start. Please ask a supervisor to check it.")
								);
							}
							// Nothing queued — force the "Work Now" popup.
							mm_employee_watcher.check_status();
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

// ---------------------------------------------------------------------------
// Passive desktop activity tracking (Sales Invoice / Payment Entry / reports)
// ---------------------------------------------------------------------------

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
		} else if (
			route[0] === "Form" &&
			route[1] &&
			route[2] &&
			!String(route[2]).toLowerCase().startsWith("new-")
		) {
			// Any other saved document the employee opens — record it as a
			// passive audit-trail entry (no work-session change).
			var svKey = "sv|" + route[1] + "|" + route[2];
			if (mm_employee_watcher._last_screen_view !== svKey) {
				mm_employee_watcher._last_screen_view = svKey;
				frappe.call({
					method: "mm_employee_watcher.api.record_screen_view",
					args: { reference_doctype: route[1], reference_name: route[2] },
					freeze: false,
				});
			}
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
			callback: function () {
				mm_employee_watcher.check_status(true);
			},
		});
	}
	frappe.router.on("change", trackRoute);
	setTimeout(trackRoute, 0);
};
