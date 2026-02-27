"""Tests para el cliente de Slack."""

import httpx
import pytest
import respx

from src.clients.slack import SLACK_API_BASE, SlackClient, SlackError


@pytest.fixture
def slack_client():
    """Cliente Slack con token fake."""
    client = SlackClient(bot_token="xoxb-fake-token")
    client._client = httpx.AsyncClient(
        base_url=SLACK_API_BASE,
        headers={"Authorization": "Bearer xoxb-fake-token"},
        timeout=httpx.Timeout(30.0),
    )
    return client


class TestSendDm:
    @respx.mock
    async def test_sends_dm(self, slack_client: SlackClient) -> None:
        respx.post(f"{SLACK_API_BASE}/conversations.open").mock(
            return_value=httpx.Response(200, json={"ok": True, "channel": {"id": "D123"}})
        )
        respx.post(f"{SLACK_API_BASE}/chat.postMessage").mock(
            return_value=httpx.Response(200, json={"ok": True, "ts": "1234567890.123456"})
        )
        result = await slack_client.send_dm(user_id="U123", text="Hola!")
        assert result == "1234567890.123456"

    @respx.mock
    async def test_raises_on_slack_error(self, slack_client: SlackClient) -> None:
        respx.post(f"{SLACK_API_BASE}/conversations.open").mock(
            return_value=httpx.Response(200, json={"ok": False, "error": "user_not_found"})
        )
        with pytest.raises(SlackError) as exc_info:
            await slack_client.send_dm(user_id="UINVALID", text="Hola!")
        assert exc_info.value.slack_error == "user_not_found"

    @respx.mock
    async def test_raises_on_http_error(self, slack_client: SlackClient) -> None:
        respx.post(f"{SLACK_API_BASE}/conversations.open").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        with pytest.raises(SlackError):
            await slack_client.send_dm(user_id="U123", text="Hola!")
