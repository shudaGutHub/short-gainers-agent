#!/usr/bin/env python3
"""
Notifications Module for Short Gainers Agent

Sends notifications via WhatsApp (Twilio) or Email after batch analysis completes.
"""

import os
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional


@dataclass
class NotificationConfig:
    """Configuration for notifications."""
    # Email settings
    email_enabled: bool = False
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""  # Use app password for Gmail
    email_from: str = ""
    email_to: list[str] = None  # List of recipient emails

    # WhatsApp settings (via Twilio)
    whatsapp_enabled: bool = False
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""  # e.g., "whatsapp:+14155238886"
    whatsapp_to: list[str] = None  # e.g., ["whatsapp:+1234567890"]

    # Report URL
    report_url: str = "http://localhost:5000"

    def __post_init__(self):
        if self.email_to is None:
            self.email_to = []
        if self.whatsapp_to is None:
            self.whatsapp_to = []


def load_notification_config() -> NotificationConfig:
    """Load notification config from environment variables."""
    return NotificationConfig(
        # Email
        email_enabled=os.environ.get("NOTIFY_EMAIL_ENABLED", "").lower() == "true",
        smtp_server=os.environ.get("SMTP_SERVER", "smtp.gmail.com"),
        smtp_port=int(os.environ.get("SMTP_PORT", "587")),
        smtp_username=os.environ.get("SMTP_USERNAME", ""),
        smtp_password=os.environ.get("SMTP_PASSWORD", ""),
        email_from=os.environ.get("EMAIL_FROM", ""),
        email_to=[e.strip() for e in os.environ.get("EMAIL_TO", "").split(",") if e.strip()],

        # WhatsApp
        whatsapp_enabled=os.environ.get("NOTIFY_WHATSAPP_ENABLED", "").lower() == "true",
        twilio_account_sid=os.environ.get("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token=os.environ.get("TWILIO_AUTH_TOKEN", ""),
        twilio_whatsapp_from=os.environ.get("TWILIO_WHATSAPP_FROM", ""),
        whatsapp_to=[w.strip() for w in os.environ.get("WHATSAPP_TO", "").split(",") if w.strip()],

        # Report URL
        report_url=os.environ.get("REPORT_URL", "http://localhost:5000"),
    )


def format_report_summary(result: dict, tickers_analyzed: list[str]) -> str:
    """Format a summary of the analysis for notifications."""
    count = result.get("count", 0)
    date = result.get("analysis_date", "")

    ticker_list = ", ".join(tickers_analyzed[:10])
    if len(tickers_analyzed) > 10:
        ticker_list += f" (+{len(tickers_analyzed) - 10} more)"

    return f"""Short Gainers Analysis Complete

Date: {date}
Tickers Analyzed: {count}
Symbols: {ticker_list}

View Reports: {{url}}"""


def send_email_notification(
    config: NotificationConfig,
    subject: str,
    body: str,
    html_body: Optional[str] = None,
) -> bool:
    """
    Send email notification.

    Args:
        config: Notification configuration
        subject: Email subject
        body: Plain text body
        html_body: Optional HTML body

    Returns:
        True if sent successfully
    """
    if not config.email_enabled:
        return False

    if not config.email_to:
        print("Email notification skipped: no recipients configured")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = config.email_from or config.smtp_username
        msg["To"] = ", ".join(config.email_to)

        # Attach plain text
        msg.attach(MIMEText(body, "plain"))

        # Attach HTML if provided
        if html_body:
            msg.attach(MIMEText(html_body, "html"))

        # Send email
        with smtplib.SMTP(config.smtp_server, config.smtp_port) as server:
            server.starttls()
            server.login(config.smtp_username, config.smtp_password)
            server.sendmail(
                config.email_from or config.smtp_username,
                config.email_to,
                msg.as_string()
            )

        print(f"Email sent to: {', '.join(config.email_to)}")
        return True

    except Exception as e:
        print(f"Failed to send email: {e}")
        return False


def send_whatsapp_notification(
    config: NotificationConfig,
    message: str,
) -> bool:
    """
    Send WhatsApp notification via Twilio.

    Args:
        config: Notification configuration
        message: Message to send

    Returns:
        True if sent successfully
    """
    if not config.whatsapp_enabled:
        return False

    if not config.whatsapp_to:
        print("WhatsApp notification skipped: no recipients configured")
        return False

    try:
        from twilio.rest import Client

        client = Client(config.twilio_account_sid, config.twilio_auth_token)

        for recipient in config.whatsapp_to:
            # Ensure whatsapp: prefix
            if not recipient.startswith("whatsapp:"):
                recipient = f"whatsapp:{recipient}"

            msg = client.messages.create(
                body=message,
                from_=config.twilio_whatsapp_from,
                to=recipient
            )
            print(f"WhatsApp sent to {recipient}: {msg.sid}")

        return True

    except ImportError:
        print("WhatsApp notification failed: twilio package not installed")
        print("Install with: pip install twilio")
        return False
    except Exception as e:
        print(f"Failed to send WhatsApp: {e}")
        return False


def send_notifications(
    result: dict,
    tickers_analyzed: list[str],
    config: Optional[NotificationConfig] = None,
    report_url: Optional[str] = None,
) -> dict:
    """
    Send all configured notifications after batch analysis.

    Args:
        result: Result dict from batch analysis
        tickers_analyzed: List of ticker symbols analyzed
        config: Optional notification config (loads from env if not provided)
        report_url: Optional override for report URL

    Returns:
        Dict with status of each notification type
    """
    if config is None:
        config = load_notification_config()

    if report_url:
        config.report_url = report_url

    # Format message
    summary = format_report_summary(result, tickers_analyzed)
    message = summary.format(url=config.report_url)

    # HTML version for email
    html_message = f"""
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px;">
        <h2 style="color: #1e40af;">Short Gainers Analysis Complete</h2>
        <p><strong>Date:</strong> {result.get('analysis_date', '')}</p>
        <p><strong>Tickers Analyzed:</strong> {result.get('count', 0)}</p>
        <p><strong>Symbols:</strong> {', '.join(tickers_analyzed[:10])}{' (+' + str(len(tickers_analyzed) - 10) + ' more)' if len(tickers_analyzed) > 10 else ''}</p>
        <p style="margin-top: 20px;">
            <a href="{config.report_url}" style="background: #1e40af; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px;">
                View Reports
            </a>
        </p>
    </body>
    </html>
    """

    status = {
        "email": False,
        "whatsapp": False,
    }

    # Send email
    if config.email_enabled:
        status["email"] = send_email_notification(
            config,
            subject=f"Short Gainers Report - {result.get('count', 0)} tickers analyzed",
            body=message,
            html_body=html_message,
        )

    # Send WhatsApp
    if config.whatsapp_enabled:
        status["whatsapp"] = send_whatsapp_notification(config, message)

    return status


# Simple notification via URL opening (fallback)
def open_whatsapp_web(phone: str, message: str) -> bool:
    """
    Open WhatsApp Web with pre-filled message (no Twilio required).

    Args:
        phone: Phone number (with country code, no +)
        message: Message to send

    Returns:
        True if browser opened
    """
    import urllib.parse
    import webbrowser

    encoded_message = urllib.parse.quote(message)
    url = f"https://web.whatsapp.com/send?phone={phone}&text={encoded_message}"

    try:
        webbrowser.open(url)
        return True
    except Exception as e:
        print(f"Failed to open WhatsApp Web: {e}")
        return False
