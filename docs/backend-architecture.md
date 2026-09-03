# mm_employee_watcher — Backend Architecture

**Project:** Employee Tracker App (Smart Work Watcher)
**Status:** Design draft
**Last updated:** 2026-09-03

## 1. Why a dedicated Frappe app (not Client Scripts)

The watcher has to expose the *same* employee state to multiple surfaces —
ERPNext Desk, WMS, the Android HHT app, and any future client. A Client
Script only runs inside one Desk session and can't be a shared source of
truth. So this lives as its own installable Frappe app, `mm_employee_watcher`,
with DocTypes + whitelisted REST/RPC methods as the single backend every
client talks to.

## 2. Core DocTypes

| DocType | Purpose |
|---|---|
| **Employee Work Session** | What an employee is doing right now: start/end time, target qty, reference document. |
| **Employee Current Status** | Current state — `WORKING`, `IDLE`, `BREAK`, `BLOCKED`, `OFFLINE`. |
| **Employee Work Log** | Permanent audit trail — start, pause, extend, complete, idle start/end. |
| **Work Activity Master** | Rules per activity type — Packing, Picking, Cutting, Stitching, Calling, Putaway, etc. |
| **Employee Work Queue** | Next available work item(s) for an employee. |

### Employee Work Session — key fields

- `source_app` — which system created this session (WMS, ERPNext, HHT, etc.)
- `reference_doctype` / `reference_name` — the business document the session is tied to

Mapping examples:

| Activity | Linked reference |
|---|---|
| Packing | Delivery Note / Packing Job |
| Cutting | Work Order / Job Card |
| Picking | Pick List |
| Sales / calling | Customer / Follow-up |

## 3. The 2:00 PM expiry flow (target-time-based sessions)

A session's target end time isn't just a UI countdown — it has to be a real
server-side state transition:

1. **Scheduler**: a Frappe periodic scheduled job scans for expired
   `Employee Work Session` records (target time passed, not yet completed).
2. **Realtime push**: for each expired session, `frappe.publish_realtime`
   fires an event to the employee's connected Desk/browser client
   immediately — no polling needed for a connected client.
3. **Employee response options** on the alert:
   - **Done** — saves actual completed time + quantity, sets
     `Employee Current Status = IDLE`.
   - **Extend** — 15 / 30 / 60 min presets, or a custom duration.
   - **Blocked / Need Help** — sets `Employee Current Status = BLOCKED`
     with a reason.
4. Once the session is closed the employee sees a *useful* free-time
   message, not a generic nag:

   > "You are free for 00:07 minutes. Next priority work: PACK-0182 —
   > 140 pcs Shirt Packing. Start Work."

   i.e. the watcher doesn't just flag idle time — it hands the employee
   the next `Employee Work Queue` item.

## 4. Automatic integration (no double data-entry)

Employees should almost never have to manually mark work "Done" in the
watcher if the source system already knows it's done. The watcher should
listen for completion events from the actual operational documents and
auto-close the matching session:

| Source event | Watcher action |
|---|---|
| WMS: Packing Job completed | Auto-complete Packing session |
| WMS: Pick List finished | Auto-complete Picking session |
| WMS: Putaway finished | Auto-complete Putaway session |
| Production: Job Card / Work Summary operation completed | Auto-complete corresponding session |

Generic, non-document-backed work (e.g. "rack cleaning 10–11",
"customer calling 3–4") has no source document to hook into, so those stay
manual — employee taps **Done** themselves.

This is the point of `reference_doctype` / `reference_name`: it's what lets
the watcher subscribe to the right document's completion event instead of
relying on the employee to update two systems.

## 5. One shared "Smart Work Bar" across every app

A small persistent bar, identical everywhere the employee is logged in:

```
🟢 Packing | Shirt | 216/300 pcs | 42 min left
```

- ERPNext Desk — bar in the header.
- WMS — same bar.
- Android HHT app — same bar.

