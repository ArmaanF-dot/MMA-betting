"""Polite HTTP client for live sources: raw-HTML cache, rate limit, robots.txt check.

It stops, rather than works around, any bot challenge: if a response looks like a
"checking your browser" interstitial it raises BlockedError.
"""
import hashlib
import time
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlsplit

import httpx

CHALLENGE_MARKERS = ("Checking your browser", "This site requires JavaScript", "cf-chl", "/__c")


class BlockedError(RuntimeError):
    pass


def looks_like_challenge(html: str) -> bool:
    head = html[:6000]
    return any(m in head for m in CHALLENGE_MARKERS)


class Fetcher:
    def __init__(self, cache_dir: str | Path, user_agent: str, min_delay_sec: float = 3.0):
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(headers={"User-Agent": user_agent}, timeout=30, follow_redirects=True)
        self.user_agent = user_agent
        self.min_delay = min_delay_sec
        self._last = 0.0
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            r = self.client.get(base + "/robots.txt")
            if r.status_code == 200 and "<html" not in r.text[:200].lower():
                rp = robotparser.RobotFileParser()
                rp.parse(r.text.splitlines())
                self._robots[base] = rp
            else:
                self._robots[base] = None  # no robots.txt published
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(self.user_agent, url)

    def get(self, url: str) -> str:
        path = self.cache / (hashlib.sha256(url.encode()).hexdigest() + ".html")
        if path.exists():
            return path.read_text(encoding="utf-8")
        if not self._allowed(url):
            raise PermissionError(f"robots.txt disallows {url}")
        wait = self.min_delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        r = self.client.get(url)
        self._last = time.monotonic()
        r.raise_for_status()
        if looks_like_challenge(r.text):
            raise BlockedError(f"{url} returned a bot-check page; not bypassing it")
        path.write_text(r.text, encoding="utf-8")
        return r.text
