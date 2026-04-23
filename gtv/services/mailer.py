"""SMTP delivery using Gmail-compatible settings."""

from __future__ import annotations

from email.message import EmailMessage
import smtplib

from gtv.config import Settings


def send_email(settings: Settings, *, to_email: str, subject: str, body: str) -> tuple[bool, str]:
    if not settings.smtp_enabled:
        return False, "SMTP no configurado"

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        return True, "Enviado"
    except Exception as exc:  # pragma: no cover - depende del entorno SMTP real.
        return False, str(exc)
