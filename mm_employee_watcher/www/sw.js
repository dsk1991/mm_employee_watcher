// MM Employee Watcher — minimal app-shell service worker for the mobile
// worker page (/mm_worker).
//
// This file is served from the site root (/sw.js) because a service worker
// can only be given a scope inside its own folder or deeper — root is the
// widest possible location. It is registered from mm_worker.html with an
// EXPLICIT `scope: "/mm_worker"`, so the browser only ever routes it
// requests for that one page. It never sees, and cannot affect, Desk, the
// wall dashboard, or anything else on the site.
//
// It caches only the worker page shell so it can still open on a dead
// connection (warehouse wifi, etc.) — every request is tried on the network
// first; the cache is purely a fallback, never preferred, so status/API
// calls are always live.

var CACHE = "mm-worker-shell-v1";
var SHELL = ["/mm_worker"];

self.addEventListener("install", function (event) {
	event.waitUntil(
		caches.open(CACHE).then(function (cache) {
			return cache.addAll(SHELL);
		})
	);
	self.skipWaiting();
});

self.addEventListener("activate", function (event) {
	event.waitUntil(
		caches.keys().then(function (keys) {
			return Promise.all(
				keys
					.filter(function (k) {
						return k !== CACHE;
					})
					.map(function (k) {
						return caches.delete(k);
					})
			);
		})
	);
	self.clients.claim();
});

self.addEventListener("fetch", function (event) {
	if (event.request.method !== "GET") return;
	event.respondWith(
		fetch(event.request).catch(function () {
			return caches.match(event.request).then(function (cached) {
				return cached || caches.match("/mm_worker");
			});
		})
	);
});
