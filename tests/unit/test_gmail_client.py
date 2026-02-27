"""Tests para el cliente de Gmail."""

import httpx
import pytest
import respx

from src.clients.gmail import GMAIL_API_BASE, GmailClient, GmailError


@pytest.fixture
def gmail_client():
    """Cliente Gmail con auth mockeada."""
    client = GmailClient()
    client._client = httpx.AsyncClient(
        base_url=GMAIL_API_BASE,
        headers={"Authorization": "Bearer fake-token"},
        timeout=httpx.Timeout(30.0),
    )
    return client


class TestSendEmail:
    @respx.mock
    async def test_sends_email(self, gmail_client: GmailClient) -> None:
        respx.post(f"{GMAIL_API_BASE}/users/me/messages/send").mock(
            return_value=httpx.Response(200, json={"id": "msg_abc123", "threadId": "thread_1"})
        )
        result = await gmail_client.send_email(
            to="tecnico@leanfinance.es",
            subject="Nuevo onboarding",
            body_html="<p>Tienes un nuevo negocio asignado.</p>",
        )
        assert result == "msg_abc123"

    @respx.mock
    async def test_sends_with_correct_payload(self, gmail_client: GmailClient) -> None:
        route = respx.post(f"{GMAIL_API_BASE}/users/me/messages/send").mock(
            return_value=httpx.Response(200, json={"id": "msg_123"})
        )
        await gmail_client.send_email(
            to="test@test.com",
            subject="Test",
            body_html="<p>Test</p>",
        )
        # Verificar que se envió con campo "raw"
        request = route.calls.last.request
        import json
        body = json.loads(request.content)
        assert "raw" in body

    @respx.mock
    async def test_raises_on_error(self, gmail_client: GmailClient) -> None:
        respx.post(f"{GMAIL_API_BASE}/users/me/messages/send").mock(
            return_value=httpx.Response(403, text="Insufficient permissions")
        )
        with pytest.raises(GmailError) as exc_info:
            await gmail_client.send_email(
                to="test@test.com",
                subject="Test",
                body_html="<p>Test</p>",
            )
        assert exc_info.value.status_code == 403
