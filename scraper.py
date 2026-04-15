"""
Ajio product size availability scraper.

Two browser modes controlled by BROWSER_MODE in config:

  cdp        (Windows / local)
    Launches Chrome as a normal OS subprocess on port 9223, then Playwright
    connects via CDP. Chrome runs with zero Playwright flags, so Akamai sees
    a completely ordinary browser — this is what bypasses the bot detection.

  playwright  (Linux / GitHub Actions / CI)
    Uses Playwright's built-in Chromium launch with stealth patches.
    Suitable for cloud runners where a real Chrome subprocess isn't practical.
"""

import asyncio
import json
import logging
import random
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    async_playwright, Browser, BrowserContext, Page, Playwright,
    TimeoutError as PlaywrightTimeout,
)
from playwright_stealth import Stealth

from config import PRODUCT_URL, TARGET_SIZE, PAGE_TIMEOUT_MS, BROWSER_MODE

logger = logging.getLogger(__name__)
_stealth = Stealth()

# ---------------------------------------------------------------------------
# Chrome location (CDP mode)
# ---------------------------------------------------------------------------
_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
]

def _find_chrome() -> str:
    override = __import__("os").getenv("CHROME_PATH", "")
    if override and Path(override).exists():
        return override
    for p in _CHROME_CANDIDATES:
        if Path(p).exists():
            return p
    raise FileNotFoundError(
        "Google Chrome not found. Install Chrome or set CHROME_PATH in .env"
    )

CDP_PORT = 9223

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SizeInfo:
    size: str
    available: bool


@dataclass
class ScrapeResult:
    target_size: str
    found: bool = False
    available: bool = False
    message: str = ""
    all_sizes: list[SizeInfo] = field(default_factory=list)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Ajio embeds ALL product + stock data in window.__PRELOADED_STATE__ in the
# page HTML. We extract it as JSON — faster and more reliable than DOM parsing.
#
# Path to size stock:
#   __PRELOADED_STATE__
#     .product.productDetails.variantOptions[]
#       .stock.stockLevelStatus  →  "inStock" | "outOfStock"
#       .variantOptionQualifiers[qualifier=="size"].value  →  "3", "4", …
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Browser wrapper
# ---------------------------------------------------------------------------

