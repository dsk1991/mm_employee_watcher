package com.modernmarwar.mmwatcher

import android.content.Intent
import android.os.Bundle
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.modernmarwar.mmwatcher.databinding.ActivityLoginBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class LoginActivity : AppCompatActivity() {

    private lateinit var b: ActivityLoginBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (Prefs.isLoggedIn) {
            goToMain()
            return
        }

        b = ActivityLoginBinding.inflate(layoutInflater)
        setContentView(b.root)

        b.etSite.setText(Prefs.baseUrl.ifBlank { "https://" })
        b.btnLogin.setOnClickListener { attemptLogin() }
    }

    private fun attemptLogin() {
        val site = b.etSite.text.toString().trim()
        val user = b.etUser.text.toString().trim()
        val pass = b.etPass.text.toString()

        if (site.length < 8 || !site.contains(".")) {
            showError("Enter your full site URL, e.g. https://erp.company.com")
            return
        }
        if (user.isEmpty() || pass.isEmpty()) {
            showError("Enter your username and password")
            return
        }

        setBusy(true)
        lifecycleScope.launch {
            try {
                withContext(Dispatchers.IO) { FrappeClient.login(site, user, pass) }
                Tracking.start(applicationContext)
                goToMain()
            } catch (e: FrappeClient.ApiException) {
                setBusy(false)
                showError(e.userMessage)
            } catch (e: Exception) {
                setBusy(false)
                showError("Could not reach the site. Check the URL and your connection.")
            }
        }
    }

    private fun goToMain() {
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }

    private fun setBusy(busy: Boolean) {
        b.progress.visibility = if (busy) View.VISIBLE else View.GONE
        b.btnLogin.isEnabled = !busy
        b.etSite.isEnabled = !busy
        b.etUser.isEnabled = !busy
        b.etPass.isEnabled = !busy
    }

    private fun showError(message: String) {
        b.tvError.text = message
        b.tvError.visibility = View.VISIBLE
    }
}
