# mm_employee_watcher — Backend Architecture (हिंदी)

**Project:** Employee Tracker App (Smart Work Watcher)
**Status:** Design draft
**Last updated:** 2026-09-03

## 1. Dedicated Frappe app क्यों (Client Script क्यों नहीं)

Watcher को एक जैसी employee state कई जगह चाहिए — ERPNext Desk, WMS, Android
HHT app, और आगे कोई भी नया client। Client Script सिर्फ एक Desk session में
चलती है, वो shared source of truth नहीं बन सकती। इसलिए ये एक अलग,
installable Frappe app के रूप में रहेगा — `mm_employee_watcher` — जिसमें
DocTypes और whitelisted REST/RPC methods होंगे, और हर client इसी backend
से बात करेगा।

## 2. Core DocTypes

| DocType | काम |
|---|---|
| **Employee Work Session** | Employee अभी क्या कर रहा है — start/end time, target qty, reference document। |
| **Employee Current Status** | Current state — `WORKING`, `IDLE`, `BREAK`, `BLOCKED`, `OFFLINE`। |
| **Employee Work Log** | Permanent audit trail — start, pause, extend, complete, idle start/end। |
| **Work Activity Master** | हर activity type (Packing, Picking, Cutting, Stitching, Calling, Putaway आदि) के rules। |
| **Employee Work Queue** | Employee के लिए अगला available काम। |

### Employee Work Session — ज़रूरी fields

- `source_app` — किस system ने ये session बनाया (WMS, ERPNext, HHT आदि)
- `reference_doctype` / `reference_name` — जिस business document से ये session जुड़ा है

Mapping examples:

| Activity | Linked reference |
|---|---|
| Packing | Delivery Note / Packing Job |
| Cutting | Work Order / Job Card |
| Picking | Pick List |
| Sales / calling | Customer / Follow-up |

## 3. 2:00 बजे का expiry flow (target-time based sessions)

Session का target end time सिर्फ UI countdown नहीं है — ये एक असली
server-side state change होना चाहिए:

1. **Scheduler**: Frappe का periodic scheduled job expired
   `Employee Work Session` records ढूंढेगा (target time निकल चुका है,
   काम अभी complete नहीं हुआ)।
2. **Realtime push**: हर expired session के लिए `frappe.publish_realtime`
   उस employee के connected Desk/browser client को तुरंत event भेजेगा —
   connected client के लिए polling की ज़रूरत नहीं।
3. Alert पर employee के पास ये options होंगे:
   - **Done** — actual completed time + quantity save होगा,
     `Employee Current Status = IDLE` हो जाएगा।
   - **Extend** — 15 / 30 / 60 min presets, या custom duration।
   - **Blocked / Need Help** — `Employee Current Status = BLOCKED`
     reason के साथ।
4. Session close होते ही employee को generic popup नहीं, useful free-time
   message दिखेगा:

   > "You are free for 00:07 minutes. Next priority work: PACK-0182 —
   > 140 pcs Shirt Packing. Start Work."

   यानी watcher सिर्फ idle time flag नहीं करता — `Employee Work Queue` से
   अगला काम भी employee को दे देता है।

## 4. Automatic integration (दो जगह data entry नहीं)

अगर source system को पहले से पता है कि काम पूरा हो गया, तो employee को
watcher में manually "Done" नहीं करना चाहिए। Watcher को actual operational
documents के completion events सुनकर matching session खुद close कर देना
चाहिए:

| Source event | Watcher action |
|---|---|
| WMS: Packing Job complete | Packing session auto-complete |
| WMS: Pick List finish | Picking session auto-complete |
| WMS: Putaway finish | Putaway session auto-complete |
| Production: Job Card / Work Summary operation complete | Corresponding session auto-complete |

Generic काम जिसका कोई source document नहीं है (जैसे "rack cleaning 10–11",
"customer calling 3–4") — वहाँ कोई hook नहीं होगा, employee खुद **Done**
दबाएगा।

यही वजह है कि `reference_doctype` / `reference_name` इतने important हैं —
यही watcher को सही document के completion event से subscribe करने देते हैं,
वरना employee को दो systems update करने पड़ते।

## 5. हर app में same "Smart Work Bar"

एक छोटी persistent bar, हर जगह एक जैसी:

```
🟢 Packing | Shirt | 216/300 pcs | 42 min left
```

- ERPNext Desk — header में bar।
- WMS — same bar।
- Android HHT app — same bar।

