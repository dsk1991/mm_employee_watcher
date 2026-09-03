package com.modernmarwar.mmwatcher

import android.content.Context
import android.content.Intent

/** One heartbeat + status cycle, shared by the service loop and the WorkManager backstop. */
object Heartbeat {

    const val ACTION_STATUS_CHANGED = "com.modernmarwar.mmwatcher.STATUS_CHANGED"
    const val ACTION_NEEDS_LOGIN = "com.modernmarwar.mmwatcher.NEEDS_LOGIN"

    /** @return the fetched [Watcher.Status], or null if the session is gone. */
    fun runCycle(context: Context, active: Boolean): Watcher.Status? {
        return try {
            Watcher.heartbeat(active)
            val status = Watcher.myStatus()
            checkExpiry(context, status)
            context.sendBroadcast(
                Intent(ACTION_STATUS_CHANGED).setPackage(context.packageName),
            )
            status
        } catch (e: FrappeClient.ApiException) {
            if (e.needsLogin) {
                Prefs.trackingActive = false
                context.sendBroadcast(
                    Intent(ACTION_NEEDS_LOGIN).setPackage(context.packageName),
                )
                Tracking.stop(context)
            }
            null
        } catch (e: Exception) {
            null
        }
    }

    private fun checkExpiry(context: Context, status: Watcher.Status) {
        val session = status.sessionName
        if (status.expired && status.isWorking && session != null) {
            if (Prefs.expiryNotifiedSession != session) {
                Prefs.expiryNotifiedSession = session
                Notifications.expiry(context, session, status.activity)
            }
        } else {
            // Not currently over target — let this session alert again if it
            // passes a (possibly extended) target time later.
            if (session != null && Prefs.expiryNotifiedSession == session) {
                Prefs.expiryNotifiedSession = ""
            }
            if (session == null) Notifications.cancel(context, Notifications.ID_EXPIRY)
        }
    }
}
