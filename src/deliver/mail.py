"""Gmail SMTP 로 다이제스트를 보낸다 (앱 비밀번호 사용)."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from ..config import DeliveryConfig

log = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
TIMEOUT = 30


def send(config: DeliveryConfig, subject: str, html_body: str, text_body: str) -> bool:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.gmail_address
    message["To"] = config.recipient
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=TIMEOUT) as smtp:
            smtp.login(config.gmail_address, config.gmail_app_password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        log.error("메일 발송 실패: %s", exc)
        return False

    log.info("메일 발송 완료 -> %s", config.recipient)
    return True
