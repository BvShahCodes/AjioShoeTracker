"""
Notification module — Telegram + desktop toast (Windows) + optional Gmail.
"""

import logging
import smtplib
import sys
import urllib.request
import urllib.parse
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import (
    TELEGRAM_ENABLED, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    EMAIL_ENABLED, EMAIL_SENDER, EMAIL_PASSWORD,
    EMAIL_RECEIVER, SMTP_HOST, SMTP_PORT,
    PRODUCT_URL, TARGET_SIZE,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Telegram  (recommended — works on any device, free)
# ---------------------------------------------------------------------------

def notify_telegram(message: str) -> None:
    """Send a Telegram message via the Bot API (no third-party lib needed)."""
    if not TELEGRAM_ENABLED:
        return
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram enabled but TOKEN or CHAT_ID is missing — skipping.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("ok"):
                logger.info("Telegram notification sent")
            else:
                logger.warning(f"Telegram API error: {data}")
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")


# ---------------------------------------------------------------------------
# Desktop toast (Windows only, skipped silently on other platforms)
# ---------------------------------------------------------------------------

def notify_desktop(title: str, message: str) -> None:
    if sys.platform != "win32":
        return
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name="Ajio Size Monitor",
            timeout=30,
        )
    except Exception as e:
        logger.warning(f"Desktop notification failed: {e}")

    try:
        import winsound
        for _ in range(3):
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Email (optional)
# ---------------------------------------------------------------------------

def notify_email(subject: str, body: str) -> None:
    if not EMAIL_ENABLED:
        return
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER]):
        logger.warning("Email enabled but credentials incomplete — skipping.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        logger.info(f"Email alert sent to {EMAIL_RECEIVER}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")


# ---------------------------------------------------------------------------
# Master alert dispatcher
# ---------------------------------------------------------------------------

def send_stock_alert(size: str = TARGET_SIZE) -> None:
    """Fire all configured notifications when the target size is back in stock."""
    title = f"Size {size} is back in stock!"
    body = (
        f"Puma Mayze Lux (White) — Size {size} is now available on Ajio.\n\n"
        f"Buy now: {PRODUCT_URL}"
    )
    telegram_msg = (
        f"<b>Ajio Restock Alert!</b>\n\n"
        f"Puma Mayze Lux (White) — <b>Size {size}</b> is now IN STOCK!\n\n"
        f'<a href="{PRODUCT_URL}">Buy now on Ajio</a>'
    )

    logger.info(f"*** ALERT: {title} ***")
    notify_telegram(telegram_msg)
    notify_desktop(title, body)
    notify_email(subject=f"[Ajio Alert] {title}", body=body)
