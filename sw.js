/* Service Worker — 离线可访问 + 数据 network-first
 * ---------------------------------------------------------------------------
 * 与 index.html 的多端点 failover 互补：
 *   - 数据（data/*.json）：network-first，拿到最新即缓存；失败回退缓存。
 *     榜单站以"新鲜度"为第一优先，故不采用 stale-while-revalidate
 *     （那会让用户首屏看到上一次的数据）。断网时依然可读最近一次成功数据。
 *   - 页面（导航请求）：network-first，失败回退缓存，彻底消除"白屏"。
 *   - 其余同源 GET：cache-first + 后台更新。
 * 跨域请求（jsDelivr / GitHub raw）同样 network-first + 缓存兜底，
 * 使多端点 failover 在离线时也有一份可用的兜底副本。
 * 任一缓存写入失败都不影响响应，绝不因 SW 异常导致页面打不开。
 */
const VERSION = "amr-sw-v3";
const SHELL_CACHE = `${VERSION}-shell`;
const DATA_CACHE = `${VERSION}-data`;
const SHELL = ["./", "./index.html", "./404.html"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(SHELL_CACHE)
      .then((c) => Promise.allSettled(SHELL.map((u) => c.add(new Request(u, { cache: "reload" })))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

const isData = (url) => /\/data\/[^/]+\.json(\?|$)/.test(url.pathname + (url.search || ""));
const isCacheable = (res) => res && (res.ok || res.type === "opaque") && res.status !== 206;

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  let url;
  try { url = new URL(req.url); } catch (_) { return; }

  // 1) 数据文件：network-first（新鲜度优先）+ 缓存兜底
  if (isData(url)) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (isCacheable(res)) caches.open(DATA_CACHE).then((c) => c.put(req, res.clone()));
          return res;
        })
        .catch(() => caches.match(req).then((h) => h || Response.error()))
    );
    return;
  }

  // 2) 页面导航：network-first，回退缓存
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (isCacheable(res)) caches.open(SHELL_CACHE).then((c) => c.put(req, res.clone()));
          return res;
        })
        .catch(() => caches.match(req).then((h) => h || caches.match("./index.html")))
    );
    return;
  }

  // 3) 其余同源静态资源：cache-first + 后台更新
  if (url.origin === self.location.origin) {
    event.respondWith(
      caches.match(req).then((hit) => {
        const net = fetch(req)
          .then((res) => { if (isCacheable(res)) caches.open(SHELL_CACHE).then((c) => c.put(req, res.clone())); return res; })
          .catch(() => hit);
        return hit || net;
      })
    );
    return;
  }

  // 4) 跨域数据端点（CDN 容灾）：网络优先，失败回退缓存
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (isCacheable(res)) caches.open(DATA_CACHE).then((c) => c.put(req, res.clone()));
        return res;
      })
      .catch(() => caches.match(req).then((h) => h || Response.error()))
  );
});
