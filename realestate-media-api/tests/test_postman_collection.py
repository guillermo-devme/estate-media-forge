"""Guard the Postman collection: valid JSON, signing script, golden-path requests."""

from __future__ import annotations

import json
from pathlib import Path

POSTMAN_DIR = Path(__file__).parent / "postman"


def _load(name: str) -> dict:
    return json.loads((POSTMAN_DIR / name).read_text())


def test_collection_has_signing_prerequest_and_golden_path():
    collection = _load("realestate-media-api.postman_collection.json")

    # Collection-level pre-request signs with the HMAC headers.
    prerequest = next(e for e in collection["event"] if e["listen"] == "prerequest")
    script = "\n".join(prerequest["script"]["exec"])
    for header in ("X-Service-Key", "X-Member-Id", "X-Timestamp", "X-Nonce", "X-Signature"):
        assert header in script
    assert "HmacSHA256" in script and "SHA256" in script

    names = [item["name"] for item in collection["item"]]
    assert any("Health" in n for n in names)
    assert any("Quotation" in n for n in names)
    assert any("Media Kit" in n for n in names)
    assert any("Poll Job" in n for n in names)
    assert any("401" in n for n in names)
    assert any("404" in n for n in names)
    assert any("Metrics" in n for n in names)


def test_environment_has_required_vars():
    env = _load("realestate-media-api.local.postman_environment.json")
    keys = {v["key"] for v in env["values"]}
    assert {
        "base_url",
        "service_key",
        "service_hmac_secret",
        "member_id",
        "other_member_id",
        "client_ref",
        "job_id",
    } <= keys
