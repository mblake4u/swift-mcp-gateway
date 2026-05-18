"""
swift-mcp-gateway — MCP server exposing Swift Messaging API v2.1.0 operations.

Auth is fully transparent: all calls route through the token server's /proxy
endpoint, which handles OAuth token caching and X-SWIFT-Signature injection.

Transport: Streamable HTTP (MCP spec 2025-03-26) on 0.0.0.0:8080.
Claude Desktop config:  { "url": "http://localhost:85/mcp" }
"""

import os
import logging

import httpx
from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROXY_BASE_URL = os.getenv("PROXY_BASE_URL", "http://localhost:82/proxy").rstrip("/")
MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", "8080"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("swift-mcp-gateway")

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="Swift API Gateway",
    instructions=(
        "Tools for interacting with the Swift Alliance Cloud Messaging API v2.1.0 "
        "(sandbox). Covers distributions, FIN messages, and InterAct messages. "
        "Auth is handled transparently — no credentials required in tool calls."
    ),
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

TIMEOUT = httpx.Timeout(30.0)


def _get(path: str, params: dict | None = None) -> dict:
    """GET from the Swift proxy, return parsed JSON (or raise)."""
    url = f"{PROXY_BASE_URL}/{path.lstrip('/')}"
    logger.info("GET %s params=%s", url, params)
    resp = httpx.get(url, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, body: dict | None = None) -> dict | None:
    """POST to the Swift proxy. Returns parsed JSON or None for 204."""
    url = f"{PROXY_BASE_URL}/{path.lstrip('/')}"
    logger.info("POST %s", url)
    resp = httpx.post(url, json=body or {}, timeout=TIMEOUT)
    resp.raise_for_status()
    if resp.status_code == 204 or not resp.content:
        return {"status": "accepted", "http_status": resp.status_code}
    return resp.json()


# ---------------------------------------------------------------------------
# Distribution tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_distributions(limit: int = 100, offset: int = 0) -> dict:
    """List available distributions from Alliance Cloud.

    Args:
        limit:  Maximum number of results to return (default 100).
        offset: Pagination offset (default 0).
    """
    params: dict = {}
    if limit != 100:
        params["limit"] = limit
    if offset:
        params["offset"] = offset
    return _get("/distributions", params or None)


@mcp.tool()
def get_distribution(distribution_id: str) -> dict:
    """Retrieve a single distribution by ID.

    Args:
        distribution_id: The distribution ID returned by list_distributions.
    """
    return _get(f"/distributions/{distribution_id}")


@mcp.tool()
def ack_distribution(distribution_id: str) -> dict:
    """Acknowledge (ACK) a distribution, marking it as successfully processed.

    Args:
        distribution_id: The ID of the distribution to acknowledge.
    """
    return _post(f"/distributions/{distribution_id}/acks")


@mcp.tool()
def nak_distribution(distribution_id: str, reason: str = "") -> dict:
    """Negative-acknowledge (NAK) a distribution, rejecting it.

    Args:
        distribution_id: The ID of the distribution to reject.
        reason:          Optional textual reason for the NAK (max 255 chars).
    """
    body: dict = {}
    if reason:
        body["reason"] = reason[:255]
    return _post(f"/distributions/{distribution_id}/naks", body)


# ---------------------------------------------------------------------------
# FIN message tools
# ---------------------------------------------------------------------------


@mcp.tool()
def download_fin_messages(distribution_id: str) -> dict:
    """Download FIN (MT) messages for a specific distribution.

    The Swift API requires `distribution-id` as a query parameter on this
    endpoint — calls without it return HTTP 400 (SwAP504).

    Args:
        distribution_id: The distribution ID whose FIN messages should be
                         downloaded. Required (Swift API constraint).
    """
    return _get("/fin/messages", {"distribution-id": distribution_id})


@mcp.tool()
def download_fin_message(distribution_id: str) -> dict:
    """Download a single FIN message by its distribution ID.

    Args:
        distribution_id: The distribution ID of the FIN message to download.
    """
    return _get(f"/fin/messages/{distribution_id}")


@mcp.tool()
def send_fin_message(
    sender_reference: str,
    message_type: str,
    sender: str,
    receiver: str,
    payload: str,
) -> dict:
    """Send a FIN (MT) message to Alliance Cloud.

    Args:
        sender_reference: Unique back-office reference for reconciliation (max 70 chars).
                          Must be unique per institution (UUMID).
        message_type:     MT message type in format fin.<type>[.<variant>].
                          Examples: fin.103, fin.103.REMIT, fin.202, fin.202.COV
        sender:           BIC12 of the sending institution (format: <BIC8><LT><branch>).
        receiver:         BIC12 of the receiving institution.
        payload:          The MT message body (the block content as a string).
    """
    body = {
        "sender_reference": sender_reference,
        "message_type": message_type,
        "sender": sender,
        "receiver": receiver,
        "payload": payload,
    }
    return _post("/fin/messages", body)


# ---------------------------------------------------------------------------
# InterAct message tools
# ---------------------------------------------------------------------------


@mcp.tool()
def download_interact_messages(distribution_id: str) -> dict:
    """Download InterAct (MX) messages for a specific distribution.

    The Swift API requires `distribution-id` as a query parameter on this
    endpoint — calls without it return HTTP 400 (SwAP504).

    Args:
        distribution_id: The distribution ID whose InterAct messages should be
                         downloaded. Required (Swift API constraint).
    """
    return _get("/interact/messages", {"distribution-id": distribution_id})


@mcp.tool()
def download_interact_message(distribution_id: str) -> dict:
    """Download a single InterAct message by its distribution ID.

    Args:
        distribution_id: The distribution ID of the InterAct message to download.
    """
    return _get(f"/interact/messages/{distribution_id}")


@mcp.tool()
def send_interact_message(
    sender_reference: str,
    service_code: str,
    message_type: str,
    requestor: str,
    responder: str,
    payload: str,
    usage_identifier: str = "",
    format: str = "",
) -> dict:
    """Send an InterAct (MX) message to Alliance Cloud.

    Args:
        sender_reference: Unique back-office reference (max 70 chars).
        service_code:     SWIFTNet service code (max 30 chars).
        message_type:     MX message type in format <area>.<type>.<variant>.<version>.
                          Example: ifds.001.001.01
        requestor:        Distinguished name (DN) of the sending party.
        responder:        Distinguished name (DN) of the receiving party.
        payload:          The MX message body (XML string).
        usage_identifier: Optional usage identifier for business validation rules.
        format:           Optional message format (e.g. 'MX').
    """
    body: dict = {
        "sender_reference": sender_reference,
        "service_code": service_code,
        "message_type": message_type,
        "requestor": requestor,
        "responder": responder,
        "payload": payload,
    }
    if usage_identifier:
        body["usage_identifier"] = usage_identifier
    if format:
        body["format"] = format
    return _post("/interact/messages", body)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info(
        "Starting Swift MCP Gateway on %s:%s (proxy → %s)",
        MCP_HOST, MCP_PORT, PROXY_BASE_URL,
    )
    mcp.run(transport="streamable-http", host=MCP_HOST, port=MCP_PORT)
