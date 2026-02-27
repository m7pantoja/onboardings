"""Tests para los steps del pipeline de onboarding."""

from unittest.mock import AsyncMock

import pytest

from src.models.deal import CompanyInfo, ContactPersonInfo
from src.models.enums import StepName
from src.models.sheets import Department, TeamMember
from src.steps.base import StepContext
from src.steps.create_drive_folder import CreateDriveFolderStep
from src.steps.create_holded_contact import CreateHoldedContactStep, _country_to_code
from src.steps.notify_slack import NotifySlackStep, _build_message
from src.steps.send_email import SendEmailStep, _build_email_html


# ── Fixtures ─────────────────────────────────────────────────────


def _make_company(**overrides) -> CompanyInfo:
    defaults = dict(
        company_id="comp_123",
        name="Acme Corp",
        nif="B12345678",
        email="info@acme.com",
        phone="+34612345678",
        website="https://acme.com",
        address="Calle Mayor 1",
        city="Madrid",
        state="Madrid",
        zip_code="28001",
        country="Spain",
        holded_id=None,
        drive_folder_id=None,
        drive_folder_url=None,
    )
    defaults.update(overrides)
    return CompanyInfo(**defaults)


def _make_contact(**overrides) -> ContactPersonInfo:
    defaults = dict(
        contact_id="cont_456",
        firstname="Juan",
        lastname="García",
        full_name="Juan García López",
        email="juan@acme.com",
        phone="+34612345679",
        mobile=None,
        job_title="CEO",
    )
    defaults.update(overrides)
    return ContactPersonInfo(**defaults)


def _make_technician(**overrides) -> TeamMember:
    defaults = dict(
        hubspot_tec_id="tec_789",
        slack_id="U06MRGSBQS3",
        email="esther@leanfinance.es",
        nombre_completo="Esther Punzano López",
        nombre_corto="Esther",
        department=Department.AS,
        is_responsable=True,
    )
    defaults.update(overrides)
    return TeamMember(**defaults)


def _make_context(**overrides) -> StepContext:
    defaults = dict(
        deal_id=12345,
        deal_name="Acme Corp - Asesoramiento fiscal y contable",
        company_name="Acme Corp",
        service_name="Asesoramiento fiscal y contable",
        hubspot_owner_id=1404036103,
        company=_make_company(),
        contact_person=_make_contact(),
        department=Department.AS,
        technician=_make_technician(),
        hubspot_portal_id=6575051,
    )
    defaults.update(overrides)
    return StepContext(**defaults)


# ── Tests CreateDriveFolderStep ──────────────────────────────────


class TestCreateDriveFolderStep:
    async def test_creates_folder_and_subfolder(self) -> None:
        drive = AsyncMock()
        hubspot = AsyncMock()
        drive.find_or_create_folder = AsyncMock(side_effect=["folder_abc", "subfolder_xyz"])

        step = CreateDriveFolderStep(drive_client=drive, hubspot_client=hubspot)
        ctx = _make_context()

        result = await step.run(ctx)

        assert result.success
        assert ctx.drive_folder_id == "folder_abc"
        assert ctx.drive_subfolder_id == "subfolder_xyz"
        # Write-back a HubSpot
        hubspot.update_company.assert_called_once()

    async def test_skips_when_folder_and_subfolder_exist(self) -> None:
        drive = AsyncMock()
        hubspot = AsyncMock()
        drive.find_folder = AsyncMock(return_value="existing_sub")

        step = CreateDriveFolderStep(drive_client=drive, hubspot_client=hubspot)
        ctx = _make_context(
            company=_make_company(drive_folder_id="existing_folder", drive_folder_url="https://drive.google.com/...")
        )

        result = await step.run(ctx)

        assert result.success
        assert result.data.get("skipped") is True
        assert ctx.drive_folder_id == "existing_folder"
        assert ctx.drive_subfolder_id == "existing_sub"

    async def test_no_subfolder_for_da_department(self) -> None:
        drive = AsyncMock()
        hubspot = AsyncMock()
        drive.find_or_create_folder = AsyncMock(return_value="folder_da")

        step = CreateDriveFolderStep(drive_client=drive, hubspot_client=hubspot)
        ctx = _make_context(department=Department.DA)

        result = await step.run(ctx)

        assert result.success
        assert ctx.drive_folder_id == "folder_da"
        assert ctx.drive_subfolder_id is None
        # Solo se creó 1 carpeta (sin subcarpeta)
        assert drive.find_or_create_folder.call_count == 1

    async def test_step_name(self) -> None:
        step = CreateDriveFolderStep(drive_client=AsyncMock(), hubspot_client=AsyncMock())
        assert step.name == StepName.CREATE_DRIVE_FOLDER


# ── Tests CreateHoldedContactStep ────────────────────────────────


