# Plan: live "Azure VPN connected / disconnected" status flag

Goal: on the Config tab (and optionally a small global badge), show a **live,
auto-updating** indicator of whether the app can currently reach the Azure
VNet-private PostgreSQL — i.e. whether the corporate VPN path is up — refreshing
at runtime without a manual "Test" click.

## The key reframe (from research)

"Is the VPN connected?" is the wrong question to ask *directly* — you can't
answer it reliably. The **right** question is:

> **"Can we resolve + open a TCP connection to the private database host right now?"**

That reachability probe is the *ground truth* of what the user actually cares
about, and it sidesteps every fragile alternative:

| Approach | Verdict |
|---|---|
| Browser JS reads the OS VPN | ❌ Impossible — browsers are sandboxed. WebRTC only leaks IPs (privacy vector), not a corporate-tunnel signal. |
| Backend runs `Get-VpnConnection` (Windows) | ⚠️ Fragile — reports *native* Windows VPN profiles but **does not see the Azure VPN Client app** (Entra/OpenVPN P2S). OS/adapter-specific, not portable. |
| Backend resolves the private FQDN (DNS only) | ⚠️ Insufficient — "DNS can resolve while routing is missing" (split tunnel). Resolving ≠ reachable. |
| **Backend TCP-connects to `host:5432` with a timeout** | ✅ **Ground truth.** If the socket opens, the VPN path is up. If it doesn't, it isn't. |

So: **reachability probe = primary signal.** OS/browser VPN detection = do not
build (fragile and misleading).

## Topology changes the meaning — detect the mode

Where the backend runs determines *whose* connectivity the probe measures:

