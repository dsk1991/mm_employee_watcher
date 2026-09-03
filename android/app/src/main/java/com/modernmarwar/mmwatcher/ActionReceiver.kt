package com.modernmarwar.mmwatcher

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.RemoteInput

/** Handles the buttons on the "time is up" notification and "Stop tracking". */
class ActionReceiver : BroadcastReceiver() {

    companion object {
        const val ACTION_END = "com.modernmarwar.mmwatcher.action.END"
        const val ACTION_EXTEND = "com.modernmarwar.mmwatcher.action.EXTEND"
        const val ACTION_BLOCK = "com.modernmarwar.mmwatcher.action.BLOCK"
        const val ACTION_STOP = "com.modernmarwar.mmwatcher.action.STOP"
        const val EXTRA_SESSION = "session"
    }

    override fun onReceive(context: Context, intent: Intent) {
        val appContext = context.applicationContext

        if (intent.action == ACTION_STOP) {
            Tracking.stop(appContext)
            return
        }

        val session = intent.getStringExtra(EXTRA_SESSION) ?: return
        val typed = RemoteInput.getResultsFromIntent(intent)
            ?.getCharSequence(Notifications.REMOTE_KEY)?.toString()?.trim()
        val action = intent.action ?: return

        val pending = goAsync()
        Thread {
            try {
                when (action) {
                    ACTION_END -> Watcher.endWork(session, typed?.ifBlank { null } ?: "Completed", null)
                    ACTION_EXTEND -> Watcher.extendWork(session, 30)
                    ACTION_BLOCK -> Watcher.markBlocked(session, typed?.ifBlank { null } ?: "Blocked")
                }
                Notifications.cancel(appContext, Notifications.ID_EXPIRY)
                Prefs.expiryNotifiedSession = ""
                Heartbeat.runCycle(appContext, active = true)
            } catch (e: Exception) {
                Notifications.error(
                    appContext,
                    "Could not update work",
                    e.message ?: "Open the app and try again",
                )
            } finally {
                pending.finish()
            }
        }.start()
    }
}
