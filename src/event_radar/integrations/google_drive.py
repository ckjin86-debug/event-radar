"""Google Drive OAuth 2.0 backup client with non-fatal degradation."""

from __future__ import annotations
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Optional
import requests


OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"


@dataclass
class BackupReport:
    success: bool
    uploaded_files: list[str] = field(default_factory=list)
    failed_files: list[str] = field(default_factory=list)
    message: str = ""


class DriveBackupClient:
    """Client for uploading and updating files in Google Drive using OAuth refresh token."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        folder_id: str = "",
        timeout: int = 15,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.folder_id = folder_id
        self.timeout = timeout
        self._access_token: Optional[str] = None

    def get_access_token(self) -> str:
        """Exchange refresh token for a short-lived access token."""
        if self._access_token:
            return self._access_token

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }
        resp = requests.post(OAUTH_TOKEN_URL, data=payload, timeout=self.timeout)
        if resp.status_code != 200:
            raise ConnectionError(f"OAuth token refresh failed: {resp.text}")

        data = resp.json()
        self._access_token = data["access_token"]
        return self._access_token

    def find_file(self, filename: str) -> Optional[str]:
        """Search for an existing file by name in the target folder."""
        token = self.get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        query = f"name = '{filename}' and trashed = false"
        if self.folder_id:
            query += f" and '{self.folder_id}' in parents"

        params = {"q": query, "fields": "files(id, name)"}
        resp = requests.get(DRIVE_FILES_URL, headers=headers, params=params, timeout=self.timeout)
        if resp.status_code == 200:
            files = resp.json().get("files", [])
            if files:
                return files[0]["id"]
        return None

    def upload_file(self, file_path: Path) -> dict:
        """Upload or update file in Drive."""
        token = self.get_access_token()
        existing_id = self.find_file(file_path.name)
        file_bytes = file_path.read_bytes()

        if existing_id:
            # Update existing file content
            url = f"{DRIVE_UPLOAD_URL}/{existing_id}?uploadType=media"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "text/csv",
            }
            resp = requests.patch(url, headers=headers, data=file_bytes, timeout=self.timeout)
            if resp.status_code == 200:
                return {"status": "UPDATED", "file_id": existing_id}
            raise ConnectionError(f"Drive patch failed: {resp.text}")

        # Upload new multipart file with metadata
        metadata = {"name": file_path.name}
        if self.folder_id:
            metadata["parents"] = [self.folder_id]

        url = f"{DRIVE_UPLOAD_URL}?uploadType=multipart"
        headers = {"Authorization": f"Bearer {token}"}
        files = {
            "data": ("metadata", json.dumps(metadata), "application/json; charset=UTF-8"),
            "file": (file_path.name, file_bytes, "text/csv"),
        }
        resp = requests.post(url, headers=headers, files=files, timeout=self.timeout)
        if resp.status_code in (200, 201):
            return {"status": "UPLOADED", "file_id": resp.json().get("id", "")}
        raise ConnectionError(f"Drive upload failed: {resp.text}")


def backup_files_to_drive(
    file_paths: list[Path],
    folder_id: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    refresh_token: Optional[str] = None,
) -> BackupReport:
    """Safely back up canonical and derived files to Google Drive with non-fatal degradation."""
    folder_id = folder_id or os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
    client_id = client_id or os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET", "")
    refresh_token = refresh_token or os.getenv("GOOGLE_REFRESH_TOKEN", "")

    if not all([folder_id, client_id, client_secret, refresh_token]):
        # Non-fatal warning
        return BackupReport(
            success=False,
            message="Skipping Google Drive backup: Missing credentials or GOOGLE_DRIVE_FOLDER_ID.",
        )

    try:
        client = DriveBackupClient(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            folder_id=folder_id,
        )

        uploaded = []
        failed = []
        for path in file_paths:
            if not path.exists():
                continue
            try:
                res = client.upload_file(path)
                uploaded.append(f"{path.name} ({res['status']})")
            except Exception as e:
                failed.append(f"{path.name}: {str(e)}")

        return BackupReport(
            success=len(failed) == 0,
            uploaded_files=uploaded,
            failed_files=failed,
            message=f"Uploaded {len(uploaded)} files to Drive folder {folder_id}." if not failed else f"Uploaded {len(uploaded)}, {len(failed)} failed.",
        )

    except Exception as e:
        return BackupReport(
            success=False,
            message=f"Google Drive backup warning: {str(e)}",
        )
