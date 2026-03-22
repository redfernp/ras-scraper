"""
Racing & Sports scraper — core logic module.

Importable by app.py (Streamlit) or run directly as a CLI:
    python scraper.py https://www.racingandsports.com.au/form-guide/thoroughbred/hong-kong/sha-tin/2026-03-22
"""

import re
import sys
import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests as cf_requests
from firecrawl import Firecrawl
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Chrome UA used for both cookie-based and browser-based requests
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Tips extraction
# ---------------------------------------------------------------------------

TIPS_PATTERN = re.compile(r'(\d+)\s+([A-Z][A-Z\s]+?)\s*\((\d+)\s*pts\)')


def parse_tips(html: str) -> list[dict]:
    """
    Extract tips from page HTML.
    Sorted by points desc, then race card number asc (tie-break).
    """
    soup = BeautifulSoup(html, "html.parser")

    best_text = None
    best_count = 2
    for tag in soup.find_all(True):
        text = tag.get_text(" ", strip=True)
        count = len(TIPS_PATTERN.findall(text))
        if count > best_count:
            best_text = text
            best_count = count

    if not best_text:
        best_text = soup.get_text(" ", strip=True)

    tips = []
    seen = set()
    for m in TIPS_PATTERN.finditer(best_text):
        key = (int(m.group(1)), m.group(2).strip())
        if key not in seen:
            seen.add(key)
            tips.append({
                "number": int(m.group(1)),
                "name":   m.group(2).strip(),
                "points": int(m.group(3)),
            })

    tips.sort(key=lambda x: (-x["points"], x["number"]))
    return tips


# ---------------------------------------------------------------------------
# Selection logic
# ---------------------------------------------------------------------------

def select_horse(tips: list) -> tuple:
    """
    gap >= 4  →  select rank 1
    gap <  4  →  select rank 2
    Ties already resolved by sort (lowest race card # wins).
    Returns (selected_horse, gap).
    """
    if not tips:
        return None, 0
    if len(tips) == 1:
        return tips[0], 0

    rank1 = tips[0]
    rank2 = tips[1]
    gap   = rank1["points"] - rank2["points"]
    return (rank1 if gap >= 4 else rank2), gap


def assign_nap_nb(results: list) -> tuple:
    """
    Given results = [(race_num, selected_horse_or_None, gap), ...],
    return (nap_race_num, nb_race_num) based on largest gaps.
    """
    valid = [(r, sel, gap) for r, sel, gap in results if sel is not None]
    ranked = sorted(valid, key=lambda x: x[2], reverse=True)
    nap = ranked[0][0] if len(ranked) >= 1 else None
    nb  = ranked[1][0] if len(ranked) >= 2 else None
    return nap, nb


# ---------------------------------------------------------------------------
# Cookie-based HTTP fetching (no browser required)
# ---------------------------------------------------------------------------

def _make_session(cf_clearance: str) -> cf_requests.Session:
    session = cf_requests.Session(impersonate="chrome")
    session.headers.update({"User-Agent": _USER_AGENT})
    session.cookies.set(
        "cf_clearance", cf_clearance, domain="www.racingandsports.com.au"
    )
    return session


def fetch_with_cookie(url: str, cf_clearance: str) -> str:
    """Fetch a page using a cf_clearance cookie. Raises on failure."""
    session = _make_session(cf_clearance)
    r = session.get(url, timeout=30)
    if r.status_code == 403:
        raise ValueError("CF cookie rejected (403) — cookie may have expired.")
    r.raise_for_status()
    if "Just a moment" in r.text or "Performing security verification" in r.text:
        raise ValueError("CF challenge page returned — cookie may have expired.")
    return r.text


