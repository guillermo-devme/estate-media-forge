"""OpenAPI polish: HMAC security scheme, tags, enums, examples, lifecycle docs."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(scope="module")
def schema():
    return create_app().openapi()


def test_hmac_security_scheme_over_headers(schema):
    schemes = schema["components"]["securitySchemes"]
    header_names = {s["name"] for s in schemes.values()}
    assert header_names == {
        "X-Service-Key",
        "X-Member-Id",
        "X-Timestamp",
        "X-Nonce",
        "X-Signature",
    }
    assert all(s["type"] == "apiKey" and s["in"] == "header" for s in schemes.values())


def test_protected_routes_require_all_headers_open_routes_do_not(schema):
    secured = schema["paths"]["/v1/media-kit"]["post"]
    assert len(secured["security"][0]) == 5
    assert "security" not in schema["paths"]["/health"]["get"]
    assert "security" not in schema["paths"]["/v1/ready"]["get"]


def test_all_tags_present(schema):
    names = {t["name"] for t in schema["tags"]}
    assert names == {
        "quotation",
        "pricing",
        "media-kit",
        "upscale",
        "video",
        "jobs",
        "metrics",
        "health",
    }


def test_enums_render_allowed_values(schema):
    defs = schema["components"]["schemas"]
    assert defs["AspectRatio"]["enum"] == ["1:1", "9:16", "16:9"]
    assert defs["ServiceType"]["enum"] == ["upscale", "media_kit", "image_to_video"]
    assert defs["JobStatus"]["enum"] == ["queued", "running", "partial", "completed", "failed"]
    assert defs["FalStage"]["enum"] == ["upscale", "outpaint", "i2v"]


def test_description_has_lifecycle_and_how_it_works(schema):
    desc = schema["info"]["description"]
    assert "Wix decrement (the hold)" in desc
    assert "How quotation + polling works" in desc
    assert schema["info"]["summary"]


def test_examples_present(schema):
    assert "examples" in schema["components"]["schemas"]["MediaKitRequest"]


def test_docs_endpoints_serve():
    client = TestClient(create_app())
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").status_code == 200