class AjioBrowser:
    """
    Wraps a long-lived browser session for repeated checks.
    Mode is determined by BROWSER_MODE in config.
    """

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._warmed_up = False

    async def start(self):
        self._playwright = await async_playwright().start()

        if BROWSER_MODE == "cdp":
            await self._start_cdp()
        else:
            await self._start_playwright()

    async def _start_cdp(self):
        """Launch real Chrome subprocess → connect via CDP."""
        chrome_exe = _find_chrome()
        self._user_data_dir = tempfile.mkdtemp(prefix="ajio_chrome_")
        cmd = [
            chrome_exe,
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={self._user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
            "--start-maximized",
        ]
        logger.info(f"Launching Chrome subprocess on port {CDP_PORT} ...")
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        await asyncio.sleep(3)

        self._browser = await self._playwright.chromium.connect_over_cdp(
            f"http://localhost:{CDP_PORT}"
        )
        logger.info("Connected to Chrome via CDP")
        self._context = (
            self._browser.contexts[0]
            if self._browser.contexts
            else await self._browser.new_context()
        )

    async def _start_playwright(self):
        """Use Playwright's built-in Chromium (CI/Linux mode)."""
        logger.info("Starting Playwright Chromium (headless) ...")
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        self._context = await self._browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 768},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            extra_http_headers={
                "Accept-Language": "en-IN,en-GB;q=0.9,en;q=0.8",
            },
        )

    async def warmup(self):
        """Visit Ajio homepage to seed session cookies."""
        if self._warmed_up:
            return
        logger.info("Warm-up: seeding cookies from Ajio homepage...")
        page = await self.new_page()
        try:
            await page.goto("https://www.ajio.com", wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            await _human_pause(page, 4)
            await _human_scroll(page)
            logger.info("Warm-up complete")
            self._warmed_up = True
        except Exception as e:
            logger.warning(f"Warm-up failed (non-fatal): {e}")
        finally:
            await page.close()

    async def new_page(self) -> Page:
        page = await self._context.new_page()
        if BROWSER_MODE == "playwright":
            await _stealth.apply_stealth_async(page)
        return page

    async def close(self):
        for obj in (self._browser, self._playwright):
            try:
                if obj:
                    await obj.close() if asyncio.iscoroutinefunction(obj.close) else obj.stop()
            except Exception:
                pass
        # stop() on Playwright is not a coroutine — handle separately
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        logger.info("Browser closed")


# Module-level singleton
_browser_instance: Optional[AjioBrowser] = None


async def init_browser() -> AjioBrowser:
    global _browser_instance
    _browser_instance = AjioBrowser()
    await _browser_instance.start()
    await _browser_instance.warmup()
    return _browser_instance


async def close_browser():
    global _browser_instance
    if _browser_instance:
        await _browser_instance.close()
        _browser_instance = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _human_pause(page: Page, seconds: float = 2.0):
    jitter = random.uniform(0.3, 1.0)
    await page.wait_for_timeout(int((seconds + jitter) * 1000))


async def _human_scroll(page: Page):
    try:
        for _ in range(random.randint(3, 5)):
            await page.mouse.wheel(0, random.randint(200, 600))
            await page.wait_for_timeout(random.randint(300, 800))
        await page.mouse.wheel(0, -800)
        await page.wait_for_timeout(500)
    except Exception:
        pass


def _parse_sizes_from_preloaded_state(html: str) -> list[SizeInfo]:
    """
    Extract size + stock data from window.__PRELOADED_STATE__ embedded in HTML.
    Returns [] if the data can't be found (page blocked or structure changed).
    """
    match = re.search(
        r'window\.__PRELOADED_STATE__\s*=\s*(\{.*?\});?\s*</script>',
        html, re.DOTALL
    )
    if not match:
        return []

    try:
        state = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []

    try:
        variant_options = (
            state["product"]["productDetails"]["variantOptions"]
        )
    except (KeyError, TypeError):
        return []

    sizes: list[SizeInfo] = []
    for variant in variant_options:
        # Find the size label from qualifiers
        qualifiers = variant.get("variantOptionQualifiers", [])
        size_label = next(
            (q["value"] for q in qualifiers if q.get("qualifier") == "size"),
            None,
        )
        if size_label is None:
            continue

        stock_status = variant.get("stock", {}).get("stockLevelStatus", "outOfStock")
        available = stock_status == "inStock"
        sizes.append(SizeInfo(size=size_label, available=available))

    return sizes


# ---------------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------------

async def check_size_availability(
    target_size: str = TARGET_SIZE,
    url: str = PRODUCT_URL,
    debug_screenshot: bool = False,
) -> ScrapeResult:
    result = ScrapeResult(target_size=target_size)

    own_browser = _browser_instance is None
    browser = _browser_instance or await init_browser()

    page = await browser.new_page()
    try:
        logger.info("Navigating to product page...")
        await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        # Small pause so the server-rendered HTML is fully received
        await _human_pause(page, 2)

        if debug_screenshot:
            await page.screenshot(path="debug.png", full_page=False)
            logger.info("Screenshot saved -> debug.png")

        html = await page.content()

        if "access denied" in html.lower()[:2000]:
            if debug_screenshot:
                Path("debug_page.html").write_text(html, encoding="utf-8")
            result.error = (
                "Ajio returned 'Access Denied' (Akamai blocked this IP). "
                "Cloud IPs are always blocked — use the Windows Task Scheduler "
                "option which runs from your home IP."
            )
            logger.error(result.error)
            return result

        # Parse size + stock from embedded JSON (fast, no DOM waiting needed)
        sizes = _parse_sizes_from_preloaded_state(html)

        if not sizes:
            if debug_screenshot:
                Path("debug_page.html").write_text(html, encoding="utf-8")
            result.error = (
                "Could not find size data in page. "
                "Check debug.png / debug_page.html."
            )
            logger.warning(result.error)
            return result

        logger.info(f"Found {len(sizes)} sizes in page data")
        result.all_sizes = sizes

        for s in sizes:
            logger.debug(f"  {s.size!r}: {'in stock' if s.available else 'OOS'}")
            if s.size == target_size or s.size.upper() == f"UK {target_size}":
                result.found = True
                result.available = s.available
                result.message = f"Size {target_size} is {'IN STOCK' if s.available else 'OUT OF STOCK'}"

        if not result.found:
            labels = [s.size for s in sizes]
            result.message = f"Size {target_size!r} not in size list. Labels: {labels}"
            logger.warning(result.message)

    except PlaywrightTimeout:
        result.error = f"Page load timed out after {PAGE_TIMEOUT_MS // 1000}s"
        logger.error(result.error)
    except Exception as e:
        result.error = f"Unexpected error: {e}"
        logger.exception("Scrape failed")
    finally:
        await page.close()
        if own_browser:
            await browser.close()

    return result


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")

    async def _main():
        await init_browser()
        try:
            result = await check_size_availability(debug_screenshot=True)
        finally:
            await close_browser()

        print("\n=== Scrape Result ===")
        print(f"Target  : {result.target_size}")
        print(f"Found   : {result.found}")
        print(f"In stock: {result.available}")
        print(f"Message : {result.message}")
        if result.error:
            print(f"Error   : {result.error}")
        if result.all_sizes:
            print("\nAll sizes:")
            for s in result.all_sizes:
                print(f"  {s.size:>8}  {'[in stock]' if s.available else '[OOS]'}")

    asyncio.run(_main())
