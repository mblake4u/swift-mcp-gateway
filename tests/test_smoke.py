"""
Smoke tests for swift-mcp-gateway.

These tests exercise the tool functions directly (not via MCP transport)
by pointing PROXY_BASE_URL at the in-process mock proxy.
"""

import os
import importlib
import pytest


@pytest.fixture(autouse=True)
def patch_proxy(mock_proxy, monkeypatch):
    """Point the gateway at the mock proxy for every test."""
    monkeypatch.setenv("PROXY_BASE_URL", mock_proxy)
    # Re-import main so the module-level PROXY_BASE_URL is refreshed
    import app.main as m
    importlib.reload(m)
    return m


def test_list_distributions(patch_proxy):
    result = patch_proxy.list_distributions()
    assert isinstance(result, dict)
    assert result.get("mock") is True


def test_get_distribution(patch_proxy):
    result = patch_proxy.get_distribution("dist-001")
    assert isinstance(result, dict)
    assert "dist-001" in result.get("path", "")


def test_ack_distribution(patch_proxy):
    result = patch_proxy.ack_distribution("dist-001")
    assert isinstance(result, dict)


def test_nak_distribution(patch_proxy):
    result = patch_proxy.nak_distribution("dist-001", reason="Test NAK")
    assert isinstance(result, dict)


def test_download_fin_messages(patch_proxy):
    result = patch_proxy.download_fin_messages()
    assert isinstance(result, dict)
    assert result.get("mock") is True


def test_download_fin_message(patch_proxy):
    result = patch_proxy.download_fin_message("dist-fin-001")
    assert isinstance(result, dict)


def test_send_fin_message(patch_proxy):
    result = patch_proxy.send_fin_message(
        sender_reference="REF-001",
        message_type="fin.103",
        sender="BANKGB2LXXX",
        receiver="BANKUS33XXX",
        payload="{1:F01BANKGB2LAXXX0000000000}{2:I103BANKUS33XXXXN}{4:\n:20:REF-001\n-}",
    )
    assert isinstance(result, dict)
    assert result.get("accepted") is True


def test_download_interact_messages(patch_proxy):
    result = patch_proxy.download_interact_messages()
    assert isinstance(result, dict)


def test_send_interact_message(patch_proxy):
    result = patch_proxy.send_interact_message(
        sender_reference="MX-REF-001",
        service_code="swift.fin!p",
        message_type="ifds.001.001.01",
        requestor="cn=bankgb2l,o=bankgb2l,o=swift",
        responder="cn=bankus33,o=bankus33,o=swift",
        payload="<Document xmlns='urn:iso:std:iso:20022'>...</Document>",
    )
    assert isinstance(result, dict)
    assert result.get("accepted") is True
