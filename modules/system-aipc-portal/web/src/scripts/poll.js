/**
 * Energy-friendly JSON poller:
 *  - pauses when the tab is hidden
 *  - sends If-None-Match (304 = no repaint)
 *  - uses setTimeout chain (not fixed setInterval pile-up)
 */

export function createJsonPoller({
  url,
  intervalMs = 8000,
  hiddenMultiplier = 4,
  onData,
  onError,
  onSoftSkip,
}) {
  let alive = true;
  let timer = 0;
  let etag = "";
  let inFlight = false;

  async function tick({ force = false } = {}) {
    if (!alive || inFlight) return;
    if (!force && document.visibilityState === "hidden") return;
    inFlight = true;
    try {
      const headers = {};
      if (etag && !force) headers["If-None-Match"] = etag;
      const res = await fetch(url, { headers, cache: "no-store" });
      if (res.status === 304) {
        onSoftSkip?.();
        return;
      }
      if (!res.ok) throw new Error(String(res.status));
      const next = res.headers.get("ETag") || "";
      if (next) etag = next;
      const data = await res.json();
      onData(data, { etag: next, forced: force });
    } catch (err) {
      onError?.(err);
    } finally {
      inFlight = false;
    }
  }

  function delayMs() {
    if (document.visibilityState === "hidden") {
      return Math.max(intervalMs * hiddenMultiplier, intervalMs);
    }
    return intervalMs;
  }

  function schedule() {
    if (!alive) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(async () => {
      await tick();
      schedule();
    }, delayMs());
  }

  function onVisibility() {
    if (!alive) return;
    if (document.visibilityState === "visible") {
      tick({ force: false });
      schedule();
    }
  }

  document.addEventListener("visibilitychange", onVisibility);
  tick({ force: true });
  schedule();

  return {
    stop() {
      alive = false;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    },
    refresh() {
      etag = "";
      return tick({ force: true });
    },
  };
}
