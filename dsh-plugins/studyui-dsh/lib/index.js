import { createReadStream, readFileSync, statSync } from 'node:fs';
import { request as httpRequest } from 'node:http';
import { connect } from 'node:net';
import { extname, join, resolve, sep } from 'node:path';

const TITLE = 'StudyUI';
const MANIFEST_PATH = '/studyui/manifest.webmanifest';
const FAVICON_PATH = '/studyui/favicon.svg';
const CANVAS_PREFIX = '/studyui/canvas';
const CANVAS_API_PREFIX = '/studyui/canvas/api';
const CANVAS_ROOT_API_PREFIX = '/studyui/api/v1';
const API_PREFIX = '/studyui/api';
const WS_PREFIX = '/studyui/ws';
const HEALTH_ROUTES = [
  { path: '/studyui/canvas/health', target: '/canvas/health' },
  { path: '/studyui/canvas/health_check', target: '/canvas/health_check' },
  { path: '/studyui/health', target: '/canvas/health' },
  { path: '/studyui/health_check', target: '/canvas/health_check' },
];
const BACKEND = process.env.STUDYUI_BACKEND_URL || 'http://127.0.0.1:7881';
const CANVAS_DIR = process.env.STUDYUI_CANVAS_DIR || '';

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.map': 'application/json; charset=utf-8',
};

function asset(name) {
  return readFileSync(new URL(`../assets/${name}`, import.meta.url));
}

function admit(ctx, req, res) {
  const admission = ctx.connection.admit(req);
  if ('rejection' in admission) {
    res.writeHead(admission.rejection);
    res.end(admission.rejection === 401 ? 'unauthorized' : 'forbidden');
    return false;
  }
  return true;
}

