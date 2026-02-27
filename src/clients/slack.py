"""Cliente async para Slack Web API (enviar DMs)."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

SLACK_API_BASE = "https://slack.com/api"


class SlackError(Exception):
    """Error al comunicarse con la API de Slack."""

    def __init__(self, message: str, slack_error: str | None = None) -> None:
        super().__init__(message)
        self.slack_error = slack_error


class SlackClient:
    """Cliente async para Slack Web API.

    Uso como context manager async:
        async with SlackClient(bot_token="xoxb-...") as slack:
            await slack.send_dm(user_id="U...", text="Hola!")
    """

    def __init__(self, bot_token: str) -> None:
        self._bot_token = bot_token
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> SlackClient:
        self._client = httpx.AsyncClient(
            base_url=SLACK_API_BASE,
            headers={"Authorization": f"Bearer {self._bot_token}"},
            timeout=httpx.Timeout(30.0),
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client:
            await self._client.aclose()

    # ── Métodos públicos ────────────────────────────────────────

    async def send_dm(self, user_id: str, text: str) -> str:
        """Envía un mensaje directo a un usuario de Slack.

        Devuelve el timestamp del mensaje (ts), que sirve como ID.
        """
        # conversations.open para obtener el channel_id del DM
        open_data = await self._api_call("conversations.open", json={"users": user_id})
        channel_id = open_data["channel"]["id"]

        # chat.postMessage para enviar el mensaje
        msg_data = await self._api_call(
            "chat.postMessage",
            json={"channel": channel_id, "text": text},
        )

        ts = msg_data["ts"]
        logger.info("slack_dm_sent", user_id=user_id, ts=ts)
        return ts

    # ── Internals ───────────────────────────────────────────────

    async def _api_call(self, method: str, **kwargs: Any) -> dict[str, Any]:
        """Ejecuta una llamada a la Slack Web API."""
        assert self._client is not None, "Usar como context manager: async with SlackClient(...)"

        response = await self._client.post(f"/{method}", **kwargs)

        if response.status_code >= 400:
            raise SlackError(f"Slack HTTP {response.status_code}: {response.text}")

        data = response.json()

        if not data.get("ok"):
            error = data.get("error", "unknown_error")
            raise SlackError(f"Slack API error: {error}", slack_error=error)

        return data