class TestCreateHoldedContactStep:
    async def test_creates_contact(self) -> None:
        holded = AsyncMock()
        hubspot = AsyncMock()
        holded.create_contact = AsyncMock(return_value="holded_abc")

        step = CreateHoldedContactStep(holded_client=holded, hubspot_client=hubspot)
        ctx = _make_context()

        result = await step.run(ctx)

        assert result.success
        assert ctx.holded_contact_id == "holded_abc"
        holded.create_contact.assert_called_once()
        hubspot.update_company.assert_called_once()

    async def test_skips_when_holded_exists(self) -> None:
        holded = AsyncMock()
        hubspot = AsyncMock()

        step = CreateHoldedContactStep(holded_client=holded, hubspot_client=hubspot)
        ctx = _make_context(company=_make_company(holded_id="existing_holded_id"))

        result = await step.run(ctx)

        assert result.success
        assert result.data.get("skipped") is True
        assert ctx.holded_contact_id == "existing_holded_id"
        holded.create_contact.assert_not_called()

    async def test_payload_includes_contact_person(self) -> None:
        holded = AsyncMock()
        hubspot = AsyncMock()
        holded.create_contact = AsyncMock(return_value="holded_123")

        step = CreateHoldedContactStep(holded_client=holded, hubspot_client=hubspot)
        ctx = _make_context()
        await step.run(ctx)

        payload = holded.create_contact.call_args[0][0]
        assert payload["name"] == "Acme Corp"
        assert payload["type"] == "client"
        assert payload["code"] == "B12345678"
        assert "contactPersons" in payload
        assert payload["contactPersons"][0]["name"] == "Juan García López"

    async def test_step_name(self) -> None:
        step = CreateHoldedContactStep(holded_client=AsyncMock(), hubspot_client=AsyncMock())
        assert step.name == StepName.CREATE_HOLDED_CONTACT


class TestCountryToCode:
    def test_spain(self) -> None:
        assert _country_to_code("Spain") == "ES"
        assert _country_to_code("España") == "ES"
        assert _country_to_code("SPAIN") == "ES"

    def test_default_is_spain(self) -> None:
        assert _country_to_code(None) == "ES"
        assert _country_to_code("") == "ES"
        assert _country_to_code("Unknown Country") == "ES"


# ── Tests NotifySlackStep ────────────────────────────────────────


class TestNotifySlackStep:
    async def test_sends_dm(self) -> None:
        slack = AsyncMock()
        slack.send_dm = AsyncMock(return_value="1234567890.123")

        step = NotifySlackStep(slack_client=slack)
        ctx = _make_context()

        result = await step.run(ctx)

        assert result.success
        slack.send_dm.assert_called_once_with(
            user_id="U06MRGSBQS3",
            text=_build_message(ctx),
        )

    async def test_fails_without_slack_id(self) -> None:
        slack = AsyncMock()

        step = NotifySlackStep(slack_client=slack)
        ctx = _make_context(technician=_make_technician(slack_id=None))

        result = await step.run(ctx)

        assert not result.success
        assert "slack_id" in result.error

    async def test_step_name(self) -> None:
        step = NotifySlackStep(slack_client=AsyncMock())
        assert step.name == StepName.NOTIFY_SLACK


class TestBuildSlackMessage:
    def test_includes_deal_info(self) -> None:
        ctx = _make_context()
        msg = _build_message(ctx)
        assert "Esther" in msg
        assert "Acme Corp - Asesoramiento fiscal y contable" in msg
        assert "Acme Corp" in msg
        assert "bandeja de entrada" in msg


# ── Tests SendEmailStep ──────────────────────────────────────────


class TestSendEmailStep:
    async def test_sends_email(self) -> None:
        gmail = AsyncMock()
        gmail.send_email = AsyncMock(return_value="msg_abc")

        step = SendEmailStep(gmail_client=gmail)
        ctx = _make_context(
            drive_folder_url="https://drive.google.com/drive/folders/abc",
            holded_contact_url="https://app.holded.com/contacts/xyz",
        )

        result = await step.run(ctx)

        assert result.success
        gmail.send_email.assert_called_once()
        call_kwargs = gmail.send_email.call_args[1]
        assert call_kwargs["to"] == "esther@leanfinance.es"
        assert "Acme Corp" in call_kwargs["subject"]

    async def test_fails_without_technician(self) -> None:
        gmail = AsyncMock()

        step = SendEmailStep(gmail_client=gmail)
        ctx = _make_context(technician=None)

        result = await step.run(ctx)

        assert not result.success
        assert "técnico" in result.error

    async def test_step_name(self) -> None:
        step = SendEmailStep(gmail_client=AsyncMock())
        assert step.name == StepName.SEND_EMAIL


class TestBuildEmailHtml:
    def test_includes_all_links(self) -> None:
        ctx = _make_context(
            drive_folder_url="https://drive.google.com/drive/folders/abc",
            holded_contact_url="https://app.holded.com/contacts/xyz",
            hubspot_portal_id=6575051,
        )
        html = _build_email_html(ctx)
        assert "drive.google.com" in html
        assert "app.holded.com" in html
        assert "app.hubspot.com" in html

    def test_includes_warning(self) -> None:
        ctx = _make_context()
        html = _build_email_html(ctx)
        assert "no ha sido supervisada" in html

    def test_includes_deal_info(self) -> None:
        ctx = _make_context()
        html = _build_email_html(ctx)
        assert "Acme Corp" in html
        assert "Asesoramiento fiscal y contable" in html
        assert "Asesoría fiscal" in html  # department label
