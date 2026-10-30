"""Polite-scraping helpers: robots.txt check, per-host throttle, URL safety.

Nothing here talks to a site unless asked to. `robots_allowed()` fetches a host's /robots.txt once
(cached 24h) with the same descriptive User-Agent as the scraper.
"""
import ipaddress
import logging
import socket
import threading
import time
import urllib.robotparser
from urllib.parse import urlparse

import httpx

log = logging.getLogger("pricewatch.polite")

ROBOTS_TTL = 24 * 3600        # cache a successful robots.txt for a day
ROBOTS_RETRY = 5 * 60         # re-check an unreachable robots.txt after 5 minutes
_robots: dict[str, tuple[float, urllib.robotparser.RobotFileParser | None]] = {}
_lock = threading.Lock()


def is_internal(url: str) -> bool:
    """Relative '/path' URLs are served in-process by the embedded demo store (DEMO_MODE)."""
    return url.startswith("/") and not url.startswith("//")


def robots_allowed_from_text(text: str, ua: str, url: str) -> bool:
    """Pure helper (easy to test): may `ua` fetch `url` according to this robots.txt body?"""
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(text.splitlines())
    return rp.can_fetch(ua, url)


def robots_allowed(url: str, ua: str, timeout: float = 10.0) -> bool:
    """True if robots.txt permits `ua` to fetch `url`.

    Follows RFC 9309: no robots.txt (4xx) = allowed; 5xx or network error = treated as
    disallowed for now and retried in a few minutes.
    """
    if is_internal(url):
        return True
    p = urlparse(url)
    origin = f"{p.scheme}://{p.netloc}"
    with _lock:
        hit = _robots.get(origin)
        if hit and hit[0] > time.time():
            rp = hit[1]
            return rp.can_fetch(ua, url) if rp else False
    rp, ttl = None, ROBOTS_RETRY
    try:
        r = httpx.get(origin + "/robots.txt", headers={"User-Agent": ua}, timeout=timeout, follow_redirects=True)
        if r.status_code < 400:
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(r.text.splitlines())
            ttl = ROBOTS_TTL
        elif r.status_code < 500:                # no robots.txt: everything allowed
            rp = urllib.robotparser.RobotFileParser()
            rp.parse([])
            ttl = ROBOTS_TTL
        else:
            log.warning("robots.txt on %s returned %s; skipping this host for now", origin, r.status_code)
    except httpx.HTTPError as e:
        log.warning("robots.txt on %s unreachable (%s); skipping this host for now", origin, e)
    with _lock:
        _robots[origin] = (time.time() + ttl, rp)
    return rp.can_fetch(ua, url) if rp else False


class HostThrottle:
    """Guarantee at least `delay` seconds between two requests to the same host."""

    def __init__(self):
        self._last: dict[str, float] = {}

    def wait(self, url: str, delay: float) -> None:
        if is_internal(url) or delay <= 0:
            return
        host = urlparse(url).netloc
        gap = self._last.get(host, 0) + delay - time.monotonic()
        if gap > 0:
            time.sleep(gap)
        self._last[host] = time.monotonic()


throttle = HostThrottle()


def url_problem(url: str, allow_private: bool = False) -> str | None:
    """Return a human-readable reason if `url` is not safe to fetch, else None (SSRF guard)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return "URL must start with http:// or https://"
    if allow_private:
        return None
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return f"cannot resolve host {p.hostname!r}"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return "URL points to a private or local address"
    return None
