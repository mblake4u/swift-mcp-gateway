# ADR-002: Swift MCP Gateway — Stack and Transport

**Date:** 2026-04-29
**Status:** Accepted
**Deciders:** Michael Blake

---

## Context

Phase 2 of SwiftOps is to expose Swift Messaging API operations as MCP tools
so that Claude can interact with Swift Alliance Cloud conversationally — listing
distributions, downloading messages, sending FIN/InterAct messages — with auth
handled transparently.

Key constraints:
- Auth complexity (OAuth JWT-Bearer + `X-SWIFT-Signature`) must not leak into
  the MCP layer. The existing token server already handles this via `/proxy`.
- The server must be accessible from a second host (Windows staging lab), so
  stdio transport (which ties the server to the Claude Desktop process) is
  unsuitable.
- Must fit the existing Docker-compose + port-per-service pattern.

---

## Decision

**Framework:** `fastmcp` (Python)  
**Transport:** Streamable HTTP (MCP spec 2025-03-26) — `POST /mcp`  
**Port:** 85 (external) / 8080 (internal, consistent with all other services)  
**Auth layer:** None in the MCP gateway. All API calls proxy through
`swift-token-server:8080/proxy`, which injects Bearer tokens and signatures.

---

## Options Considered

| Option | Notes |
|---|---|
| `stdio` + fastmcp | Simplest. Claude Desktop spawns the process locally. Ruled out: cannot be shared across hosts. |
| HTTP/SSE + fastmcp | SSE transport (older MCP spec). Works but deprecated in favour of streamable HTTP. |
| **Streamable HTTP + fastmcp** ✅ | Current MCP spec. One URL swap promotes dev → staging → prod. Supported by Claude Desktop ≥ 0.9. |
| Raw MCP SDK (Python) | Lower-level; more boilerplate for no benefit at this scale. |
| TypeScript MCP SDK | No reason to add a second language to the stack. |

---

## Consequences

- Claude Desktop config points at `http://localhost:85/mcp` in dev,
  `http://<staging-ip>:85/mcp` in staging.
- The `/proxy` endpoint in `swift-token-server` becomes the sole integration
  point — the MCP gateway is credential-free.
- FileAct (two-phase upload/download) is explicitly out of scope for v1 due to
  its stateful handshake. It can be added in a future ADR.
- The gateway is stateless; horizontal scaling is trivially possible.