All of these read from one endpoint:
`GET /api/method/mm_employee_watcher.api.get_my_status`.
Since Frappe DocTypes expose REST out of the box, and custom whitelisted
methods are trivial to add, every client (including the Android app) can
hit the same central backend rather than each maintaining its own state.

### Common whitelisted API surface

- `start_work`
- `complete_work`
- `extend_work`
- `pause_work`
- `resume_work`
- `mark_blocked`
- `get_my_status`
- `get_next_work`
- `heartbeat`
- `start_reference_work` (idempotent WMS/HHT start)
- `update_progress` (absolute completed quantity)
- `complete_reference_work` (idempotent WMS/HHT completion)

See [`wms-integration.md`](wms-integration.md) for the Android call sequence.

## 6. Office / Supervisor dashboard

Live employee cards, e.g.:

```
Mahipal     — WORKING — Shirt Packing — 216/300 — ends 2:00
Vinay       — IDLE 18 min — No active work
Rameshwar   — BLOCKED 7 min — Stock not available
Ragunath    — WORKING — Putaway — extended 30 min
```

A manager sees, at a glance: who's working, on what, how much output,
how much time is left, and who's sitting idle.

### Daily report

- Productive Time
- Idle Time
- Break Time
- Blocked Time
- Total Tasks
- Target Qty vs Completed Qty
- Extensions (count)
- Average output / hour

## 7. Hard rules

1. **One Primary Active Work per employee at a time.** Two concurrent
   active sessions (e.g. Packing 11–2 and Picking 12–3 both "active")
   corrupts productivity and idle-time math. The backend must enforce
   this — starting a new primary session should require closing/pausing
   any existing one, not just be a UI convention.
2. **Planned rule: tracker only runs after attendance check-in.** This rule
   needs HRMS shift/attendance policy configuration and is not enforced by
   the current release; do not claim attendance-gated tracking yet.
3. **Authorized Lunch/Tea Break → `BREAK`, never `IDLE`.** These are
   distinct states with different reporting semantics.
4. **After checkout → `OFF DUTY`**, a distinct state from all of the above.
5. **Network/app-down ≠ `IDLE`.** A dropped connection or closed app
   should surface as `OFFLINE` / `NO HEARTBEAT`, not silently count as
   idle time — those mean different things to a manager.

## 8. Mobile / closed-app reliability

`frappe.publish_realtime` (Socket.IO) only reaches **connected** clients —
it does nothing for a closed or fully backgrounded Android app. For the
2:00 PM-style alert to reach someone whose app isn't open, the watcher
needs an **FCM push notification** as a second delivery channel alongside
the realtime socket event. Frappe (the Employee Work Session record and
its state machine) remains the source of truth either way — FCM is just
a delivery mechanism, not where state lives.

## 9. Long-term vision: Company Work Operating System

Beyond "watch the employee," this engine can become the backbone for
work tracking across the company:

- **Warehouse:** Pick / Pack / Putaway
- **Production:** Cutting / Stitching / Kaj-Button / Iron / QC
- **B2B team:** Calling / Order / Recovery
- **Retail:** Customer Handling / Stock Work

All activity types plug into the same DocTypes, states, and API surface.

The single most valuable feature: the moment an employee goes free, the
system suggests the next task based on their role and priority — turning
the dashboard from a passive monitoring tool into an actual **work
allocation engine**.

## 10. Recommended build order

1. `Employee Work Session` + `Employee Current Status` + `Employee Work Queue`
2. Realtime notifications (scheduler + `publish_realtime` + FCM)
3. Core whitelisted API methods (`start_work`, `complete_work`, etc.) and
   the Smart Work Bar consuming them
4. Supervisor dashboard + daily report
5. Wire up automatic integration hooks for WMS (Packing/Picking/Putaway)
   and Production (Job Card / Work Summary)
6. Extend to Sales/B2B and Retail activity types

This foundation (`Employee Work Session` + `Current Status` + `Work Queue`
+ realtime) is what everything else — WMS, production, sales — plugs into,
so it should be built and stabilized first.
