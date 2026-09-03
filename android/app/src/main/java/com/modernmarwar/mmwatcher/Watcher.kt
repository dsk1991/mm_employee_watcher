package com.modernmarwar.mmwatcher

import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Locale

/** Typed calls onto the `mm_employee_watcher` whitelisted API. */
object Watcher {

    private const val API = "mm_employee_watcher.api."
    private const val SOURCE_APP = "HHT"

    data class Status(
        val hasEmployee: Boolean,
        val tracking: Boolean,
        val state: String?,             // WORKING / IDLE / BREAK / BLOCKED / OFFLINE / OFF DUTY
        val statusSinceMs: Long?,
        val sessionName: String?,
        val sessionStatus: String?,     // Active / Extended / Paused / Blocked
        val activity: String?,
        val description: String?,
        val targetEndMs: Long?,
        val targetQty: Double?,
        val completedQty: Double?,
        val blockedReason: String?,
        val expired: Boolean,
    ) {
        val hasOpenSession get() = sessionName != null &&
            sessionStatus in setOf("Active", "Extended", "Paused", "Blocked")
        val isWorking get() = sessionStatus == "Active" || sessionStatus == "Extended"
        val isPausedOrBlocked get() = sessionStatus == "Paused" || sessionStatus == "Blocked"
    }

    data class QueueItem(
        val name: String,
        val activity: String,
        val targetQty: Double?,
    )

    data class Activity(val name: String, val defaultMinutes: Int?)

    data class EndResult(
        val autoStartedActivity: String?,
        val autoStartFailed: Boolean,
        val nextActivity: String?,
    )

    // ---- reads ------------------------------------------------------------

    fun myStatus(): Status {
        val m = FrappeClient.callObject("${API}get_my_status")
            ?: return Status(false, false, null, null, null, null, null, null, null, null, null, null, false)

        val employee = m.optString("employee").takeIf { it.isNotBlank() && !m.isNull("employee") }
        if (employee == null) {
            return Status(false, false, null, null, null, null, null, null, null, null, null, null, false)
        }
        if (m.has("tracking") && !m.optBoolean("tracking", true)) {
            return Status(true, false, null, null, null, null, null, null, null, null, null, null, false)
        }

        val session = m.optJSONObject("session")
        return Status(
            hasEmployee = true,
            tracking = true,
            state = m.optString("status").ifBlank { null },
            statusSinceMs = parseTs(m.optString("status_since")),
            sessionName = m.optString("current_session").ifBlank { null },
            sessionStatus = session?.optString("status")?.ifBlank { null },
            activity = session?.optString("work_activity")?.ifBlank { null },
            description = session?.optString("notes")?.ifBlank { null },
            targetEndMs = parseTs(session?.optString("target_end_time")),
            targetQty = session?.optDoubleOrNull("target_qty"),
            completedQty = session?.optDoubleOrNull("completed_qty"),
            blockedReason = session?.optString("blocked_reason")?.ifBlank { null },
            expired = m.optBoolean("expired", false),
        )
    }

    /** Sends a heartbeat and refreshes the server-clock offset. */
    fun heartbeat(active: Boolean) {
        val m = FrappeClient.callObject(
            "${API}heartbeat",
            mapOf("active" to if (active) "1" else "0"),
        )
        parseTs(m?.optString("server_time"))?.let {
            Prefs.clockOffsetMs = it - System.currentTimeMillis()
        }
    }

    fun nextWork(): QueueItem? {
        val m = FrappeClient.callObject("${API}get_next_work") ?: return null
        val name = m.optString("name").ifBlank { return null }
        return QueueItem(
            name = name,
            activity = m.optString("work_activity"),
            targetQty = m.optDoubleOrNull("target_qty"),
        )
    }

    fun activities(): List<Activity> {
        val arr: JSONArray = FrappeClient.callArray(
            "frappe.client.get_list",
            mapOf(
                "doctype" to "Work Activity Master",
                "fields" to "[\"name\",\"default_duration_minutes\"]",
                "limit_page_length" to "0",
                "order_by" to "name asc",
            ),
        ) ?: return emptyList()
        val out = ArrayList<Activity>(arr.length())
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            out.add(Activity(o.optString("name"), o.optIntOrNull("default_duration_minutes")))
        }
        return out
    }

    // ---- writes ---------------------------------------------------------

    fun startWork(activity: String, description: String, minutes: Int, targetQty: Double?) {
        FrappeClient.call(
            "${API}start_work",
            buildMap {
                put("work_activity", activity)
                put("description", description)
                put("target_minutes", minutes.toString())
                put("source_app", SOURCE_APP)
                if (targetQty != null) put("target_qty", trimNum(targetQty))
            },
        )
    }

    fun endWork(session: String, remarks: String, completedQty: Double?): EndResult {
        val m = FrappeClient.callObject(
            "${API}end_work",
            buildMap {
                put("work_session", session)
                put("remarks", remarks)
                if (completedQty != null) put("completed_qty", trimNum(completedQty))
            },
        )
        val auto = m?.optJSONObject("auto_started")
        val next = m?.optJSONObject("next_work")
        return EndResult(
            autoStartedActivity = auto?.optString("work_activity")?.ifBlank { null },
            autoStartFailed = m?.optBoolean("auto_start_failed", false) ?: false,
            nextActivity = next?.optString("work_activity")?.ifBlank { null },
        )
    }

    fun extendWork(session: String, minutes: Int) {
        FrappeClient.call(
            "${API}extend_work",
            mapOf("work_session" to session, "minutes" to minutes.toString()),
        )
    }

    fun markBlocked(session: String, reason: String) {
        FrappeClient.call(
            "${API}mark_blocked",
            mapOf("work_session" to session, "reason" to reason),
        )
    }

    fun resumeWork(session: String) {
        FrappeClient.call("${API}resume_work", mapOf("work_session" to session))
    }

    fun markBreak(reason: String?) {
        FrappeClient.call(
            "${API}mark_break",
            buildMap { if (!reason.isNullOrBlank()) put("reason", reason) },
        )
    }

    // ---- helpers ------------------------------------------------------

    private fun trimNum(d: Double): String =
        if (d == d.toLong().toDouble()) d.toLong().toString() else d.toString()

    private val tsFormat = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)

    private fun parseTs(value: String?): Long? {
        if (value.isNullOrBlank()) return null
        val cleaned = value.substringBefore('.').replace('T', ' ').trim()
        return runCatching { tsFormat.parse(cleaned)?.time }.getOrNull()
    }

    private fun JSONObject.optDoubleOrNull(key: String): Double? =
        if (isNull(key) || !has(key)) null else optDouble(key).takeIf { !it.isNaN() }

    private fun JSONObject.optIntOrNull(key: String): Int? =
        if (isNull(key) || !has(key)) null else optInt(key)
}