/** Rewrite the host-generated index so the tab, PWA manifest and icons are StudyUI's. */
export function rewriteIndex(html) {
  return html
    .replace(/<title>.*?<\/title>/i, `<title>${TITLE}</title>`)
    .replace(
      /apple-mobile-web-app-title"\s+content="[^"]*"/i,
      `apple-mobile-web-app-title" content="${TITLE}"`,
    )
    .replace(/<link rel="manifest" href="[^"]*"[^>]*>/i, `<link rel="manifest" href="${MANIFEST_PATH}" />`)
    .replace(/<link rel="icon"[^>]*>/gi, `<link rel="icon" type="image/svg+xml" href="${FAVICON_PATH}" />`)
    .replace(
      /<link rel="apple-touch-icon"[^>]*>/gi,
      `<link rel="apple-touch-icon" href="${FAVICON_PATH}" />`,
    );
}

const API_REWRITE = `<script id="studyui-api-rewrite">
(() => {
  const rewrite = (value) => {
    if (typeof value !== "string") return value;
    if (value.startsWith("/canvas/api/")) return "/studyui" + value;
    if (value.startsWith("/api/")) return "/studyui" + value;
    if (value.startsWith("/health")) return "/studyui" + value;
    if (value.startsWith("/ws")) return "/studyui" + value;
    return value;
  };
  const rewriteValue = (value) => {
    if (typeof value !== "string") return value;
    const direct = rewrite(value);
    if (direct !== value) return direct;
    try {
      const url = new URL(value, location.href);
      if (url.origin !== location.origin) return value;
      const next = rewrite(url.pathname + url.search);
      return next === url.pathname + url.search ? value : next + url.hash;
    } catch (_) {
      return value;
    }
  };
  const fetchOriginal = window.fetch;
  if (fetchOriginal) {
    window.fetch = (input, init) => {
      if (typeof input === "string") input = rewriteValue(input);
      else if (input instanceof Request) {
        const url = new URL(input.url, location.href);
        const next = rewrite(url.pathname + url.search);
        if (next !== url.pathname + url.search) input = new Request(new URL(next, location.href), input);
      }
      return fetchOriginal(input, init);
    };
  }
  const openOriginal = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    return openOriginal.call(this, method, rewriteValue(url), ...rest);
  };
  const EventSourceOriginal = window.EventSource;
  if (EventSourceOriginal) {
    window.EventSource = function (url, config) {
      return new EventSourceOriginal(rewriteValue(url), config);
    };
    window.EventSource.prototype = EventSourceOriginal.prototype;
  }
  const WebSocketOriginal = window.WebSocket;
  if (WebSocketOriginal) {
    window.WebSocket = new Proxy(WebSocketOriginal, {
      construct(target, args) {
        const url = new URL(args[0], location.href);
        if (url.pathname.startsWith("/ws")) url.pathname = "/studyui" + url.pathname;
        args[0] = url.toString();
        return new target(...args);
      },
    });
  }
  const syncRoute = () => {
    document.documentElement.dataset.studyuiRoute = location.pathname;
  };
  syncRoute();
  const pushOriginal = history.pushState;
  history.pushState = function (...args) {
    const result = pushOriginal.apply(this, args);
    syncRoute();
    return result;
  };
  const replaceOriginal = history.replaceState;
  history.replaceState = function (...args) {
    const result = replaceOriginal.apply(this, args);
    syncRoute();
    return result;
  };
  window.addEventListener("popstate", syncRoute);
  const hideVendorChrome = () => {
    for (const element of document.querySelectorAll("button, [role='button']")) {
      const label = (element.textContent || "").trim();
      if (label === "Playground" || label === "Share") element.style.display = "none";
    }
    const notices = [
      "Error while updating the Component",
      "Flow needs review",
      "component needs updates",
      "Update required",
      "此组件不支持动态更新",
    ];
    for (const element of document.querySelectorAll("div")) {
      const text = element.textContent || "";
      if (!notices.some((notice) => text.includes(notice))) continue;
      const rect = element.getBoundingClientRect();
      if (rect.width > 0 && rect.width < 800 && rect.height > 0 && rect.height < 200) {
        element.style.display = "none";
      }
    }
  };
  setInterval(hideVendorChrome, 1500);
})();
</script>`;

const CANVAS_SKIN = `<style id="studyui-canvas-skin">
/* Match the DSH light theme and drop the vendor project chrome. */
#body:not(.dark) {
  --background: 0 0% 100% !important;
  --foreground: 220 17% 7% !important;
  --card: 0 0% 100% !important;
  --card-foreground: 220 17% 7% !important;
  --popover: 0 0% 100% !important;
  --popover-foreground: 220 17% 7% !important;
  --muted: 210 20% 98% !important;
  --muted-foreground: 210 5% 40% !important;
  --border: 220 13% 91% !important;
  --input: 220 13% 91% !important;
  --canvas: 0 0% 100% !important;
  --canvas-dot: 220 9% 84% !important;
}
#body:not(.dark),
#body:not(.dark) #root {
  background: #ffffff !important;
  color: #0f1115 !important;
}
#body.dark,
#body.dark #root {
  background: #151517 !important;
  color: #f9fafb !important;
}
/* The DSH shell replaces the vendor header; the project sidebar is only
   removed on the workflow-management page so the editor keeps its palette. */
header[class*="h-[48px]"] {
  display: none !important;
}
html[data-studyui-route^="/studyui/canvas/flows"] div[class*="sidebar-wrapper"] > aside.group {
  display: none !important;
}
html[data-studyui-route^="/studyui/canvas/flows"] div[class*="sidebar-wrapper"] {
  width: 100% !important;
}
/* The DSH toolbar owns Run; hide the bridge's floating bar and status panel. */
#studyui-canvas-bar,
#studyui-agent-run-status {
  display: none !important;
}
body,
#root {
  font-family: system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif !important;
}
#body.dark {
  --background: 240 5% 9% !important;
  --foreground: 210 20% 98% !important;
  --card: 240 5% 12% !important;
  --card-foreground: 210 20% 98% !important;
  --popover: 240 5% 12% !important;
  --muted: 240 5% 15% !important;
  --muted-foreground: 215 7% 70% !important;
  --border: 240 5% 18% !important;
  --input: 240 5% 18% !important;
  --canvas: 240 5% 9% !important;
  --canvas-dot: 240 5% 24% !important;
}
</style>`;

const CANVAS_LOADING = `<div id="studyui-canvas-loading" role="status" aria-live="polite">
  <div class="studyui-loading-brand"><span class="studyui-loading-mark">S</span><span class="studyui-loading-name">StudyUI</span></div>
  <div class="studyui-loading-status">正在加载工作流…</div>
  <div class="studyui-loading-spinner" aria-hidden="true"></div>
</div>
<style>
  #studyui-canvas-loading {
    position: fixed; inset: 0; z-index: 2147483646;
    display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px;
    background: #ffffff; color: #0f1115;
    font-family: system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    transition: opacity .18s ease; opacity: 1;
  }
  #studyui-canvas-loading .studyui-loading-brand { display: flex; align-items: center; gap: 8px; }
  #studyui-canvas-loading .studyui-loading-mark {
    display: inline-flex; align-items: center; justify-content: center;
    width: 28px; height: 28px; border-radius: 8px; background: #29476f; color: #fff;
    font: 700 17px Georgia, serif;
  }
  #studyui-canvas-loading .studyui-loading-name { font-size: 15px; font-weight: 600; }
  #studyui-canvas-loading .studyui-loading-status { font-size: 12.5px; color: #81858c; }
  #studyui-canvas-loading .studyui-loading-spinner {
    width: 20px; height: 20px; border-radius: 50%;
    border: 2px solid #e5e7eb; border-top-color: #29476f; animation: studyui-canvas-spin .8s linear infinite;
  }
  @keyframes studyui-canvas-spin { to { transform: rotate(360deg); } }
  @media (prefers-color-scheme: dark) {
    #studyui-canvas-loading { background: #151517; color: #f9fafb; }
    #studyui-canvas-loading .studyui-loading-status { color: #adb2b8; }
    #studyui-canvas-loading .studyui-loading-spinner { border-color: #2a2a2e; border-top-color: #6d8cff; }
  }
  #studyui-canvas-loading.dark { background: #151517; color: #f9fafb; }
  #studyui-canvas-loading.dark .studyui-loading-status { color: #adb2b8; }
  #studyui-canvas-loading.dark .studyui-loading-spinner { border-color: #2a2a2e; border-top-color: #6d8cff; }
</style>
<script id="studyui-canvas-loading-script">
(() => {
  const overlay = document.getElementById('studyui-canvas-loading');
  if (!overlay) return;
  const applyTheme = (dark) => {
    const body = document.getElementById('body') || document.body;
    body.classList.toggle('dark', !!dark);
    overlay.classList.toggle('dark', !!dark);
    try {
      localStorage.setItem('themePreference', dark ? 'dark' : 'light');
      localStorage.setItem('isDark', dark ? 'true' : 'false');
    } catch (_) {}
    document.documentElement.dataset.studyuiDark = dark ? '1' : '0';
    try {
      window.dispatchEvent(new CustomEvent('studyui-theme', { detail: { dark: !!dark } }));
    } catch (_) {}
  };
  window.addEventListener('message', (event) => {
    if (event.origin !== location.origin) return;
    const data = event.data;
    if (data && data.type === 'studyui-canvas-theme') applyTheme(data.dark);
  });
  let done = false;
  const finish = () => {
    if (done) return;
    if (!document.querySelector('.react-flow') && !document.querySelector('[class*="sidebar-wrapper"]')) return;
    done = true;
    overlay.style.opacity = '0';
    setTimeout(() => overlay.remove(), 200);
    try { window.parent.postMessage({ type: 'studyui-canvas-ready' }, location.origin); } catch (_) {}
  };
  new MutationObserver(finish).observe(document.documentElement, { childList: true, subtree: true });
  setInterval(finish, 250);
  setTimeout(() => {
    if (!done) {
      const status = overlay.querySelector('.studyui-loading-status');
      if (status) status.textContent = '还在加载…';
    }
  }, 10000);
  setTimeout(() => {
    if (done) return;
    done = true;
    overlay.style.opacity = '0';
    setTimeout(() => overlay.remove(), 200);
  }, 25000);
})();
</script>`;

function canvasIndex(html) {
  return html
    .replace(/<base[^>]*>/i, '<base href="/studyui/canvas/" />')
    .replace(/<head([^>]*)>/i, (match, attrs) => `<head${attrs}>${API_REWRITE}`)
    .replace(/<\/head>/i, `${CANVAS_SKIN}</head>`)
    .replace(/<body([^>]*)>/i, (match, attrs) => `<body${attrs}>${CANVAS_LOADING}`);
}

function contentType(path) {
  return MIME[extname(path).toLowerCase()] || 'application/octet-stream';
}

function serveCanvas(req, res, ctx) {
  if (!admit(ctx, req, res)) return;
  if (!CANVAS_DIR) {
    res.writeHead(503, { 'content-type': 'text/plain; charset=utf-8' });
    res.end('StudyUI canvas directory is not configured');
    return;
  }
  const url = new URL(req.url || '/', 'http://127.0.0.1');
  let relative = decodeURIComponent(url.pathname.slice(CANVAS_PREFIX.length));
  if (!relative || relative === '/') relative = '/index.html';
  const root = resolve(CANVAS_DIR);
  let file = resolve(join(root, relative));
  if (file !== root && !file.startsWith(root + sep)) {
    res.writeHead(403);
    res.end('forbidden');
    return;
  }
  let index = relative === '/index.html';
  try {
    if (!statSync(file).isFile()) throw new Error('not a file');
  } catch {
    if (extname(relative)) {
      res.writeHead(404);
      res.end('not found');
      return;
    }
    file = join(root, 'index.html');
    index = true;
  }
  if (index) {
    res.writeHead(200, {
      'content-type': MIME['.html'],
      'cache-control': 'no-cache',
    });
    res.end(canvasIndex(readFileSync(file, 'utf8')));
    return;
  }
  const size = statSync(file).size;
  res.writeHead(200, {
    'content-type': contentType(file),
    'content-length': size,
    'cache-control': 'public, max-age=3600',
  });
  if (req.method === 'HEAD') {
    res.end();
    return;
  }
  createReadStream(file).pipe(res);
}

function proxy(req, res, ctx, sourcePrefix, targetPrefix) {
  if (!admit(ctx, req, res)) return;
  const url = new URL(req.url || '/', 'http://127.0.0.1');
  const targetPath = targetPrefix + url.pathname.slice(sourcePrefix.length) + url.search;
  const backend = new URL(BACKEND);
  const headers = { ...req.headers, host: backend.host };
  delete headers.cookie;
  delete headers.authorization;
  // The sidecar enforces same-Origin equality; the DSH port differs from the
  // sidecar port, so let the trusted loopback proxy speak for itself.
  delete headers.origin;
  delete headers.referer;
  const upstream = httpRequest(
    {
      hostname: backend.hostname,
      port: backend.port || 80,
      method: req.method,
      path: targetPath,
      headers,
    },
    (upstreamResponse) => {
      res.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers);
      upstreamResponse.pipe(res);
    },
  );
  upstream.on('error', (error) => {
    if (!res.headersSent) {
      res.writeHead(502, { 'content-type': 'text/plain; charset=utf-8' });
    }
    res.end(`StudyUI backend error: ${error.message}`);
  });
  req.pipe(upstream);
}

