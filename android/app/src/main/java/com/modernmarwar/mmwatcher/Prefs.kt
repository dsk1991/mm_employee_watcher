package com.modernmarwar.mmwatcher

import android.content.Context
import android.content.SharedPreferences

/** Tiny wrapper over SharedPreferences for the handful of values the app keeps. */
object Prefs {

    private lateinit var sp: SharedPreferences

    fun init(context: Context) {
        sp = context.applicationContext.getSharedPreferences("mmwatcher", Context.MODE_PRIVATE)
    }

    var baseUrl: String
        get() = sp.getString("base_url", "") ?: ""
        set(value) {
            var v = value.trim()
            if (v.isNotEmpty() && !v.startsWith("http://") && !v.startsWith("https://")) {
                v = "https://$v"
            }
            sp.edit().putString("base_url", v.trimEnd('/')).apply()
        }

    /** Serialized "name=value; name2=value2" cookie jar for the Frappe session. */
    var cookie: String
        get() = sp.getString("cookie", "") ?: ""
        set(value) = sp.edit().putString("cookie", value).apply()

    var fullName: String
        get() = sp.getString("full_name", "") ?: ""
        set(value) = sp.edit().putString("full_name", value).apply()

    /** Difference (ms) between Frappe server time and this device's clock. */
    var clockOffsetMs: Long
        get() = sp.getLong("clock_offset", 0L)
        set(value) = sp.edit().putLong("clock_offset", value).apply()

    /** Session name we already raised an "over target time" notification for. */
    var expiryNotifiedSession: String
        get() = sp.getString("expiry_session", "") ?: ""
        set(value) = sp.edit().putString("expiry_session", value).apply()

    /** True while the employee is "on shift" and the heartbeat service should run. */
    var trackingActive: Boolean
        get() = sp.getBoolean("tracking_active", false)
        set(value) = sp.edit().putBoolean("tracking_active", value).apply()

    val isLoggedIn: Boolean
        get() = baseUrl.isNotEmpty() && cookie.contains("sid=")

    fun serverNow(): Long = System.currentTimeMillis() + clockOffsetMs

    fun signOut() {
        sp.edit()
            .remove("cookie")
            .remove("full_name")
            .remove("expiry_session")
            .putBoolean("tracking_active", false)
            .apply()
    }
}
