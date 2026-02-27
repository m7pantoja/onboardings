"""Registro de steps del pipeline de onboarding."""

from __future__ import annotations

from src.clients.gmail import GmailClient
from src.clients.google_drive import GoogleDriveClient
from src.clients.holded import HoldedClient
from src.clients.hubspot import HubSpotClient
from src.clients.slack import SlackClient
from src.steps.base import BaseStep
from src.steps.create_drive_folder import CreateDriveFolderStep
from src.steps.create_holded_contact import CreateHoldedContactStep
from src.steps.notify_slack import NotifySlackStep
from src.steps.send_email import SendEmailStep


def build_pipeline(
    drive_client: GoogleDriveClient,
    holded_client: HoldedClient,
    slack_client: SlackClient,
    gmail_client: GmailClient,
    hubspot_client: HubSpotClient,
) -> list[BaseStep]:
    """Devuelve la lista ordenada de steps del pipeline de onboarding.

    El orden es deliberado:
    1. Drive primero (el técnico necesita la carpeta para trabajar)
    2. Holded segundo (crear ficha antes de notificar)
    3. Slack tercero (aviso rápido al técnico)
    4. Email último (incluye los enlaces de Drive y Holded)
    """
    return [
        CreateDriveFolderStep(drive_client, hubspot_client),
        CreateHoldedContactStep(holded_client, hubspot_client),
        NotifySlackStep(slack_client),
        SendEmailStep(gmail_client),
    ]
