"""Tests para el cliente de Holded."""

import httpx
import pytest
import respx

from src.clients.holded import HOLDED_API_BASE, HoldedClient, HoldedError, holded_contact_url


@pytest.fixture
def holded_client():
    """Cliente Holded con API key fake."""
    client = HoldedClient(api_key="fake-key")
    client._client = httpx.AsyncClient(
        base_url=HOLDED_API_BASE,
        headers={"key": "fake-key"},
        timeout=httpx.Timeout(30.0),
    )
    return client


class TestCreateContact:
    @respx.mock
    async def test_creates_contact(self, holded_client: HoldedClient) -> None:
        respx.post(f"{HOLDED_API_BASE}/contacts").mock(
            return_value=httpx.Response(200, json={"id": "holded_abc123"})
        )
        payload = {"name": "Test Corp", "type": "client", "code": "B12345678"}
        result = await holded_client.create_contact(payload)
        assert result == "holded_abc123"

    @respx.mock
    async def test_raises_on_error(self, holded_client: HoldedClient) -> None:
        respx.post(f"{HOLDED_API_BASE}/contacts").mock(
            return_value=httpx.Response(422, text="Validation error")
        )
        with pytest.raises(HoldedError) as exc_info:
            await holded_client.create_contact({"name": "Test"})
        assert exc_info.value.status_code == 422


class TestGetContact:
    @respx.mock
    async def test_returns_contact(self, holded_client: HoldedClient) -> None:
        respx.get(f"{HOLDED_API_BASE}/contacts/abc123").mock(
            return_value=httpx.Response(200, json={"id": "abc123", "name": "Test Corp"})
        )
        result = await holded_client.get_contact("abc123")
        assert result["name"] == "Test Corp"


class TestHoldedContactUrl:
    def test_generates_correct_url(self) -> None:
        assert holded_contact_url("abc123") == "https://app.holded.com/contacts/abc123"
