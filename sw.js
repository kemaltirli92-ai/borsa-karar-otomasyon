/* =====================================================================
 * BLOK 20: XK100 Borsa PWA Service Worker
 * ---------------------------------------------------------------------
 * Kurallar:
 *  - Statik kabuk (index.html, logo, favicon, manifest): CACHE-FIRST
 *  - API istekleri (/api/...): NETWORK-FIRST; ag basarisizsa cache
 *    (stale-while-revalidate benzeri geri donus)
 *  - Cache'e yazilan HER API yanitina "x-cached-at" damgasi eklenir
 *  - Eski onbellek sunulurken istemciye B20_STALE_SERVED mesaji gonderilir;
 *    istemci "CEVRIMDISI VERI — SON GUNCELLEME: {tarih}" bandi gosterir.
 *    ESKI ONBELLEK CANLI VERI GIBI SUNULMAZ.
 * ===================================================================== */
(function () {
  "use strict";

  var SW_VERSION = "1.0.0";
  var SHELL_CACHE = "xk100-shell-v1";
  var API_CACHE = "xk100-api-v1";

  /* Statik kabuk: uygulama iskeleti — cache-first */
  var SHELL_ASSETS = [
    "index.html",
    "logo-aiborsam2.png",
    "favicon-xk100.png",
    "manifest.webmanifest"
  ];

  function isApiRequest(url) {
    return url.pathname.indexOf("/api/") === 0;
  }

  function isShellAsset(url) {
    if (url.origin !== self.location.origin) return false;
    var path = url.pathname;
    if (path === "/" || path === "" || path.endsWith("/")) return true;
    for (var i = 0; i < SHELL_ASSETS.length; i++) {
      if (path.endsWith("/" + SHELL_ASSETS[i]) || path === "/" + SHELL_ASSETS[i]) return true;
    }
    return false;
  }

  /* API yanitina x-cached-at damgasi basarak cache'e yazar.
   * Damga, yanitin cache'e yazildigi ANI gosterir (ISO-8601). */
  function stampAndCache(request, response) {
    var cachedAt = new Date().toISOString();
    return response.clone().blob().then(function (body) {
      var headers = new Headers(response.headers);
      headers.set("x-cached-at", cachedAt);
      var stamped = new Response(body, {
        status: response.status,
        statusText: response.statusText,
        headers: headers
      });
      return caches.open(API_CACHE).then(function (cache) {
        return cache.put(request, stamped);
      });
    });
  }

  function notifyClient(clientId, message) {
    if (!clientId) return;
    self.clients.get(clientId).then(function (client) {
      if (client) client.postMessage(message);
    });
  }

  /* API: network-first. Basarili canli yanit -> damgala + cache'e yaz.
   * Ag hatasi -> cache geri donusu + istemciye ACIK "eski veri" bildirimi. */
  function networkFirstApi(event) {
    var request = event.request;
    return fetch(request).then(function (response) {
      if (response && response.ok) {
        return stampAndCache(request, response).then(function () {
          notifyClient(event.clientId, { type: "B20_LIVE", url: request.url });
          return response;
        });
      }
      return response;
    }).catch(function () {
      return caches.open(API_CACHE).then(function (cache) {
        return cache.match(request).then(function (cached) {
          if (cached) {
            var cachedAt = cached.headers.get("x-cached-at") || "";
            notifyClient(event.clientId, {
              type: "B20_STALE_SERVED",
              url: request.url,
              cachedAt: cachedAt
            });
            return cached;
          }
          /* cache de yok: sahte veri URETILMEZ — hata oldugu gibi iletilir */
          return new Response(
            JSON.stringify({ error: "OFFLINE_NO_CACHE", error_id: "sw-" + Date.now() }),
            { status: 503, headers: { "Content-Type": "application/json" } }
          );
        });
      });
    });
  }

  /* Statik kabuk: cache-first. Cache yoksa ag + cache'e yaz. */
  function cacheFirstShell(event) {
    var request = event.request;
    return caches.open(SHELL_CACHE).then(function (cache) {
      return cache.match(request, { ignoreSearch: true }).then(function (hit) {
        if (hit) return hit;
        return fetch(request).then(function (response) {
          if (response && response.ok) cache.put(request, response.clone());
          return response;
        });
      });
    });
  }

  self.addEventListener("install", function (event) {
    event.waitUntil(
      caches.open(SHELL_CACHE).then(function (cache) {
        return cache.addAll(SHELL_ASSETS);
      }).then(function () {
        return self.skipWaiting();
      })
    );
  });

  self.addEventListener("activate", function (event) {
    event.waitUntil(
      caches.keys().then(function (keys) {
        return Promise.all(keys.map(function (key) {
          if (key !== SHELL_CACHE && key !== API_CACHE) return caches.delete(key);
          return null;
        }));
      }).then(function () {
        return self.clients.claim();
      })
    );
  });

  self.addEventListener("fetch", function (event) {
    var request = event.request;
    if (request.method !== "GET") return; /* GET disi dogrudan aga */
    var url = new URL(request.url);
    if (isApiRequest(url)) {
      event.respondWith(networkFirstApi(event));
      return;
    }
    if (isShellAsset(url)) {
      event.respondWith(cacheFirstShell(event));
    }
  });
})();
