"""Cliente async para Gmail API (enviar emails)."""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from typing import Any

import httpx
import structlog

from src.clients.google_auth import get_google_credentials

logger = structlog.get_logger()

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"


class GmailError(Exception):
    """Error al comunicarse con la Gmail API."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GmailClient:
    """Cliente async para enviar emails vía Gmail API.

    Envía desde la cuenta asociada al token OAuth (tech@leanfinance.es).

    Uso como context manager async:
        async with GmailClient() as gmail:
            await gmail.send_email(to="...", subject="...", body_html="...")
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> GmailClient:
        creds = get_google_credentials()
        self._client = httpx.AsyncClient(
            base_url=GMAIL_API_BASE,
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=httpx.Timeout(30.0),
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client:
            await self._client.aclose()

    # ── Métodos públicos ────────────────────────────────────────

    async def send_email(
        self,
        to: str,
        subject: str,
        body_html: str,
        sender: str = "tech@leanfinance.es",
    ) -> str:
        """Envía un email HTML y devuelve el message ID de Gmail."""
        assert self._client is not None, "Usar como context manager: async with GmailClient(...)"

        message = MIMEText(body_html, "html")
        message["to"] = to
        message["from"] = sender
        message["subject"] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        response = await self._client.post(
            "/users/me/messages/send",
            json={"raw": raw},
        )

        if response.status_code >= 400:
            raise GmailError(
                f"Gmail {response.status_code}: {response.text}",
                status_code=response.status_code,
            )

        data: dict[str, Any] = response.json()
        message_id = data.get("id", "")
        logger.info("gmail_email_sent", to=to, subject=subject, message_id=message_id)
        return message_id