function proxyUpgrade(ctx, req, socket, head) {
  const rejection = ctx.connection.requestRejection(req);
  if (rejection !== undefined) {
    const reason = rejection === 401 ? 'Unauthorized' : 'Forbidden';
    socket.end(`HTTP/1.1 ${rejection} ${reason}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`);
    return;
  }
  const backend = new URL(BACKEND);
  const url = new URL(req.url || '/', 'http://127.0.0.1');
  const targetPath = '/ws' + url.search;
  const upstream = connect(Number(backend.port || 80), backend.hostname);
  const dispose = () => {
    socket.destroy();
    upstream.destroy();
  };
  upstream.once('connect', () => {
    upstream.write(
      `GET ${targetPath} HTTP/1.1\r\nHost: ${backend.host}\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n`,
    );
    for (const [key, value] of Object.entries(req.headers)) {
      if (key.startsWith('sec-websocket-') && value !== undefined) {
        upstream.write(`${key}: ${Array.isArray(value) ? value.join(', ') : value}\r\n`);
      }
    }
    upstream.write('\r\n');
    if (head.length > 0) upstream.write(head);
    socket.pipe(upstream).pipe(socket);
  });
  upstream.on('error', dispose);
  socket.on('error', dispose);
}

export const inject = ['webServer', 'connection'];

