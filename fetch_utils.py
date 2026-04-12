"""
fetch_utils.py — Shared HTTP fetch utilities for robots.txt and sitemap retrieval.

Two-layer design:
  fetch_url()    — generic URL fetcher (used by sitemap_intensity.py for sitemaps)
  fetch_robots() — robots.txt-specific wrapper (used by scan_robots.py and sitemap_intensity.py)

Rule: robots.txt uses fetch_robots(). Sitemaps use fetch_url(..., as_bytes=True). Never mix.
"""

import requests

# ---------------------------------------------------------------------------
# User-Agent strings
# ---------------------------------------------------------------------------

UA_RESEARCH = "Mozilla/5.0 (compatible; AcademicResearchBot/1.0)"
UA_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Maximum robots.txt content to read (1 MB)
MAX_CONTENT_BYTES = 1_000_000


# ---------------------------------------------------------------------------
# Generic URL fetcher
# ---------------------------------------------------------------------------

def fetch_url(url, timeout=30, as_bytes=False, ua=UA_RESEARCH):
    """Fetch any URL. Returns bytes or text depending on as_bytes.

    Retries once with UA_BROWSER if the first attempt returns 403.
    No robots.txt-specific logic (no SSL fallback, no HTTP fallback).

    Args:
        url: Full URL to fetch.
        timeout: Request timeout in seconds.
        as_bytes: If True, return raw response bytes; else return decoded text.
        ua: User-Agent string for the first attempt.

    Returns:
        dict with keys:
            status_code: int or None
            content: str (if as_bytes=False) or bytes (if as_bytes=True), may be empty
            final_url: str (URL after redirects)
            fetch_error: str (empty string on success)
    """
    for attempt_ua in [ua, UA_BROWSER]:
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": attempt_ua},
                timeout=timeout,
                allow_redirects=True,
            )
            if resp.status_code == 403 and attempt_ua == ua:
                continue  # retry with browser UA

            if as_bytes:
                content = resp.content if resp.status_code == 200 else b""
            else:
                content = resp.text if resp.status_code == 200 else ""

            return {
                "status_code": resp.status_code,
                "content": content,
                "final_url": resp.url,
                "fetch_error": "",
            }

        except requests.exceptions.Timeout:
            if attempt_ua == ua:
                continue
            return {
                "status_code": None,
                "content": b"" if as_bytes else "",
                "final_url": url,
                "fetch_error": "timeout",
            }
        except requests.exceptions.TooManyRedirects:
            return {
                "status_code": None,
                "content": b"" if as_bytes else "",
                "final_url": url,
                "fetch_error": "too_many_redirects",
            }
        except requests.exceptions.RequestException as e:
            if attempt_ua == ua:
                continue
            return {
                "status_code": None,
                "content": b"" if as_bytes else "",
                "final_url": url,
                "fetch_error": str(type(e).__name__),
            }

    # All attempts exhausted
    return {
        "status_code": None,
        "content": b"" if as_bytes else "",
        "final_url": url,
        "fetch_error": "all_attempts_failed",
    }


# ---------------------------------------------------------------------------
# robots.txt fetcher
# ---------------------------------------------------------------------------

def fetch_robots(host, timeout=15):
    """Fetch robots.txt from a host.

    Logic:
    - Try HTTPS first with research UA; retry with browser UA on 403.
    - SSL error only: fall back to HTTP (connection errors and timeouts do not
      trigger HTTP fallback — they are not HTTPS-specific issues).

    Args:
        host: Hostname (e.g., "www.example.com"). No scheme or path.
        timeout: Request timeout in seconds.

    Returns:
        dict with keys:
            status_code: int or None
            content: str (robots.txt text, or "" on error)
            final_url: str
            fetch_error: str (empty on success)
            ua_used: str ("research" | "browser" | "")
            http_fallback: bool
    """
    https_url = f"https://{host}/robots.txt"
    http_url = f"http://{host}/robots.txt"
    https_failed_reason = None

    # --- HTTPS attempt ---
    for ua, ua_label in [(UA_RESEARCH, "research"), (UA_BROWSER, "browser")]:
        try:
            resp = requests.get(
                https_url,
                headers={"User-Agent": ua},
                timeout=timeout,
                allow_redirects=True,
            )
            if resp.status_code == 403 and ua_label == "research":
                continue  # retry with browser UA

            content = resp.text[:MAX_CONTENT_BYTES] if resp.status_code == 200 else ""
            return {
                "status_code": resp.status_code,
                "content": content,
                "final_url": resp.url,
                "fetch_error": "",
                "ua_used": ua_label,
                "http_fallback": False,
            }
        except requests.exceptions.SSLError:
            https_failed_reason = "ssl_error"
            break
        except requests.exceptions.Timeout:
            if ua_label == "research":
                continue
            return {
                "status_code": None,
                "content": "",
                "final_url": https_url,
                "fetch_error": "timeout",
                "ua_used": ua_label,
                "http_fallback": False,
            }
        except requests.exceptions.TooManyRedirects:
            return {
                "status_code": None,
                "content": "",
                "final_url": https_url,
                "fetch_error": "too_many_redirects",
                "ua_used": ua_label,
                "http_fallback": False,
            }
        except requests.exceptions.ConnectionError:
            if ua_label == "research":
                continue
            return {
                "status_code": None,
                "content": "",
                "final_url": https_url,
                "fetch_error": "connection_error",
                "ua_used": ua_label,
                "http_fallback": False,
            }
        except requests.exceptions.RequestException as e:
            return {
                "status_code": None,
                "content": "",
                "final_url": https_url,
                "fetch_error": str(type(e).__name__),
                "ua_used": ua_label,
                "http_fallback": False,
            }

    # --- HTTP fallback (only after SSLError) ---
    if https_failed_reason == "ssl_error":
        for ua, ua_label in [(UA_RESEARCH, "research"), (UA_BROWSER, "browser")]:
            try:
                resp = requests.get(
                    http_url,
                    headers={"User-Agent": ua},
                    timeout=timeout,
                    allow_redirects=True,
                )
                if resp.status_code == 403 and ua_label == "research":
                    continue
                content = resp.text[:MAX_CONTENT_BYTES] if resp.status_code == 200 else ""
                return {
                    "status_code": resp.status_code,
                    "content": content,
                    "final_url": resp.url,
                    "fetch_error": "",
                    "ua_used": ua_label,
                    "http_fallback": True,
                }
            except requests.exceptions.Timeout:
                if ua_label == "research":
                    continue
                return {
                    "status_code": None,
                    "content": "",
                    "final_url": http_url,
                    "fetch_error": "timeout_after_ssl_fallback",
                    "ua_used": ua_label,
                    "http_fallback": True,
                }
            except requests.exceptions.RequestException as e:
                if ua_label == "research":
                    continue
                return {
                    "status_code": None,
                    "content": "",
                    "final_url": http_url,
                    "fetch_error": f"{type(e).__name__}_after_ssl_fallback",
                    "ua_used": ua_label,
                    "http_fallback": True,
                }

    return {
        "status_code": None,
        "content": "",
        "final_url": https_url,
        "fetch_error": https_failed_reason or "all_attempts_failed",
        "ua_used": "",
        "http_fallback": https_failed_reason == "ssl_error",
    }
