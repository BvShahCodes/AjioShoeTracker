"""
Ajio size monitor — polls the product page every CHECK_INTERVAL_MINUTES and
fires a desktop notification + optional email when the target size is in stock.

Usage:
    python monitor.py              # start continuous monitoring
    python monitor.py --once       # one check then exit
    python monitor.py --debug      # one check + save debug.png / debug_page.html

A Chrome window will open (and can be minimised). This is intentional —
running headless triggers Ajio's bot detection (Akamai). The window must
stay open while the monitor is running.
"""

import asyncio
import logging
import signal
import sys
import time
from datetime import datetime

from config import CHECK_INTERVAL_MINUTES, TARGET_SIZE, PRODUCT_URL
from scraper import init_browser, close_browser, check_size_availability
from notifier import send_stock_alert

# ---------------------------------------------------------------------------
# Logging — stdout + rotating file
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("monitor.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Single check
# ---------------------------------------------------------------------------

async def run_check(debug: bool = False) -> bool:
    """Return True if target size is in stock."""
    logger.info(f"Checking size {TARGET_SIZE!r} ...")
    result = await check_size_availability(debug_screenshot=debug)

    if result.error:
        logger.error(f"  Error: {result.error}")
        return False

    if result.found:
        logger.info(f"  {result.message}")
        if result.available:
            send_stock_alert(TARGET_SIZE)
            return True
    else:
        logger.warning(f"  {result.message}")

    if result.all_sizes:
        in_stock  = [s.size for s in result.all_sizes if s.available]
        oos       = [s.size for s in result.all_sizes if not s.available]
        logger.info(f"  In stock : {in_stock or 'none'}")
        logger.info(f"  OOS      : {oos or 'none'}")

    return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _banner():
    print("=" * 62)
    print("  Ajio Size Monitor")
    print(f"  Product  : Puma Mayze Lux Women's Sneakers (White)")
    print(f"  Watching : Size {TARGET_SIZE}")
    if "--once" in sys.argv or "--debug" in sys.argv:
        print("  Mode     : Single check")
    else:
        print(f"  Interval : Every {CHECK_INTERVAL_MINUTES} minute(s)")
    print()
    print("  NOTE: A Chrome window will open — you can minimise it.")
    print("        Do NOT close it while the monitor is running.")
    print("=" * 62)


async def _async_main():
    once  = "--once"  in sys.argv
    debug = "--debug" in sys.argv

    _banner()

    # Start shared browser (warm-up included)
    await init_browser()

    try:
        if once or debug:
            available = await run_check(debug=debug)
            logger.info("Single-check done.")
            return

        # Continuous loop
        logger.info("Monitoring started. Press Ctrl+C to stop.\n")
        while True:
            available = await run_check()
            if available:
                logger.info(
                    f"*** Size {TARGET_SIZE} IS IN STOCK! "
                    "Notification sent. Still monitoring... ***"
                )

            next_at = datetime.now().strftime("%H:%M:%S")
            logger.info(
                f"Sleeping {CHECK_INTERVAL_MINUTES} min "
                f"(next check ~{next_at}) ...\n"
            )
            await asyncio.sleep(CHECK_INTERVAL_MINUTES * 60)

    except asyncio.CancelledError:
        pass
    finally:
        await close_browser()
        logger.info("Monitor stopped.")


def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    main_task = None

    def _shutdown(signum, frame):
        logger.info("Interrupt received — shutting down...")
        if main_task and not main_task.done():
            main_task.cancel()

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    main_task = loop.create_task(_async_main())
    try:
        loop.run_until_complete(main_task)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
