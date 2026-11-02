import json
from pathlib import Path
import pytest


def test_site_json_files_exist_and_valid():
    site_dir = Path("site")
    events_file = site_dir / "data" / "events.json"
    details_file = site_dir / "data" / "event_details.json"
    meta_file = site_dir / "data" / "metadata.json"

    assert events_file.exists()
    assert details_file.exists()
    assert meta_file.exists()

    events = json.loads(events_file.read_text(encoding="utf-8"))
    assert isinstance(events, list)
    if events:
        first = events[0]
        required_keys = ["event_id", "d_day", "country", "ticker", "company", "event_type", "event_date", "relation_grade", "event_score", "status"]
        for k in required_keys:
            assert k in first

    details = json.loads(details_file.read_text(encoding="utf-8"))
    assert isinstance(details, dict)

    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    assert "generated_at" in meta
    assert "version" in meta


def test_no_secrets_in_site_directory():
    site_dir = Path("site")
    forbidden = ["api_key", "client_secret", "refresh_token", "password", "private_key"]

    for file_path in site_dir.rglob("*"):
        if file_path.is_file():
            content = file_path.read_text(encoding="utf-8", errors="ignore").lower()
            for secret_word in forbidden:
                assert secret_word not in content, f"Found secret word '{secret_word}' in public site file: {file_path}"
