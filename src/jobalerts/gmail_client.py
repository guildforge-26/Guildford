"""Shared Gmail OAuth client, used by the email-alert collector (read-only)
and the digest drafter (compose-only -- drafts, never sends).

First run opens a browser for a one-time consent screen; the resulting
token is cached at settings.gmail_token_path so later runs (including cron)
are non-interactive. See README.md "Authorize Gmail".
"""
from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import Settings

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


def get_gmail_service(settings: Settings):
    creds = None
    if settings.gmail_token_path.exists():
        creds = Credentials.from_authorized_user_file(str(settings.gmail_token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not settings.gmail_credentials_path.exists():
                raise FileNotFoundError(
                    f"Gmail OAuth client file not found at {settings.gmail_credentials_path}. "
                    "Create one in Google Cloud Console (OAuth client, Desktop app) and download it there."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(settings.gmail_credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)
        settings.gmail_token_path.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)