| Mode | Backend location | What the probe reflects | Card should say |
|---|---|---|---|
| **local-db** | local, `PGHOST=localhost` | nothing VPN-related | "Local database — VPN not required." |
| **vpn-gated** | local (on the user's machine), `PGHOST=*.postgres.database.azure.com` | **the user's machine's VPN** ✅ (exactly what they asked for) | live Connected / Disconnected |
| **in-vnet** | deployed in the VNet (ACA) | the *server's* path (always up) — NOT the user's VPN | "Backend is in-VNet; DB always reachable. (If you loaded this page you're already on the network.)" |

Pick the mode from the effective `PGHOST`:
`localhost`/`127.*`/private-RFC1918 → local-db; `*.postgres.database.azure.com`
(or any non-local host) → vpn-gated; a deploy-time env flag
(`DEPLOY_MODE=vnet`) forces in-vnet.

## Backend design

A lightweight, cached, non-blocking probe — **raw socket, not psycopg2** (we
want *network reachability*, not auth; a raw connect is faster and works even if
the password is wrong):

```python
# app/probe.py
import socket, time
_cache = {"at": 0.0, "result": None}

def probe(host: str, port: int, timeout: float = 3.0) -> dict:
    started = time.perf_counter()
    # 1) DNS
    try:
        socket.getaddrinfo(host, port)
        dns_ok = True
    except socket.gaierror:
        return {"state": "disconnected", "dnsOk": False, "tcpOk": False,
                "reason": "Host doesn't resolve — VPN likely down (or no private DNS).",
                "latencyMs": None}
    # 2) TCP connect (the real test)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
        tcp_ok = True
    except (socket.timeout, OSError):
        tcp_ok = False
    ms = round((time.perf_counter() - started) * 1000, 1)
    if tcp_ok:
        return {"state": "connected", "dnsOk": True, "tcpOk": True,
                "reason": "Database is reachable.", "latencyMs": ms}
    return {"state": "unreachable", "dnsOk": True, "tcpOk": False,
            "reason": "Host resolves but port 5432 isn't reachable — check VPN "
                      "routing (split tunnel), the DB firewall/NSG, or that the DB is up.",
            "latencyMs": ms}

def probe_cached(host, port, ttl=4.0):
    now = time.monotonic()
    if _cache["result"] and now - _cache["at"] < ttl and _cache["result"]["host"] == host:
        return _cache["result"]
    r = probe(host, port); r["host"] = host
    _cache.update(at=now, result=r)
    return r
```

Endpoint (uses the **saved** config host, never a client-supplied host, to avoid
SSRF surface):

```python
@app.get("/api/vpn-status")
def vpn_status():
    d = runtime.db_cfg()
    host, port = d["host"], int(d["port"])
    mode = classify(host)                 # local-db | vpn-gated | in-vnet
    if mode == "local-db":
        return {"mode": mode, "state": "n/a", "reason": "Local database — VPN not required."}
    r = probe_cached(host, port)
    return {"mode": mode, **r, "checkedAt": ...}
```

Notes:
- **Timeout 2–3 s** so a down VPN fails fast; **cache ~4 s** so rapid polls don't pile up.
- FastAPI runs sync endpoints in a threadpool → the blocking socket won't stall the server. (Or make it `async` with `asyncio.open_connection` + `wait_for`.)
- Distinguishes the three failure modes the user asked about: **DNS fail → VPN down**; **TCP fail after DNS ok → routing/firewall/DB-down**; **TCP ok → connected**.

## Frontend design

Poll the endpoint on an interval while the Config tab is open (and optionally a
small badge in the topbar). **Polling, not SSE/WebSocket** — a status flag doesn't
justify a persistent connection.

```tsx
function useVpnStatus(pollMs = 7000) {
  const [s, setS] = useState<VpnStatus|null>(null);
  useEffect(() => {
    let fails = 0, alive = true;
    const tick = async () => {
      try {
        const r = await api.vpnStatus();
        if (!alive) return;
        // debounce flapping: require 2 consecutive fails before showing "down"
        if (r.state === "connected" || r.state === "n/a") { fails = 0; setS(r); }
        else if (++fails >= 2) setS(r);
      } catch { if (++fails >= 2 && alive) setS({state:"disconnected", reason:"backend unreachable"}); }
    };
    tick(); const id = setInterval(tick, pollMs);
    return () => { alive = false; clearInterval(id); };
  }, [pollMs]);
  return s;
}
```

Pill states (replaces the static VPN note in the Connection card):
- 🟢 **Connected** — "Database reachable · 42 ms · checked 3 s ago"
- 🔴 **Disconnected** — "Host won't resolve — Azure VPN is likely disconnected."
- 🟡 **Unreachable** — "Resolves but port blocked — check VPN routing / firewall."
- ⚪ **Local / N-A** — "Local database — VPN not required."
- **in-vnet** mode → static informational note (probe always green; don't imply it's the user's VPN).

Debounce (2 consecutive failures) prevents a single transient blip from flipping
the flag to red.

## What NOT to build
- ❌ Browser-side VPN detection (WebRTC/timing) — unreliable and privacy-hostile.
- ❌ Relying on `Get-VpnConnection` as the source of truth — misses the Azure VPN Client app.
- ❌ DNS-only checks — resolving doesn't prove routing.

## Optional secondary signal (low priority)
In **local-backend + Windows** only, you *could* enrich with a best-effort
`Get-VpnConnection | Where ConnectionStatus -eq 'Connected'` to name the active
profile — but flag it "best-effort (won't detect the Azure VPN Client app)".
Not recommended for v1; the reachability probe already answers the real question.

## Effort
Small: ~1 backend file (`probe.py`) + 1 endpoint, ~1 frontend hook + pill in the
Config card. No new deps (stdlib `socket`). Half a day incl. tests. Verify by
running locally against a bad host (VPN-down simulation) — the same trick already
used for the `test-db` endpoint.

## Sources
- Azure Database for PostgreSQL — Private Link networking (DNS vs routing; split-tunnel pitfall): <https://learn.microsoft.com/en-us/azure/postgresql/network/concepts-networking-private-link>
- P2S VPN + Private Link DNS resolution (custom DNS / forwarder needed): <https://learn.microsoft.com/en-us/answers/questions/2028351/how-to-setup-point-to-site-vpn-to-got-access-to-az>
- `Get-VpnConnection` (Windows VpnClient module — native profiles only): <https://learn.microsoft.com/en-us/powershell/module/vpnclient/get-vpnconnection>
- Azure P2S client connection health (control-plane, needs Azure auth — not a client-side check): <https://learn.microsoft.com/en-us/powershell/module/az.network/get-azvirtualnetworkgatewayvpnclientconnectionhealth>
- Python TCP reachability with timeouts (`create_connection` / `connect_ex`): <https://buildsoftwaresystems.com/post/python-remote-tcp-port-reachability-check/>
- Always set socket timeouts in production: <https://oneuptime.com/blog/post/2026-03-20-socket-timeouts-ipv4-python/view>
- WebRTC IP leaks (why the browser can't cleanly detect a corporate VPN): <https://browserleaks.com/>
