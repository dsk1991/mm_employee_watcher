package com.modernmarwar.mmwatcher

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.widget.EditText
import android.widget.LinearLayout
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.modernmarwar.mmwatcher.databinding.ActivityMainBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : AppCompatActivity() {

    private lateinit var b: ActivityMainBinding
    private var status: Watcher.Status? = null

    private val ticker = Handler(Looper.getMainLooper())
    private val pollHandler = Handler(Looper.getMainLooper())

    private val tickRunnable = object : Runnable {
        override fun run() {
            renderTimer()
            ticker.postDelayed(this, 1_000)
        }
    }
    private val pollRunnable = object : Runnable {
        override fun run() {
            refresh(silent = true)
            pollHandler.postDelayed(this, 30_000)
        }
    }

    private val updates = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            when (intent?.action) {
                Heartbeat.ACTION_STATUS_CHANGED -> refresh(silent = true)
                Heartbeat.ACTION_NEEDS_LOGIN -> forceRelogin()
            }
        }
    }

    private val startWork = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { refresh() }

    private val notifPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (!Prefs.isLoggedIn) {
            forceRelogin()
            return
        }

        b = ActivityMainBinding.inflate(layoutInflater)
        setContentView(b.root)
        supportActionBar?.title = Prefs.fullName.ifBlank { getString(R.string.app_name) }

        b.swipe.setOnRefreshListener { refresh() }
        b.btnStart.setOnClickListener { startWork.launch(Intent(this, StartWorkActivity::class.java)) }
        b.btnEnd.setOnClickListener { endWorkDialog() }
        b.btnExtend15.setOnClickListener { act { Watcher.extendWork(requireSession(), 15) } }
        b.btnExtend30.setOnClickListener { act { Watcher.extendWork(requireSession(), 30) } }
        b.btnBlocked.setOnClickListener { blockedDialog() }
        b.btnResume.setOnClickListener { act { Watcher.resumeWork(requireSession()) } }
        b.btnBreak.setOnClickListener { act { Watcher.markBreak(null) } }

        askNotificationPermission()
        Tracking.start(applicationContext)
    }

    override fun onResume() {
        super.onResume()
        if (!Prefs.isLoggedIn) {
            forceRelogin()
            return
        }
        ContextCompat.registerReceiver(
            this,
            updates,
            IntentFilter().apply {
                addAction(Heartbeat.ACTION_STATUS_CHANGED)
                addAction(Heartbeat.ACTION_NEEDS_LOGIN)
            },
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )
        ticker.post(tickRunnable)
        pollHandler.post(pollRunnable)
        refresh()
    }

    override fun onPause() {
        super.onPause()
        runCatching { unregisterReceiver(updates) }
        ticker.removeCallbacksAndMessages(null)
        pollHandler.removeCallbacksAndMessages(null)
    }

    // ---- data ----------------------------------------------------------

    private fun refresh(silent: Boolean = false) {
        if (!silent) b.swipe.isRefreshing = true
        lifecycleScope.launch {
            try {
                val s = withContext(Dispatchers.IO) { Watcher.myStatus() }
                status = s
                render(s)
            } catch (e: FrappeClient.ApiException) {
                if (e.needsLogin) forceRelogin() else toast(e.userMessage)
            } catch (e: Exception) {
                if (!silent) toast("Could not refresh — check your connection")
            } finally {
                b.swipe.isRefreshing = false
            }
        }
    }

    private fun act(block: suspend () -> Unit) {
        b.swipe.isRefreshing = true
        lifecycleScope.launch {
            try {
                withContext(Dispatchers.IO) { block() }
                refresh()
            } catch (e: FrappeClient.ApiException) {
                b.swipe.isRefreshing = false
                if (e.needsLogin) forceRelogin() else toast(e.userMessage)
            } catch (e: Exception) {
                b.swipe.isRefreshing = false
                toast("Something went wrong — try again")
            }
        }
    }

    private fun requireSession(): String =
        status?.sessionName ?: throw FrappeClient.ApiException("No active work session")

    // ---- rendering ------------------------------------------------------

    private fun render(s: Watcher.Status) {
        if (!s.hasEmployee) {
            showMessageOnly("This login has no linked Employee record. Ask your admin to set User ID on your Employee.")
            return
        }
        if (!s.tracking) {
            showMessageOnly("Work tracking is turned off for your account. Ask your admin to enable it on your User.")
            return
        }

        b.tvMessage.visibility = View.GONE
        b.tvStatus.text = s.state ?: "—"
        b.tvStatus.setTextColor(statusColor(s.state))
        b.tvSince.text = s.statusSinceMs?.let { "since ${minutesAgo(it)}" } ?: ""

        val hasWork = s.hasOpenSession
        b.tvActivity.visibility = if (hasWork) View.VISIBLE else View.GONE
        b.tvDescription.visibility = if (hasWork && !s.description.isNullOrBlank()) View.VISIBLE else View.GONE
        b.tvTimer.visibility = if (hasWork) View.VISIBLE else View.GONE
        b.tvActivity.text = s.activity ?: ""
        b.tvDescription.text = s.description ?: ""

        val qtyVisible = hasWork && (s.targetQty != null || (s.completedQty ?: 0.0) > 0.0)
        b.tvQty.visibility = if (qtyVisible) View.VISIBLE else View.GONE
        if (qtyVisible) {
            val done = fmtNum(s.completedQty ?: 0.0)
            b.tvQty.text = s.targetQty?.let { "Qty $done / ${fmtNum(it)}" } ?: "Qty $done"
        }

        b.tvBlocked.visibility = if (!s.blockedReason.isNullOrBlank()) View.VISIBLE else View.GONE
        b.tvBlocked.text = s.blockedReason?.let { "Blocked: $it" } ?: ""

        // Buttons
        b.btnStart.visibility = if (!hasWork) View.VISIBLE else View.GONE
        b.rowExtend.visibility = if (s.isWorking) View.VISIBLE else View.GONE
        b.btnBlocked.visibility = if (s.isWorking) View.VISIBLE else View.GONE
        b.btnEnd.visibility = if (hasWork) View.VISIBLE else View.GONE
        b.btnResume.visibility = if (s.isPausedOrBlocked) View.VISIBLE else View.GONE
        b.btnBreak.visibility = if (s.state != "BREAK") View.VISIBLE else View.GONE

        renderTimer()
    }

    private fun renderTimer() {
        val s = status ?: return
        if (!s.hasOpenSession) return
        val end = s.targetEndMs
        if (end == null) {
            b.tvTimer.text = "--:--"
            return
        }
        val remaining = end - Prefs.serverNow()
        val over = remaining < 0
        val secs = Math.abs(remaining) / 1000
        val h = secs / 3600
        val m = (secs % 3600) / 60
        val sec = secs % 60
        val clock = if (h > 0) "%d:%02d:%02d".format(h, m, sec) else "%02d:%02d".format(m, sec)
        b.tvTimer.text = if (over) "-$clock" else clock
        b.tvTimer.setTextColor(
            if (over) ContextCompat.getColor(this, R.color.status_blocked)
            else ContextCompat.getColor(this, R.color.status_working),
        )
    }

    private fun showMessageOnly(message: String) {
        b.tvMessage.visibility = View.VISIBLE
        b.tvMessage.text = message
        for (v in listOf(
            b.tvActivity, b.tvDescription, b.tvTimer, b.tvQty, b.tvBlocked,
            b.btnStart, b.rowExtend, b.btnBlocked, b.btnEnd, b.btnResume, b.btnBreak,
        )) v.visibility = View.GONE
        b.tvStatus.text = status?.state ?: "—"
        b.tvSince.text = ""
    }

    // ---- dialogs ------------------------------------------------------

    private fun endWorkDialog() {
        val pad = (16 * resources.displayMetrics.density).toInt()
        val remarks = EditText(this).apply {
            hint = "What did you do / complete?"
            minLines = 2
        }
        val qty = EditText(this).apply {
            hint = "Completed quantity (optional)"
            inputType = android.text.InputType.TYPE_CLASS_NUMBER or android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL
        }
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad / 2, pad, 0)
            addView(remarks)
            addView(qty)
        }
        AlertDialog.Builder(this)
            .setTitle("End work")
            .setView(container)
            .setPositiveButton("End") { _, _ ->
                val text = remarks.text.toString().trim()
                if (text.isEmpty()) {
                    toast("Please describe what you worked on")
                    return@setPositiveButton
                }
                val q = qty.text.toString().trim().toDoubleOrNull()
                act {
                    val result = Watcher.endWork(requireSession(), text, q)
                    withContext(Dispatchers.Main) { announceChain(result) }
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun announceChain(result: Watcher.EndResult) {
        when {
            result.autoStartedActivity != null ->
                toast("Next work started: ${result.autoStartedActivity}")
            result.autoStartFailed ->
                toast("Work ended. Could not auto-start the next queued item.")
            result.nextActivity != null ->
                toast("Next in your queue: ${result.nextActivity}")
        }
    }

    private fun blockedDialog() {
        val input = EditText(this).apply { hint = "Why are you blocked?" }
        val pad = (16 * resources.displayMetrics.density).toInt()
        val container = LinearLayout(this).apply {
            setPadding(pad, pad / 2, pad, 0)
            addView(input)
        }
        AlertDialog.Builder(this)
            .setTitle("Mark blocked")
            .setView(container)
            .setPositiveButton("Mark blocked") { _, _ ->
                val reason = input.text.toString().trim()
                if (reason.isEmpty()) {
                    toast("A reason is required")
                    return@setPositiveButton
                }
                act { Watcher.markBlocked(requireSession(), reason) }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    // ---- menu --------------------------------------------------------

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.main, menu)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        when (item.itemId) {
            R.id.action_refresh -> refresh()
            R.id.action_battery -> requestIgnoreBatteryOptimizations()
            R.id.action_stop_tracking -> {
                Tracking.stop(applicationContext)
                toast("Tracking stopped. Reopen the app to start again.")
                finish()
            }
            R.id.action_sign_out -> {
                Tracking.stop(applicationContext)
                Prefs.signOut()
                forceRelogin()
            }
            else -> return super.onOptionsItemSelected(item)
        }
        return true
    }

    // ---- misc -------------------------------------------------------

    private fun forceRelogin() {
        startActivity(
            Intent(this, LoginActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK),
        )
        finish()
    }

    private fun askNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            notifPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    private fun requestIgnoreBatteryOptimizations() {
        val pm = getSystemService(PowerManager::class.java)
        if (pm.isIgnoringBatteryOptimizations(packageName)) {
            toast("Already exempt from battery optimization")
            return
        }
        runCatching {
            startActivity(
                Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                    .setData(Uri.parse("package:$packageName")),
            )
        }.onFailure {
            startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }
    }

    private fun statusColor(state: String?): Int {
        val res = when (state) {
            "WORKING" -> R.color.status_working
            "IDLE" -> R.color.status_idle
            "BREAK" -> R.color.status_break
            "BLOCKED" -> R.color.status_blocked
            else -> R.color.status_offline
        }
        return ContextCompat.getColor(this, res)
    }

    private fun minutesAgo(sinceMs: Long): String {
        val mins = ((Prefs.serverNow() - sinceMs) / 60_000L).toInt().coerceAtLeast(0)
        return when {
            mins < 1 -> "just now"
            mins < 60 -> "$mins min"
            else -> "${mins / 60}h ${mins % 60}m"
        }
    }

    private fun fmtNum(d: Double) = if (d == d.toLong().toDouble()) d.toLong().toString() else d.toString()

    private fun toast(msg: String) =
        android.widget.Toast.makeText(this, msg, android.widget.Toast.LENGTH_SHORT).show()
}