export function apply(ctx) {
  ctx.effect(() => ctx.webServer.tapIndex(rewriteIndex), 'studyui-brand: index');
  const routes = [
    {
      path: MANIFEST_PATH,
      body: asset('manifest.webmanifest'),
      type: 'application/manifest+json; charset=utf-8',
    },
    { path: FAVICON_PATH, body: asset('favicon.svg'), type: 'image/svg+xml' },
  ];
  for (const route of routes) {
    ctx.effect(
      () =>
        ctx.webServer.register({
          kind: 'exact',
          path: route.path,
          handler: (req, res) => {
            if (!admit(ctx, req, res)) return;
            res.writeHead(200, { 'content-type': route.type, 'cache-control': 'no-cache' });
            res.end(route.body);
          },
        }),
      `studyui-brand: ${route.path}`,
    );
  }
  ctx.effect(
    () =>
      ctx.webServer.register({
        kind: 'prefix',
        path: CANVAS_API_PREFIX,
        handler: (req, res) => proxy(req, res, ctx, CANVAS_API_PREFIX, '/canvas/api'),
      }),
    'studyui-canvas: canvas api proxy',
  );
  // The canvas SPA also calls absolute /api/v1 paths; the workflow router is
  // mounted under the canvas app, so map those to /canvas/api/v1.
  ctx.effect(
    () =>
      ctx.webServer.register({
        kind: 'prefix',
        path: CANVAS_ROOT_API_PREFIX,
        handler: (req, res) => proxy(req, res, ctx, CANVAS_ROOT_API_PREFIX, '/canvas/api/v1'),
      }),
    'studyui-canvas: canvas root api proxy',
  );
  ctx.effect(
    () =>
      ctx.webServer.register({
        kind: 'prefix',
        path: API_PREFIX,
        handler: (req, res) => proxy(req, res, ctx, API_PREFIX, '/api'),
      }),
    'studyui-canvas: api proxy',
  );
  for (const route of HEALTH_ROUTES) {
    ctx.effect(
      () =>
        ctx.webServer.register({
          kind: 'exact',
          path: route.path,
          handler: (req, res) => proxy(req, res, ctx, route.path, route.target),
        }),
      `studyui-canvas: health ${route.path}`,
    );
  }
  ctx.effect(
    () =>
      ctx.webServer.registerUpgrade({
        path: WS_PREFIX,
        handler: (req, socket, head) => proxyUpgrade(ctx, req, socket, head),
      }),
    'studyui-canvas: websocket proxy',
  );
  ctx.effect(
    () =>
      ctx.webServer.register({
        kind: 'prefix',
        path: CANVAS_PREFIX,
        handler: (req, res) => serveCanvas(req, res, ctx),
      }),
    'studyui-canvas: static and spa',
  );
}
