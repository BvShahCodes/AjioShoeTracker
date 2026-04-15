import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Product to monitor
PRODUCT_URL = "https://www.ajio.com/puma-mayze-lux-women-s-sneakers/p/701812622_white"
TARGET_SIZE = os.getenv("TARGET_SIZE", "4")

# How often to check (in minutes)
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "15"))

# --- Telegram notification (recommended) ---
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# --- Optional email notification ---
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")  # Gmail App Password
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

# --- Browser mode ---
# "cdp"   → launch Chrome as a subprocess and connect via CDP (default on Windows;
#            bypasses Akamai because Chrome runs as a normal user process)
# "playwright" → use Playwright's built-in Chromium launch (used in CI / Linux)
# "auto"  → cdp on Windows, playwright on Linux/Mac
_browser_mode_env = os.getenv("BROWSER_MODE", "auto").lower()
if _browser_mode_env == "auto":
    BROWSER_MODE = "cdp" if sys.platform == "win32" else "playwright"
else:
    BROWSER_MODE = _browser_mode_env   # "cdp" or "playwright"

PAGE_TIMEOUT_MS = 60000
