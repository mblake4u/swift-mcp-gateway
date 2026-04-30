# Contributing

## Branch model

| Branch | Purpose |
|---|---|
| `dev` | Active development — target PRs here |
| `staging` | Staging / pre-prod |
| `main` | Stable baseline; tagged releases only |

All work happens on `dev`. Open a PR against `dev`; `main` is updated at release.

## Getting started

```bash
git clone https://github.com/mblake4u/swift-mcp-gateway.git
cd swift-mcp-gateway
cp .env.example .env
# Edit .env — set PROXY_BASE_URL to point at your token server instance
```

The MCP gateway itself requires no Swift credentials. It proxies all API calls
through `swift-token-server`. You will need that service running (see
[swift-token-server](https://github.com/mblake4u/swift-token-server) and the
[swiftops](https://github.com/mblake4u/swiftops) orchestration repo).

## Running locally (no Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install --require-hashes -r requirements.txt
PROXY_BASE_URL=http://localhost:82/proxy python -m app.main
```

## Running tests

```bash
pip install pytest
python -m pytest tests/ -v
```

Tests use an in-process mock proxy — no running token server required.

## Updating dependencies

```bash
# Edit requirements.in, then:
pip-compile --generate-hashes --output-file requirements.txt requirements.in
# Commit both requirements.in and requirements.txt
```

## Pull requests

1. Branch from `dev`: `git checkout -b feat/my-thing`
2. Keep changes focused — one concern per PR
3. Run smoke tests before opening the PR
4. Reference any related ADR in the PR description