def scrape_meeting_with_cookie(
    meeting_url: str,
    cf_clearance: str,
    log_fn=None,
) -> tuple:
    """
    Scrape a full meeting using a cf_clearance cookie (no browser needed).
    Returns (track_name, results, nap_race, nb_race).
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    track = extract_track_name(meeting_url)
    results = []

    try:
        html = fetch_with_cookie(meeting_url, cf_clearance)
    except Exception as e:
        log(f"ERROR loading overview: {e}")
        return track, [], None, None

    race_count = detect_race_count(html, meeting_url)
    if race_count == 0:
        log("ERROR: Could not detect races on overview page.")
        return track, [], None, None

    log(f"Found {race_count} races")

    for r in range(1, race_count + 1):
        race_url = f"{meeting_url.rstrip('/')}/R{r}"
        try:
            html = fetch_with_cookie(race_url, cf_clearance)
        except Exception as e:
            log(f"R{r}: fetch failed — {e}")
            results.append((r, None, 0))
            continue

        tips = parse_tips(html)
        if not tips:
            log(f"R{r}: no tips found")
            results.append((r, None, 0))
            continue

        selected, gap = select_horse(tips)
        rule = "rank 1" if gap >= 4 else "rank 2"
        log(f"R{r}: {selected['name']} ({rule}, gap={gap})")
        results.append((r, selected, gap))

    nap, nb = assign_nap_nb(results)
    return track, results, nap, nb


# ---------------------------------------------------------------------------
# Firecrawl-based fetching (handles Cloudflare automatically)
# ---------------------------------------------------------------------------

def fetch_with_firecrawl(url: str, api_key: str) -> str:
    """Fetch a page via Firecrawl — bypasses Cloudflare on their infrastructure."""
    app = Firecrawl(api_key=api_key)
    result = app.scrape(url, formats=["html"])
    html = getattr(result, "html", None)
    if not html and isinstance(result, dict):
        html = result.get("html")
    if not html:
        raise ValueError(f"Firecrawl returned no HTML for {url}")
    return html


def scrape_meeting_with_firecrawl(
    meeting_url: str,
    api_key: str,
    log_fn=None,
) -> tuple:
    """
    Scrape a full meeting via Firecrawl.
    Returns (track_name, results, nap_race, nb_race).
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    track = extract_track_name(meeting_url)
    results = []

    try:
        html = fetch_with_firecrawl(meeting_url, api_key)
    except Exception as e:
        log(f"ERROR loading overview: {e}")
        return track, [], None, None

    race_count = detect_race_count(html, meeting_url)
    if race_count == 0:
        log("ERROR: Could not detect races on overview page.")
        return track, [], None, None

    log(f"Found {race_count} races")

    for r in range(1, race_count + 1):
        race_url = f"{meeting_url.rstrip('/')}/R{r}"
        try:
            html = fetch_with_firecrawl(race_url, api_key)
        except Exception as e:
            log(f"R{r}: fetch failed — {e}")
            results.append((r, None, 0))
            continue

        tips = parse_tips(html)
        if not tips:
            log(f"R{r}: no tips found")
            results.append((r, None, 0))
            continue

        selected, gap = select_horse(tips)
        rule = "rank 1" if gap >= 4 else "rank 2"
        log(f"R{r}: {selected['name']} ({rule}, gap={gap})")
        results.append((r, selected, gap))

    nap, nb = assign_nap_nb(results)
    return track, results, nap, nb


# ---------------------------------------------------------------------------
# Overview page helpers
# ---------------------------------------------------------------------------

def detect_race_count(html: str, meeting_url: str) -> int:
    """Detect number of races from the meeting overview page."""
    soup = BeautifulSoup(html, "html.parser")
    base_path = urlparse(meeting_url).path.rstrip("/")
    link_pattern = re.compile(r'/R(\d+)(?:/|$)', re.IGNORECASE)

    race_nums = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if base_path in href:
            m = link_pattern.search(href)
            if m:
                race_nums.add(int(m.group(1)))

    if not race_nums:
        for a in soup.find_all("a", href=True):
            m = link_pattern.search(a["href"])
            if m:
                n = int(m.group(1))
                if 1 <= n <= 20:
                    race_nums.add(n)

    return max(race_nums) if race_nums else 0


def extract_track_name(url: str) -> str:
    """'sha-tin' → 'SHA TIN'"""
    parts = urlparse(url).path.strip("/").split("/")
    if len(parts) >= 4:
        return parts[3].upper().replace("-", " ")
    return "MEETING"


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

def is_challenge_page(page) -> bool:
    try:
        if "Just a moment" in page.title():
            return True
        body = page.inner_text("body")
        if "Performing security verification" in body or "Just a moment" in body:
            return True
    except Exception:
        pass
    return False


def wait_for_page(page, timeout: int = 45) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_challenge_page(page):
            return True
        time.sleep(1)
    return False


