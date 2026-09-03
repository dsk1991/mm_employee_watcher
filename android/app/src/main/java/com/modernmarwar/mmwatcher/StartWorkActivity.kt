package com.modernmarwar.mmwatcher

import android.os.Bundle
import android.view.View
import android.widget.ArrayAdapter
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.modernmarwar.mmwatcher.databinding.ActivityStartWorkBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class StartWorkActivity : AppCompatActivity() {

    private lateinit var b: ActivityStartWorkBinding
    private var activities: List<Watcher.Activity> = emptyList()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityStartWorkBinding.inflate(layoutInflater)
        setContentView(b.root)
        supportActionBar?.title = getString(R.string.start_work)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)

        b.btnStart.setOnClickListener { submit() }
        b.btnBreak.setOnClickListener {
            setBusy(true)
            lifecycleScope.launch {
                try {
                    withContext(Dispatchers.IO) { Watcher.markBreak(null) }
                    finishOk()
                } catch (e: Exception) {
                    setBusy(false)
                    toast(userMessage(e))
                }
            }
        }

        b.etActivity.setOnItemClickListener { _, _, position, _ ->
            activities.getOrNull(position)?.defaultMinutes?.let {
                if (it > 0) b.etMinutes.setText(it.toString())
            }
        }

        loadContext()
    }

    override fun onSupportNavigateUp(): Boolean {
        finish()
        return true
    }

    private fun loadContext() {
        lifecycleScope.launch {
            val loaded = withContext(Dispatchers.IO) {
                val acts = runCatching { Watcher.activities() }.getOrDefault(emptyList())
                val next = runCatching { Watcher.nextWork() }.getOrNull()
                acts to next
            }
            activities = loaded.first
            if (activities.isNotEmpty()) {
                b.etActivity.setAdapter(
                    ArrayAdapter(
                        this@StartWorkActivity,
                        android.R.layout.simple_list_item_1,
                        activities.map { it.name },
                    ),
                )
            }
            loaded.second?.let { next ->
                b.tvQueueHint.visibility = View.VISIBLE
                b.tvQueueHint.text = "Next in your queue: ${next.activity} — tap to use"
                b.tvQueueHint.setOnClickListener {
                    b.etActivity.setText(next.activity, false)
                    next.targetQty?.let { q -> b.etQty.setText(fmtNum(q)) }
                    activities.firstOrNull { it.name == next.activity }?.defaultMinutes?.let {
                        if (it > 0) b.etMinutes.setText(it.toString())
                    }
                }
            }
        }
    }

    private fun submit() {
        val activity = b.etActivity.text.toString().trim()
        val description = b.etDescription.text.toString().trim()
        val minutes = b.etMinutes.text.toString().trim().toIntOrNull() ?: 0
        val qty = b.etQty.text.toString().trim().toDoubleOrNull()

        if (activity.isEmpty()) {
            toast("Pick a work activity")
            return
        }
        if (description.isEmpty()) {
            toast("Describe what you're working on")
            return
        }
        if (minutes <= 0) {
            toast("Enter a target duration in minutes")
            return
        }

        setBusy(true)
        lifecycleScope.launch {
            try {
                withContext(Dispatchers.IO) { Watcher.startWork(activity, description, minutes, qty) }
                finishOk()
            } catch (e: Exception) {
                setBusy(false)
                toast(userMessage(e))
            }
        }
    }

    private fun finishOk() {
        setResult(RESULT_OK)
        finish()
    }

    private fun setBusy(busy: Boolean) {
        b.progress.visibility = if (busy) View.VISIBLE else View.GONE
        b.btnStart.isEnabled = !busy
        b.btnBreak.isEnabled = !busy
    }

    private fun userMessage(e: Throwable) = when (e) {
        is FrappeClient.ApiException -> e.userMessage
        else -> "Something went wrong — try again"
    }

    private fun fmtNum(d: Double) = if (d == d.toLong().toDouble()) d.toLong().toString() else d.toString()

    private fun toast(msg: String) =
        android.widget.Toast.makeText(this, msg, android.widget.Toast.LENGTH_SHORT).show()
}