ये सब एक ही endpoint से data लेंगे:
`GET /api/method/mm_employee_watcher.api.get_my_status`।
Frappe DocTypes खुद-ब-खुद REST APIs expose करते हैं, और custom whitelisted
methods add करना आसान है — इसलिए Android/WMS सहित हर client इसी central
backend को use कर सकता है।

### Common whitelisted API methods

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

Android call sequence के लिए [`wms-integration.md`](wms-integration.md) देखें।

## 6. Office / Supervisor dashboard

Live employee cards, जैसे:

```
Mahipal     — WORKING — Shirt Packing — 216/300 — ends 2:00
Vinay       — IDLE 18 min — No active work
Rameshwar   — BLOCKED 7 min — Stock not available
Ragunath    — WORKING — Putaway — extended 30 min
```

Manager को एक नज़र में पता चलेगा — कौन काम कर रहा है, किस काम पर है, कितना
output हुआ, कितना time बचा है, और कौन बिना काम के बैठा है।

### Daily report

- Productive Time
- Idle Time
- Break Time
- Blocked Time
- Total Tasks
- Target Qty vs Completed Qty
- Extensions (count)
- Average output / hour

## 7. Pakke rules

1. **एक समय पर एक employee का सिर्फ एक Primary Active Work।** दो active
   sessions (जैसे 11–2 Packing और 12–3 Picking दोनों active) होने से
   productivity और idle-time calculation बिगड़ जाता है। ये backend में
   enforce होना चाहिए — नया primary session शुरू करने से पहले पुराना
   session close/pause होना ज़रूरी हो, सिर्फ UI convention न हो।
2. **Planned rule: Attendance check-in के बाद ही tracker active हो।** इसके
   लिए HRMS shift/attendance policy configuration चाहिए और current release
   अभी इसे enforce नहीं करता; अभी attendance-gated tracking claim न करें।
3. **Authorized Lunch/Tea Break → `BREAK`, कभी `IDLE` नहीं।** ये दोनों
   states अलग-अलग हैं और reporting में अलग matter करती हैं।
4. **Checkout के बाद → `OFF DUTY`**, बाकी सब states से अलग।
5. **Network/app बंद होना = `IDLE` नहीं।** Connection टूटना या app बंद
   होना सीधा idle time नहीं गिनना चाहिए — इसके लिए अलग
   `OFFLINE` / `NO HEARTBEAT` state होनी चाहिए, क्योंकि manager के लिए
   इनका मतलब अलग है।

## 8. Mobile / closed app reliability

`frappe.publish_realtime` (Socket.IO) सिर्फ **connected** clients तक पहुँचता
है — अगर Android app बंद है या पूरी तरह background में है, तो कुछ नहीं
होगा। 2:00 बजे जैसे alert को closed app तक पहुँचाने के लिए, realtime socket
event के साथ-साथ एक **FCM push notification** channel भी होना चाहिए।
State हमेशा Frappe (Employee Work Session record और उसकी state machine)
में ही रहेगा — FCM सिर्फ delivery का ज़रिया है, source of truth नहीं।

## 9. Aage ka vision: Company Work Operating System

"Employee Watcher" से आगे, ये engine पूरी company की work tracking की
backbone बन सकता है:

- **Warehouse:** Pick / Pack / Putaway
- **Production:** Cutting / Stitching / Kaj-Button / Iron / QC
- **B2B team:** Calling / Order / Recovery
- **Retail:** Customer Handling / Stock Work

सभी activity types इन्हीं DocTypes, states और API surface से जुड़ेंगे।

सबसे important feature: employee free होते ही system role और priority के
हिसाब से अगला काम खुद suggest करे — इससे dashboard सिर्फ monitoring tool
नहीं रहेगा, बल्कि असली **work allocation engine** बन जाएगा।

## 10. Recommended build order

1. `Employee Work Session` + `Employee Current Status` + `Employee Work Queue`
2. Realtime notifications (scheduler + `publish_realtime` + FCM)
3. Core whitelisted API methods (`start_work`, `complete_work` आदि) और
   उन्हें use करने वाली Smart Work Bar
4. Supervisor dashboard + daily report
5. WMS (Packing/Picking/Putaway) और Production (Job Card / Work Summary)
   के लिए automatic integration hooks
6. Sales/B2B और Retail activity types तक extend करना

ये foundation (`Employee Work Session` + `Current Status` + `Work Queue`
+ realtime) ही है जिस पर WMS, production, sales सब कुछ connect होगा —
इसलिए इसे पहले बनाना और stabilize करना सबसे clean रास्ता है।