def create_page(context):
    """Create a new page with stealth patches applied."""
    from playwright_stealth import Stealth
    page = context.new_page()
    page.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    try:
        Stealth().apply_stealth_sync(page)
    except Exception:
        pass
    return page


def safe_goto(page, url: str, context=None) -> tuple:
    """
    Navigate to a URL, handling page crashes by creating a fresh page.
    Returns (page, success).
    """
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        return page, True
    except PlaywrightTimeoutError:
        return page, True  # partial load is fine
    except Exception as e:
        if any(w in str(e).lower() for w in ("crashed", "closed")) and context:
            try:
                page.close()
            except Exception:
                pass
            page = create_page(context)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                return page, True
            except PlaywrightTimeoutError:
                return page, True
            except Exception:
                return page, False
        return page, False


# ---------------------------------------------------------------------------
# Core scrape function — accepts a Playwright browser context
# ---------------------------------------------------------------------------

def scrape_meeting_with_page(
    meeting_url: str,
    context,
    log_fn=None,
) -> tuple:
    """
    Scrape a full meeting using a Playwright browser context.
    Creates its own page (with stealth) and closes it when done.
    Returns (track_name, results, nap_race, nb_race).
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    track = extract_track_name(meeting_url)
    page = create_page(context)
    results = []

    try:
        page, ok = safe_goto(page, meeting_url, context)
        if not ok:
            log("ERROR: Could not load overview page.")
            return track, [], None, None

        if not wait_for_page(page, timeout=90):
            log("ERROR: Cloudflare challenge did not clear.")
            return track, [], None, None

        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except PlaywrightTimeoutError:
            pass

        race_count = detect_race_count(page.content(), meeting_url)
        if race_count == 0:
            log("ERROR: Could not detect races on overview page.")
            return track, [], None, None

        log(f"Found {race_count} races")
        results = []

        for r in range(1, race_count + 1):
            race_url = f"{meeting_url.rstrip('/')}/R{r}"
            page, ok = safe_goto(page, race_url, context)
            if not ok:
                log(f"R{r}: page crashed — skipped")
                results.append((r, None, 0))
                continue

            if not wait_for_page(page, timeout=30):
                log(f"R{r}: challenge stuck — skipped")
                results.append((r, None, 0))
                continue

            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except PlaywrightTimeoutError:
                pass

            tips = parse_tips(page.content())
            if not tips:
                log(f"R{r}: no tips found")
                results.append((r, None, 0))
                continue

            selected, gap = select_horse(tips)
            rule = "rank 1" if gap >= 4 else "rank 2"
            log(f"R{r}: {selected['name']} ({rule}, gap={gap})")
            results.append((r, selected, gap))

    except Exception as e:
        log(f"ERROR: {e}")
    finally:
        try:
            page.close()
        except Exception:
            pass

    nap, nb = assign_nap_nb(results)
    return track, results, nap, nb


# ---------------------------------------------------------------------------
# Standalone browser session — used by CLI
# ---------------------------------------------------------------------------

def make_context(browser, headless: bool = False):
    return browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        extra_http_headers={
            "Sec-CH-UA":          '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
            "Sec-CH-UA-Mobile":   "?0",
            "Sec-CH-UA-Platform": '"Windows"',
        },
    )


def scrape_meeting(meeting_url: str, cdp_url: str = "http://localhost:9222") -> None:
    print(f"\nLoading: {meeting_url}")
    print(f"Connecting to Chrome on {cdp_url} ...\n")

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            print("Connected to your Chrome browser.\n")
        except Exception:
            print(
                "Could not connect to Chrome.\n"
                "Please close Chrome and relaunch with:\n"
                r'  "C:\Program Files\Google\Chrome\Application\chrome.exe"'
                " --remote-debugging-port=9222 --user-data-dir=\"C:\\ChromeDebug\"\n"
            )
            return

        track, results, nap, nb = scrape_meeting_with_page(
            meeting_url, context, log_fn=lambda m: print(f"  {m}")
        )
        browser.close()

    print(f"\n{'=' * 35}")
    print(track)
    for r, selected, gap in results:
        if not selected:
            print(f"R{r} -")
            continue
        suffix = " (NAP)" if r == nap else " (NB)" if r == nb else ""
        print(f"R{r} {selected['name']}{suffix}")
    print(f"{'=' * 35}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scraper.py <meeting-url>")
        sys.exit(1)
    scrape_meeting(sys.argv[1])
