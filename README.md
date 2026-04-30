# swift-mcp-gateway

An MCP (Model Context Protocol) server that exposes **Swift Alliance Cloud Messaging API v2.1.0** operations as Claude tools.

Part of the [SwiftOps](https://github.com/mblake4u/swiftops) open-source Swift API tooling stack.

---

## What it does

Connects Claude directly to the Swift API — ask Claude to list distributions, download FIN/InterAct messages, send messages, or ACK/NAK distributions in natural language. Auth is fully transparent: the gateway proxies all calls through `swift-token-server`, which handles OAuth token caching and `X-SWIFT-Signature` injection.

```
Claude ──(MCP tools)──► swift-mcp-gateway ──(HTTP)──► swift-token-server /proxy ──► sandbox.swift.com
```

## Tools

| Tool | Operation |
|---|---|
| `list_distributions` | List available distributions |
| `get_distribution` | Get a single distribution by ID |
| `ack_distribution` | Acknowledge a distribution |
| `nak_distribution` | Negative-acknowledge a distribution |
| `download_fin_messages` | Download FIN messages |
| `download_fin_message` | Download a single FIN message |
| `send_fin_message` | Send a FIN (MT) message |
| `download_interact_messages` | Download InterAct messages |
| `download_interact_message` | Download a single InterAct message |
| `send_interact_message` | Send an InterAct (MX) message |

## Stack

- **Python 3.11** + [fastmcp](https://github.com/jlowin/fastmcp)
- **Transport:** Streamable HTTP (MCP spec 2025-03-26) at `POST /mcp`
- **Docker** — runs as a container on port 8080 (exposed as 85 in dev)

## Quick start (Docker Compose)

See [swiftops](https://github.com/mblake4u/swiftops) — the full stack is orchestrated there.

```bash
cd ~/dev/github/mblake4u/swiftops
docker compose up -d
```

Then add to your Claude Desktop config (`~/.config/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "swift-api-gateway": {
      "url": "http://localhost:85/mcp"
    }
  }
}
```

Restart Claude Desktop. Ask: *"List the Swift distributions"*.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `PROXY_BASE_URL` | `http://localhost:82/proxy` | Token server proxy base URL |
| `MCP_HOST` | `0.0.0.0` | Bind host |
| `MCP_PORT` | `8080` | Bind port (internal) |

## Updating dependencies

```bash
# Edit requirements.in, then:
pip-compile --generate-hashes --output-file requirements.txt requirements.in
```

## License

[Apache 2.0](LICENSE)
