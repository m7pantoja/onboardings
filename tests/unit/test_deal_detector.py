"""Tests para DealDetector."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from src.clients.hubspot import BASE_URL, HubSpotClient
from src.models.deal import EnrichedDeal
from src.services.deal_detector import DealDetector


def _make_raw_deal(
    deal_id: str = "100",
    deal_name: str = "ACME SL - CFO",
    **extra_props: str,
) -> dict:
    """Helper para crear un raw deal de HubSpot."""
    props = {
        "dealname": deal_name,
        "amount": "5000",
        "hubspot_owner_id": "111",
        "pipeline": "20024183",
        "dealstage": "48577422",
        "closedate": "1735689600000",  # 2025-01-01
        **extra_props,
    }
    return {"id": deal_id, "properties": props}


@pytest.fixture
def mock_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_by_deal_id.return_value = None  # no procesado por defecto
    return repo


def _mock_search(deals: list[dict]) -> None:
    """Mockea el endpoint de búsqueda de deals."""
    respx.post(f"{BASE_URL}/crm/v3/objects/deals/search").mock(
        return_value=httpx.Response(200, json={
            "results": deals,
            "paging": {},
        })
    )


def _mock_associations_and_data(
    deal_id: str = "100",
    company_id: str = "500",
    contact_id: str = "600",
    company_props: dict | None = None,
    contact_props: dict | None = None,
) -> None:
    """Mockea las llamadas de asociaciones + datos de empresa y contacto."""
    respx.get(f"{BASE_URL}/crm/v3/objects/deals/{deal_id}/associations/companies").mock(
        return_value=httpx.Response(200, json={
            "results": [{"toObjectId": int(company_id)}],
        })
    )
    respx.get(f"{BASE_URL}/crm/v3/objects/companies/{company_id}").mock(
        return_value=httpx.Response(200, json={
            "id": company_id,
            "properties": company_props or {
                "name": "ACME SL",
                "nif": "B12345678",
                "phone": "+34 911 000 000",
                "generic_email": "info@acme.com",
                "address": "Calle Mayor 1",
                "city": "Madrid",
                "state": "Madrid",
                "zip": "28001",
                "country": "Spain",
                "website": "acme.com",
                "tl_holded_id": None,
                "tl_synced_holded": None,
            },
        })
    )
    respx.get(
        f"{BASE_URL}/crm/v3/objects/companies/{company_id}/associations/contacts"
    ).mock(
        return_value=httpx.Response(200, json={
            "results": [{"toObjectId": int(contact_id)}],
        })
    )
    respx.get(f"{BASE_URL}/crm/v3/objects/contacts/{contact_id}").mock(
        return_value=httpx.Response(200, json={
            "id": contact_id,
            "properties": contact_props or {
                "firstname": "Juan",
                "lastname": "García",
                "email": "juan@acme.com",
                "phone": "+34 600 000 000",
                "mobilephone": None,
                "nombre_y_apellidos": None,
                "cargo_en_empresa": "CEO",
                "nif": "B12345678",
                "cfo_asignado": "789",
                "tecnico_enisa_asignado": None,
            },
        })
    )


def _mock_get_deal(
    deal_id: str = "100",
    deal_name: str = "ACME SL - CFO",
    **extra_props: str,
) -> None:
    """Mockea GET /crm/v3/objects/deals/{deal_id}."""
    raw = _make_raw_deal(deal_id=deal_id, deal_name=deal_name, **extra_props)
    respx.get(f"{BASE_URL}/crm/v3/objects/deals/{deal_id}").mock(
        return_value=httpx.Response(200, json=raw)
    )


class TestEnrichDealById:
    @respx.mock
    async def test_enriches_deal_successfully(self, mock_repo: AsyncMock):
        _mock_get_deal()
        _mock_associations_and_data()

        async with HubSpotClient(token="test") as client:
            detector = DealDetector(client=client, repository=mock_repo)
            result = await detector.enrich_deal_by_id(100)

        assert result is not None
        assert isinstance(result, EnrichedDeal)
        assert result.deal_id == 100
        assert result.company_name == "ACME SL"
        assert result.service_name == "CFO"
        assert result.company.nif == "B12345678"
        assert result.contact_person.firstname == "Juan"
        assert len(result.technicians) == 1

    @respx.mock
    async def test_returns_none_for_unparseable_name(self, mock_repo: AsyncMock):
        _mock_get_deal(deal_name="SIN SEPARADOR")

        async with HubSpotClient(token="test") as client:
            detector = DealDetector(client=client, repository=mock_repo)
            result = await detector.enrich_deal_by_id(100)

        assert result is None

    @respx.mock
    async def test_returns_none_when_no_company(self, mock_repo: AsyncMock):
        _mock_get_deal()
        respx.get(f"{BASE_URL}/crm/v3/objects/deals/100/associations/companies").mock(
            return_value=httpx.Response(200, json={"results": []})
        )

        async with HubSpotClient(token="test") as client:
            detector = DealDetector(client=client, repository=mock_repo)
            result = await detector.enrich_deal_by_id(100)

        assert result is None

    @respx.mock
    async def test_returns_none_when_no_contacts(self, mock_repo: AsyncMock):
        _mock_get_deal()
        respx.get(f"{BASE_URL}/crm/v3/objects/deals/100/associations/companies").mock(
            return_value=httpx.Response(200, json={
                "results": [{"toObjectId": 500}],
            })
        )
        respx.get(f"{BASE_URL}/crm/v3/objects/companies/500").mock(
            return_value=httpx.Response(200, json={
                "id": "500", "properties": {"name": "ACME SL"},
            })
        )
        respx.get(f"{BASE_URL}/crm/v3/objects/companies/500/associations/contacts").mock(
            return_value=httpx.Response(200, json={"results": []})
        )

        async with HubSpotClient(token="test") as client:
            detector = DealDetector(client=client, repository=mock_repo)
            result = await detector.enrich_deal_by_id(100)

        assert result is None


class TestDealDetector:
    @respx.mock
    async def test_detects_new_deal(self, mock_repo: AsyncMock):
        _mock_search([_make_raw_deal()])
        _mock_associations_and_data()

        async with HubSpotClient(token="test") as client:
            detector = DealDetector(client=client, repository=mock_repo)
            result = await detector.detect_new_deals()

        assert len(result) == 1
        deal = result[0]
        assert isinstance(deal, EnrichedDeal)
        assert deal.deal_id == 100
        assert deal.company_name == "ACME SL"
        assert deal.service_name == "CFO"
        assert deal.company.nif == "B12345678"
        assert deal.company.city == "Madrid"
        assert deal.contact_person.firstname == "Juan"
        assert deal.contact_person.job_title == "CEO"
        assert len(deal.technicians) == 1
        assert deal.technicians[0].hubspot_tec_id == "789"

    @respx.mock
    async def test_skips_already_processed_deal(self, mock_repo: AsyncMock):
        mock_repo.get_by_deal_id.return_value = MagicMock()  # ya existe
        _mock_search([_make_raw_deal()])

        async with HubSpotClient(token="test") as client:
            detector = DealDetector(client=client, repository=mock_repo)
            result = await detector.detect_new_deals()

        assert result == []
        # No debe haber llamado a associations ni a company/contact
        assert len(respx.calls) == 1  # solo la búsqueda

    @respx.mock
    async def test_skips_unparseable_deal_name(self, mock_repo: AsyncMock):
        _mock_search([_make_raw_deal(deal_name="SIN SEPARADOR")])

        async with HubSpotClient(token="test") as client:
            detector = DealDetector(client=client, repository=mock_repo)
            result = await detector.detect_new_deals()

        assert result == []

    @respx.mock
    async def test_skips_deal_without_company(self, mock_repo: AsyncMock):
        _mock_search([_make_raw_deal()])
        respx.get(f"{BASE_URL}/crm/v3/objects/deals/100/associations/companies").mock(
            return_value=httpx.Response(200, json={"results": []})
        )

        async with HubSpotClient(token="test") as client:
            detector = DealDetector(client=client, repository=mock_repo)
            result = await detector.detect_new_deals()

        assert result == []

    @respx.mock
    async def test_skips_company_without_contacts(self, mock_repo: AsyncMock):
        _mock_search([_make_raw_deal()])
        respx.get(f"{BASE_URL}/crm/v3/objects/deals/100/associations/companies").mock(
            return_value=httpx.Response(200, json={
                "results": [{"toObjectId": 500}],
            })
        )
        respx.get(f"{BASE_URL}/crm/v3/objects/companies/500").mock(
            return_value=httpx.Response(200, json={
                "id": "500", "properties": {"name": "ACME SL"},
            })
        )
        respx.get(f"{BASE_URL}/crm/v3/objects/companies/500/associations/contacts").mock(
            return_value=httpx.Response(200, json={"results": []})
        )

        async with HubSpotClient(token="test") as client:
            detector = DealDetector(client=client, repository=mock_repo)
            result = await detector.detect_new_deals()

        assert result == []

    @respx.mock
    async def test_holded_id_preserved_when_exists(self, mock_repo: AsyncMock):
        """Si la empresa ya tiene tl_holded_id, se preserva en CompanyInfo."""
        _mock_search([_make_raw_deal()])
        _mock_associations_and_data(
            company_props={
                "name": "ACME SL",
                "nif": "B12345678",
                "tl_holded_id": "abc123_holded",
                "tl_synced_holded": "true",
            },
        )

        async with HubSpotClient(token="test") as client:
            detector = DealDetector(client=client, repository=mock_repo)
            result = await detector.detect_new_deals()

        assert len(result) == 1
        assert result[0].company.holded_id == "abc123_holded"

    @respx.mock
    async def test_multiple_deals(self, mock_repo: AsyncMock):
        deals = [
            _make_raw_deal(deal_id="100", deal_name="ACME SL - CFO"),
            _make_raw_deal(deal_id="200", deal_name="BETA SL - ENISA"),
        ]
        _mock_search(deals)

        # Mock para deal 100
        _mock_associations_and_data(deal_id="100", company_id="500", contact_id="600")
        # Mock para deal 200
        _mock_associations_and_data(deal_id="200", company_id="501", contact_id="601")

        async with HubSpotClient(token="test") as client:
            detector = DealDetector(client=client, repository=mock_repo)
            result = await detector.detect_new_deals()

        assert len(result) == 2
        assert result[0].deal_id == 100
        assert result[1].deal_id == 200
