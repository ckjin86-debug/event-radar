from pathlib import Path
import pytest
from event_radar.integrations.google_drive import (
    DriveBackupClient,
    BackupReport,
    backup_files_to_drive,
)


def test_drive_client_token_refresh(monkeypatch):
    client = DriveBackupClient(
        client_id="dummy_client",
        client_secret="dummy_secret",
        refresh_token="dummy_refresh",
    )

    class MockResponse:
        status_code = 200

        def json(self):
            return {"access_token": "mocked_access_token_123"}

    monkeypatch.setattr("requests.post", lambda *args, **kwargs: MockResponse())
    token = client.get_access_token()
    assert token == "mocked_access_token_123"


def test_drive_backup_is_non_fatal_on_missing_credentials():
    # If environment variables are empty or missing, it returns warning report, does NOT crash
    report = backup_files_to_drive(
        file_paths=[Path("data/canonical/events.csv")],
        folder_id="",
        client_id="",
        client_secret="",
        refresh_token="",
    )

    assert isinstance(report, BackupReport)
    assert report.success is False
    assert "missing credentials" in report.message.lower()


def test_drive_upload_file_mocked(tmp_path, monkeypatch):
    test_file = tmp_path / "test.csv"
    test_file.write_text("a,b,c\n1,2,3\n", encoding="utf-8")

    client = DriveBackupClient(
        client_id="dummy_client",
        client_secret="dummy_secret",
        refresh_token="dummy_refresh",
        folder_id="folder_123",
    )

    # Mock token
    monkeypatch.setattr(client, "get_access_token", lambda: "mock_token")

    # Mock search: no existing file
    class MockSearchResp:
        status_code = 200

        def json(self):
            return {"files": []}

    # Mock upload: success
    class MockUploadResp:
        status_code = 200

        def json(self):
            return {"id": "file_id_999", "name": "test.csv"}

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: MockSearchResp())
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: MockUploadResp())

    report = client.upload_file(test_file)
    assert report["status"] == "UPLOADED"
    assert report["file_id"] == "file_id_999"
