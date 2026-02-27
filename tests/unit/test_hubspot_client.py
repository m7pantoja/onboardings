"""Tests para HubSpotClient."""

import httpx
import pytest
import respx

from src.clients.hubspot import (
    BASE_URL,
    COMPANY_PROPERTIES,
    CONTACT_PROPERTIES,
    DEAL_PROPERTIES,
    HubSpotClient,
    HubSpotError,
)


@pytest.fixture
def token() -> str:
    return "test-token-123"


class TestSearchWonDeals:
    @respx.mock
    async def test_returns_deals(self, token: str):
        respx.post(f"{BASE_URL}/crm/v3/objects/deals/search").mock(
            return_value=httpx.Response(200, json={
                "results": [
                    {"id": "100", "properties": {"dealname": "ACME - CFO"}},
                    {"id": "200", "properties": {"dealname": "BETA - ENISA"}},
                ],
                "paging": {},
            })
        )

        from datetime import datetime
        async with HubSpotClient(token=token) as client:
            deals = [d async for d in client.search_won_deals(since=datetime(2025, 1, 1))]

        assert len(deals) == 2
        assert deals[0]["id"] == "100"
        assert deals[1]["id"] == "200"

    @respx.mock
    async def test_handles_pagination(self, token: str):
        """Verifica que itera múltiples páginas."""
        route = respx.post(f"{BASE_URL}/crm/v3/objects/deals/search")
        route.side_effect = [
            httpx.Response(200, json={
                "results": [{"id": "1", "properties": {}}],
                "paging": {"next": {"after": "cursor_1"}},
            }),
            httpx.Response(200, json={
                "results": [{"id": "2", "properties": {}}],
                "paging": {},
            }),
        ]

        from datetime import datetime
        async with HubSpotClient(token=token) as client:
            deals = [d async for d in client.search_won_deals(since=datetime(2025, 1, 1))]

        assert len(deals) == 2
        assert deals[0]["id"] == "1"
        assert deals[1]["id"] == "2"
        assert route.call_count == 2

    @respx.mock
    async def test_empty_results(self, token: str):
        respx.post(f"{BASE_URL}/crm/v3/objects/deals/search").mock(
            return_value=httpx.Response(200, json={"results": [], "paging": {}})
        )

        from datetime import datetime
        async with HubSpotClient(token=token) as client:
            deals = [d async for d in client.search_won_deals(since=datetime(2025, 1, 1))]

        assert deals == []


class TestGetDeal:
    @respx.mock
    async def test_returns_deal_properties(self, token: str):
        respx.get(f"{BASE_URL}/crm/v3/objects/deals/100").mock(
            return_value=httpx.Response(200, json={
                "id": "100",
                "properties": {"dealname": "ACME - CFO", "amount": "5000"},
            })
        )

        async with HubSpotClient(token=token) as client:
            data = await client.get_deal("100")

        assert data["id"] == "100"
        assert data["properties"]["dealname"] == "ACME - CFO"
        assert data["properties"]["amount"] == "5000"


class TestGetCompany:
    @respx.mock
    async def test_returns_company_properties(self, token: str):
        respx.get(f"{BASE_URL}/crm/v3/objects/companies/123").mock(
            return_value=httpx.Response(200, json={
                "id": "123",
                "properties": {"name": "ACME SL", "nif": "B12345678"},
            })
        )

        async with HubSpotClient(token=token) as client:
            data = await client.get_company("123")

        assert data["properties"]["name"] == "ACME SL"
        assert data["properties"]["nif"] == "B12345678"


class TestGetDealCompanyId:
    @respx.mock
    async def test_returns_company_id(self, token: str):
        respx.get(f"{BASE_URL}/crm/v3/objects/deals/100/associations/companies").mock(
            return_value=httpx.Response(200, json={
                "results": [{"toObjectId": 999}],
            })
        )

        async with HubSpotClient(token=token) as client:
            result = await client.get_deal_company_id("100")

        assert result == "999"

    @respx.mock
    async def test_returns_none_when_no_company(self, token: str):
        respx.get(f"{BASE_URL}/crm/v3/objects/deals/100/associations/companies").mock(
            return_value=httpx.Response(200, json={"results": []})
        )

        async with HubSpotClient(token=token) as client:
            result = await client.get_deal_company_id("100")

        assert result is None


class TestGetContact:
    @respx.mock
    async def test_returns_contact_properties(self, token: str):
        respx.get(f"{BASE_URL}/crm/v3/objects/contacts/456").mock(
            return_value=httpx.Response(200, json={
                "id": "456",
                "properties": {
                    "firstname": "Juan",
                    "lastname": "García",
                    "email": "juan@example.com",
                    "cfo_asignado": "789",
                },
            })
        )

        async with HubSpotClient(token=token) as client:
            data = await client.get_contact("456")

        assert data["properties"]["firstname"] == "Juan"
        assert data["properties"]["cfo_asignado"] == "789"


class TestRetryLogic:
    @respx.mock
    async def test_retries_on_429(self, token: str):
        """Verifica que reintenta ante un 429 y luego tiene éxito."""
        route = respx.get(f"{BASE_URL}/crm/v3/objects/companies/123")
        route.side_effect = [
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"id": "123", "properties": {}}),
        ]

        async with HubSpotClient(token=token) as client:
            data = await client.get_company("123")

        assert data["id"] == "123"
        assert route.call_count == 2

    @respx.mock
    async def test_retries_on_500(self, token: str):
        route = respx.get(f"{BASE_URL}/crm/v3/objects/companies/123")
        route.side_effect = [
            httpx.Response(500),
            httpx.Response(200, json={"id": "123", "properties": {}}),
        ]

        async with HubSpotClient(token=token) as client:
            data = await client.get_company("123")

        assert data["id"] == "123"
        assert route.call_count == 2

    @respx.mock
    async def test_raises_on_4xx(self, token: str):
        respx.get(f"{BASE_URL}/crm/v3/objects/companies/123").mock(
            return_value=httpx.Response(404, text="Not found")
        )

        async with HubSpotClient(token=token) as client:
            with pytest.raises(HubSpotError) as exc_info:
                await client.get_company("123")

        assert exc_info.value.status_code == 404

    @respx.mock
    async def test_raises_after_max_retries(self, token: str):
        respx.get(f"{BASE_URL}/crm/v3/objects/companies/123").mock(
            return_value=httpx.Response(500)
        )

        async with HubSpotClient(token=token) as client:
            with pytest.raises(HubSpotError, match="Max reintentos"):
                await client.get_company("123")
