"""
Swift MCP Gateway — operational metrics probe (axis 3 of the eval methodology).

Measures:
  - **Latency**: P50 and P95 per safe (read-only) tool, against the live Swift sandbox.
  - **Coverage**: percentage of Swift Messaging API v2.1.0 endpoints reachable via the gateway.

What's NOT measured:
  - Mutating tools (`ack_distribution`, `nak_distribution`, `send_fin_message`,
    `send_interact_message`) — running 20× sends or NAKs against the sandbox
    would spam state and is not a fair latency benchmark anyway. We document
    expected latency from the read tools (which traverse the same auth +
    signing + proxy stack) as a proxy.
  - Freshness — by design N/A (transparent proxy, no caching).

Usage:
    python evals/probe.py
    python evals/probe.py --runs 20 --output evals/results
    python evals/probe.py --proxy http://localhost:82/proxy

See `docs/ADR-003-eval-methodology.md` for the methodology.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_PROXY_BASE_URL = "http://localhost:82/proxy"
DEFAULT_RUNS = 20
TIMEOUT_S = 30.0

# Tools we can probe safely (no state change).
# Each entry: (tool_name, method, path, params_or_body)
# Paths with {id} will be substituted from the bootstrap list_distributions call.

SAFE_PROBES = [
    {"tool": "list_distributions",         "method": "GET", "path": "/distributions",                    "needs_id": False, "id_as_query": False},
    {"tool": "get_distribution",           "method": "GET", "path": "/distributions/{id}",               "needs_id": True,  "id_as_query": False},
    # download_*_messages (plural) use the id as the `distribution-id` *query parameter*.
    # The Swift API rejects these calls without it (HTTP 400 SwAP504) — surfaced by
    # the initial probe run on 2026-05-18. Gateway tool defs corrected to make
    # distribution_id required; probe paths now include the query param.
    {"tool": "download_fin_messages",      "method": "GET", "path": "/fin/messages",                     "needs_id": True,  "id_as_query": True},
    {"tool": "download_fin_message",       "method": "GET", "path": "/fin/messages/{id}",                "needs_id": True,  "id_as_query": False},
    {"tool": "download_interact_messages", "method": "GET", "path": "/interact/messages",                "needs_id": True,  "id_as_query": True},
    {"tool": "download_interact_message",  "method": "GET", "path": "/interact/messages/{id}",           "needs_id": True,  "id_as_query": False},
]

# Tools we know about but do NOT probe.
UNPROBED = [
    {"tool": "ack_distribution",     "rationale": "Mutating — changes distribution state."},
    {"tool": "nak_distribution",     "rationale": "Mutating — changes distribution state."},
    {"tool": "send_fin_message",     "rationale": "Mutating — would emit real outbound MT messages."},
    {"tool": "send_interact_message","rationale": "Mutating — would emit real outbound MX messages."},
]

# Coverage denominator — from Swift Messaging API v2.1.0 OpenAPI spec.
# See swift-swagger-ui/SWIFT-API-Swift-Messaging-2.1.0-swagger.yaml.
TOTAL_ENDPOINTS = 43
FILEACT_ENDPOINTS = 8  # Out of scope per ADR-002 (stateful handshake)
TOTAL_EXCLUDING_FILEACT = TOTAL_ENDPOINTS - FILEACT_ENDPOINTS


# ---------------------------------------------------------------------------
# Bootstrap — find a real distribution_id to probe id-bearing endpoints
# ---------------------------------------------------------------------------

def fetch_distribution_id(proxy: str) -> str | None:
    """Call list_distributions and pull the first id, if any."""
    url = f"{proxy.rstrip('/')}/distributions"
    try:
        resp = httpx.get(url, timeout=TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  bootstrap failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None

    # Best-effort: walk the response looking for an id-like field.
    items = data if isinstance(data, list) else data.get("distributions") or data.get("items") or data.get("data") or []
    if not items or not isinstance(items, list):
        return None
    first = items[0]
    for key in ("id", "distribution_id", "distributionId"):
        if key in first:
            return str(first[key])
    return None


# ---------------------------------------------------------------------------
# Probe one tool
# ---------------------------------------------------------------------------

def probe_tool(
    proxy: str,
    method: str,
    path: str,
    runs: int,
) -> dict[str, Any]:
    url = f"{proxy.rstrip('/')}{path}"
    latencies: list[float] = []
    statuses: list[int] = []
    errors: list[str] = []

    for _ in range(runs):
        start = time.perf_counter()
        try:
            if method == "GET":
                resp = httpx.get(url, timeout=TIMEOUT_S)
            else:
                raise NotImplementedError(f"probe does not run {method}")
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies.append(elapsed_ms)
            statuses.append(resp.status_code)
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies.append(elapsed_ms)
            errors.append(f"{type(e).__name__}: {e}")

    sorted_lat = sorted(latencies)
    n = len(sorted_lat)
    p50 = statistics.median(sorted_lat) if sorted_lat else 0
    # Simple P95: index ceil(0.95 * n) - 1, clamped
    p95_idx = max(0, min(n - 1, int(round(0.95 * n)) - 1))
    p95 = sorted_lat[p95_idx] if sorted_lat else 0
    mean = statistics.mean(sorted_lat) if sorted_lat else 0
    success = sum(1 for s in statuses if 200 <= s < 300)

    return {
        "runs": runs,
        "p50_ms": round(p50, 1),
        "p95_ms": round(p95, 1),
        "mean_ms": round(mean, 1),
        "min_ms": round(min(sorted_lat), 1) if sorted_lat else 0,
        "max_ms": round(max(sorted_lat), 1) if sorted_lat else 0,
        "success_count": success,
        "status_codes": dict(sorted({s: statuses.count(s) for s in set(statuses)}.items())),
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------

def compute_coverage() -> dict[str, Any]:
    exposed = len(SAFE_PROBES) + len(UNPROBED)  # 6 + 4 = 10
    return {
        "exposed_tools": exposed,
        "total_endpoints_in_spec": TOTAL_ENDPOINTS,
        "raw_coverage_pct": round(100 * exposed / TOTAL_ENDPOINTS, 1),
        "fileact_endpoints_excluded": FILEACT_ENDPOINTS,
        "adjusted_total_endpoints": TOTAL_EXCLUDING_FILEACT,
        "adjusted_coverage_pct": round(100 * exposed / TOTAL_EXCLUDING_FILEACT, 1),
        "note": (
            "FileAct (8 endpoints) is intentionally excluded — see ADR-002. "
            "The remaining gap is operational/reporting endpoints (delivery reports, "
            "archives, exports, transmission reports, batch) not in v1 scope."
        ),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_report(
    output_dir: Path,
    proxy: str,
    distribution_id: str | None,
    per_tool: dict[str, dict],
    coverage: dict,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    json_path = output_dir / f"{ts}-probe.json"
    md_path = output_dir / f"{ts}-probe.md"

    payload = {
        "timestamp_utc": ts,
        "proxy_base_url": proxy,
        "bootstrap_distribution_id": distribution_id,
        "per_tool": per_tool,
        "unprobed_tools": UNPROBED,
        "coverage": coverage,
    }
    json_path.write_text(json.dumps(payload, indent=2) + "\n")

    # Markdown
    lines = [
        f"# Operational probe — {ts} UTC",
        "",
        f"**Proxy:** `{proxy}`  ",
        f"**Bootstrap distribution_id:** `{distribution_id or '(none — id-bearing endpoints skipped)'}`",
        "",
        "Methodology: see [`docs/ADR-003-eval-methodology.md`](../../docs/ADR-003-eval-methodology.md), axis 3.",
        "",
        "## Latency by tool (live sandbox)",
        "",
        "| Tool | Runs | Successes | P50 (ms) | P95 (ms) | Mean (ms) | Min (ms) | Max (ms) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for tool, stats in per_tool.items():
        lines.append(
            f"| `{tool}` | {stats['runs']} | {stats['success_count']}/{stats['runs']} | "
            f"{stats['p50_ms']} | {stats['p95_ms']} | {stats['mean_ms']} | "
            f"{stats['min_ms']} | {stats['max_ms']} |"
        )

    lines.extend(
        [
            "",
            "### Caveats",
            "",
            "- Live Swift sandbox, single region, single time of window. Production latency will differ.",
            "- Sandbox load is variable; P95 should be read directionally, not as an SLA.",
            "- The token server's OAuth token cache means run 1 of each tool may include a token refresh (~200–500ms one-off).",
            "",
            "## Unprobed tools",
            "",
            "Mutating tools are not benchmarked — see methodology rationale.",
            "",
            "| Tool | Reason |",
            "|---|---|",
        ]
    )
    for u in UNPROBED:
        lines.append(f"| `{u['tool']}` | {u['rationale']} |")

    lines.extend(
        [
            "",
            "Expected latency for mutating tools should be similar to the matching read tool plus signing overhead (the `X-SWIFT-Signature` injection runs on POST/PUT/PATCH/DELETE).",
            "",
            "## Coverage",
            "",
            f"- **Tools exposed:** {coverage['exposed_tools']}",
            f"- **Endpoints in spec:** {coverage['total_endpoints_in_spec']}",
            f"- **Raw coverage:** {coverage['raw_coverage_pct']}%",
            f"- **Coverage excluding FileAct ({coverage['fileact_endpoints_excluded']} endpoints, ADR-002):** {coverage['adjusted_coverage_pct']}%",
            "",
            f"> {coverage['note']}",
            "",
            "See [`evals/results/2026-05-18-analysis.md`](2026-05-18-analysis.md) for the per-domain coverage breakdown.",
            "",
            "## Files",
            "",
            f"- This summary: `{md_path.name}`",
            f"- Full JSON: `{json_path.name}`",
        ]
    )

    md_path.write_text("\n".join(lines) + "\n")
    return json_path, md_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proxy", default=DEFAULT_PROXY_BASE_URL)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--output", type=Path, default=Path("evals/results"))
    args = parser.parse_args()

    print(f"Probing proxy: {args.proxy}")
    print(f"Runs per tool: {args.runs}")
    print()

    print("Bootstrap — fetching a real distribution_id…")
    distribution_id = fetch_distribution_id(args.proxy)
    if distribution_id:
        print(f"  using distribution_id={distribution_id}")
    else:
        print("  no distribution_id found; id-bearing endpoints will be skipped")
    print()

    per_tool: dict[str, dict] = {}
    for probe in SAFE_PROBES:
        if probe["needs_id"] and not distribution_id:
            print(f"  [skip] {probe['tool']} (no distribution_id available)")
            continue

        if probe["id_as_query"]:
            # Distribution id as ?distribution-id=... query param (plural endpoints)
            path = f"{probe['path']}?distribution-id={distribution_id}"
        elif probe["needs_id"]:
            # Distribution id as path segment {id} (singular endpoints)
            path = probe["path"].replace("{id}", distribution_id)
        else:
            path = probe["path"]

        print(f"  probing {probe['tool']} ({probe['method']} {path})…")
        stats = probe_tool(args.proxy, probe["method"], path, args.runs)
        per_tool[probe["tool"]] = stats
        print(
            f"    P50={stats['p50_ms']}ms  P95={stats['p95_ms']}ms  "
            f"success={stats['success_count']}/{stats['runs']}"
        )

    coverage = compute_coverage()
    print()
    print(
        f"Coverage: {coverage['exposed_tools']}/{coverage['total_endpoints_in_spec']} "
        f"endpoints ({coverage['raw_coverage_pct']}% raw, "
        f"{coverage['adjusted_coverage_pct']}% excluding FileAct)"
    )
    print()

    json_path, md_path = write_report(args.output, args.proxy, distribution_id, per_tool, coverage)
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
