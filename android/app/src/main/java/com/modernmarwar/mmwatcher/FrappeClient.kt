package com.modernmarwar.mmwatcher

import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * Minimal Frappe HTTP client built on HttpURLConnection (no third-party deps).
 *
 * Auth is a plain session cookie obtained from `/api/method/login`. Every
 * whitelisted method is then called with **GET** — Frappe only runs CSRF
 * validation on unsafe HTTP verbs for a logged-in session, so GET keeps the
 * cookie flow working without needing a CSRF token. The watcher's
 * `@frappe.whitelist()` methods do not restrict the HTTP method.
 */
object FrappeClient {

    /** Thrown for any non-2xx response. [needsLogin] means the session is gone. */
    class ApiException(
        val userMessage: String,
        val needsLogin: Boolean = false,
    ) : Exception(userMessage)

    // ---- public API ---------------------------------------------------------

    /** Logs in and stores the session cookie. Returns the user's full name. */
    fun login(baseUrl: String, user: String, password: String): String {
        Prefs.baseUrl = baseUrl
        Prefs.cookie = ""
        val body = "usr=${enc(user)}&pwd=${enc(password)}"
        val conn = open("/api/method/login")
        conn.requestMethod = "POST"
        conn.doOutput = true
        conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
        conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }

        val code = conn.responseCode
        val text = readBody(conn)
        storeCookies(conn)

        if (code == HttpURLConnection.HTTP_OK && Prefs.cookie.contains("sid=")) {
            val fullName = runCatching { JSONObject(text).optString("full_name") }.getOrDefault("")
            Prefs.fullName = fullName
            return fullName
        }
        val message = runCatching { JSONObject(text).optString("message") }.getOrNull()
        throw ApiException(
            if (!message.isNullOrBlank()) message else "Sign in failed ($code)",
        )
    }

    /** GET a whitelisted method. Returns the `message` payload (JSONObject / JSONArray / primitive) or null. */
    fun call(method: String, params: Map<String, String?> = emptyMap()): Any? {
        val query = params.entries
            .filter { it.value != null }
            .joinToString("&") { "${enc(it.key)}=${enc(it.value!!)}" }
        val path = "/api/method/$method" + if (query.isEmpty()) "" else "?$query"

        val conn = open(path)
        conn.requestMethod = "GET"
        val code = conn.responseCode
        val text = readBody(conn)
        storeCookies(conn)

        if (code in 200..299) {
            if (text.isBlank()) return null
            val obj = runCatching { JSONObject(text) }.getOrElse {
                throw ApiException("Unexpected response from server")
            }
            return if (obj.isNull("message")) null else obj.opt("message")
        }
        if (code == 401 || code == 403) {
            throw ApiException("Session expired — please sign in again.", needsLogin = true)
        }
        throw ApiException(extractError(text) ?: "Request failed ($code)")
    }

    fun callObject(method: String, params: Map<String, String?> = emptyMap()): JSONObject? =
        call(method, params) as? JSONObject

    fun callArray(method: String, params: Map<String, String?> = emptyMap()): JSONArray? =
        call(method, params) as? JSONArray

    // ---- internals --------------------------------------------------------

    private fun open(path: String): HttpURLConnection {
        val base = Prefs.baseUrl
        if (base.isEmpty()) throw ApiException("No site configured", needsLogin = true)
        val conn = URL(base + path).openConnection() as HttpURLConnection
        conn.connectTimeout = 15_000
        conn.readTimeout = 25_000
        conn.instanceFollowRedirects = false
        conn.setRequestProperty("Accept", "application/json")
        conn.setRequestProperty("X-Frappe-CSRF-Token", "None")
        val cookie = Prefs.cookie
        if (cookie.isNotEmpty()) conn.setRequestProperty("Cookie", cookie)
        return conn
    }

    private fun readBody(conn: HttpURLConnection): String {
        val stream = try {
            conn.inputStream
        } catch (e: Exception) {
            conn.errorStream
        } ?: return ""
        return stream.bufferedReader().use(BufferedReader::readText)
    }

    private fun storeCookies(conn: HttpURLConnection) {
        val headers = conn.headerFields ?: return
        val setCookie = headers.entries
            .firstOrNull { it.key != null && it.key.equals("Set-Cookie", ignoreCase = true) }
            ?.value ?: return

        val jar = LinkedHashMap<String, String>()
        Prefs.cookie.split(";").forEach { part ->
            val t = part.trim()
            val eq = t.indexOf('=')
            if (eq > 0) jar[t.substring(0, eq)] = t.substring(eq + 1)
        }
        for (raw in setCookie) {
            val first = raw.substringBefore(";").trim()
            val eq = first.indexOf('=')
            if (eq <= 0) continue
            val name = first.substring(0, eq)
            val value = first.substring(eq + 1)
            if (value.isEmpty() || value == "\"\"" || value.equals("deleted", true)) {
                jar.remove(name)
            } else {
                jar[name] = value
            }
        }
        Prefs.cookie = jar.entries.joinToString("; ") { "${it.key}=${it.value}" }
    }

    private fun extractError(text: String): String? {
        return try {
            val obj = JSONObject(text)
            val serverMessages = obj.optString("_server_messages")
            if (serverMessages.isNotBlank()) {
                val arr = JSONArray(serverMessages)
                val parts = ArrayList<String>()
                for (i in 0 until arr.length()) {
                    val rawItem = arr.getString(i)
                    val msg = runCatching { JSONObject(rawItem).getString("message") }
                        .getOrDefault(rawItem)
                    parts.add(stripHtml(msg))
                }
                return parts.joinToString("\n").trim().ifBlank { null }
            }
            val exception = obj.optString("exception")
            if (exception.isNotBlank()) return stripHtml(exception)
            obj.optString("message").ifBlank { null }?.let { stripHtml(it) }
        } catch (e: Exception) {
            null
        }
    }

    private fun stripHtml(s: String) = s.replace(Regex("<[^>]*>"), "").trim()

    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")
}
