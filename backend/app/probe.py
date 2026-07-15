"""Live connectivity probe for the connection-status flag.

We can't read the OS VPN state (and a browser certainly can't), so we measure
the ground truth instead: can we resolve + open a TCP socket to the database
host right now? That reflects whichever machine the backend runs on.
See docs/VPN-STATUS-PLAN.md for the topology reasoning.
"""
import socket
import time

_cache = {"at": 0.0, "key": None, "result": None}


def classify(host: str, deploy_mode: str) -> str:
    """local-db (no VPN concept) | vpn-gated (backend-on-laptop) | in-vnet."""
    if (deploy_mode or "").lower() == "vnet":
        return "in-vnet"
    h = (host or "").lower()
    if h in ("localhost", "127.0.0.1", "::1") or h.startswith("127."):
        return "local-db"
    return "vpn-gated"


def probe(host: str, port: int, timeout: float = 3.0) -> dict:
    """DNS + TCP reachability, bounded to a TOTAL of `timeout` seconds across all
    resolved addresses. Distinguishes VPN-down / routing / connected."""
    started = time.perf_counter()
    try:
        infos = socket.getaddrinfo(host, int(port), type=socket.SOCK_STREAM)
    except socket.gaierror:
        return {
            "state": "disconnected", "dnsOk": False, "tcpOk": False, "latencyMs": None,
            "reason": "Host name doesn't resolve — the VPN is likely disconnected "
                      "(or private DNS isn't configured).",
        }
    deadline = time.monotonic() + timeout
    for family, socktype, proto, _canon, sockaddr in infos:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        s = socket.socket(family, socktype, proto)
        s.settimeout(min(remaining, timeout))
        try:
            s.connect(sockaddr)
            return {
                "state": "connected", "dnsOk": True, "tcpOk": True,
                "latencyMs": round((time.perf_counter() - started) * 1000, 1),
                "reason": "Database host is reachable.",
            }
        except OSError:
            continue
        finally:
            s.close()
    return {
        "state": "unreachable", "dnsOk": True, "tcpOk": False,
        "latencyMs": round((time.perf_counter() - started) * 1000, 1),
        "reason": "Host resolves but the port isn't reachable — check VPN routing "
                  "(split tunnel), the DB firewall/NSG, or that the database is up.",
    }


def probe_cached(host: str, port: int, ttl: float = 4.0) -> dict:
    """Cache the last probe briefly so rapid polls don't pile up sockets."""
    now = time.monotonic()
    key = f"{host}:{port}"
    if _cache["result"] and _cache["key"] == key and now - _cache["at"] < ttl:
        return _cache["result"]
    result = probe(host, port)
    _cache.update(at=now, key=key, result=result)
    return result
