"""
Swift MCP Gateway — eval harness for axes 1 (tool selection) and 2 (argument fidelity).

See docs/ADR-003-eval-methodology.md for the methodology.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python evals/run_evals.py
    python evals/run_evals.py --models claude-sonnet-4-5 claude-haiku-4-5
    python evals/run_evals.py --test-set evals/test_set.jsonl --output evals/results

Output:
    evals/results/<timestamp>.json   — full per-case results
    evals/results/<timestamp>.md     — human-readable summary

Cost note: prompt caching is enabled on system prompt + tools block.
The 10 tool schemas are large; without caching, schema cost dominates.
With caching, first case primes the cache and subsequent cases pay ~10x less.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from anthropic import Anthropic
except ImportError:
    sys.exit("anthropic package not installed. Run: pip install -r requirements.txt")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MODELS = [
    # "Latest each tier" run (mixed generation).
    # Opus 4-7 and Sonnet 4-6 are aliases — they auto-track the latest snapshot
    # within the named generation. Acknowledged reproducibility trade-off; the
    # matched-generation run below is the methodology control.
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
]

MATCHED_GEN_MODELS = [
    # Matched-generation 4.5 run — fully pinned, fully reproducible.
    # Used as the methodology control via:
    #   python evals/run_evals.py --models $(awk -F'"' '/MATCHED_GEN/,/]/ {if ($2 ~ /^claude/) print $2}' evals/run_evals.py | xargs)
    # or simply: python evals/run_evals.py --models claude-opus-4-5-20251101 claude-sonnet-4-5-20250929 claude-haiku-4-5-20251001
    "claude-opus-4-5-20251101",
    "claude-sonnet-4-5-20250929",
    "claude-haiku-4-5-20251001",
]

# Judge is pinned for stability — judge-drift would corrupt cross-run
# comparability of the free-text-arg scores.
JUDGE_MODEL = "claude-sonnet-4-5-20250929"

SYSTEM_PROMPT = (
    "You are a Swift API assistant. You have tools that interact with the Swift "
    "Alliance Cloud Messaging API v2.1.0 sandbox. The available tools cover "
    "distributions (list, get, ack, nak), FIN messages (download, send), and "
    "InterAct messages (download, send).\n\n"
    "For each user request, decide if a tool call is appropriate. If the request "
    "is off-topic, ambiguous without clarification, or requires a capability not "
    "exposed by the available tools, respond in natural language without calling "
    "any tool. Do not invent capabilities. Do not silently substitute a similar "
    "tool for one that doesn't exist."
)

JUDGE_PROMPT_TEMPLATE = (
    "You are scoring a free-text argument fidelity case for a Swift MCP gateway "
    "evaluation.\n\n"
    "The user's question was:\n{question}\n\n"
    "The argument being judged is `{arg_name}`.\n\n"
    "The evaluator's expected-behaviour rubric for this argument is:\n{rubric}\n\n"
    "The model populated this value for the argument:\n{actual_value}\n\n"
    "Question: does the populated value semantically match the rubric for the "
    "user's stated intent?\n\n"
    "Respond with a JSON object exactly in this form:\n"
    "{{\"verdict\": 0 or 1, \"reasoning\": \"one short sentence\"}}\n\n"
    "Verdict 1 means a match; 0 means a miss."
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TestCase:
    id: str
    axis: str
    question: str
    expected_tool: str | None
    expected_args: dict[str, Any] | None
    freeform_args: dict[str, str] | None
    notes: str = ""


@dataclass
class CaseResult:
    case_id: str
    model: str
    axis: str
    expected_tool: str | None
    actual_tool: str | None
    tool_match: bool
    expected_args: dict[str, Any] | None
    actual_args: dict[str, Any] | None
    strict_arg_match: dict[str, bool] | None
    freeform_verdicts: dict[str, dict] | None
    overall_pass: bool
    latency_ms: float
    cache_read_input_tokens: int | None
    cache_creation_input_tokens: int | None
    error: str | None = None


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------


def load_test_set(path: Path) -> list[TestCase]:
    cases: list[TestCase] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            cases.append(TestCase(**data))
    return cases


def load_tool_schemas(path: Path) -> list[dict]:
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Per-case eval
# ---------------------------------------------------------------------------


def run_case(
    client: Anthropic,
    model: str,
    case: TestCase,
    tools_with_cache: list[dict],
    system_blocks: list[dict],
) -> CaseResult:
    """Send the case question to the model with tool-use enabled. Score."""
    started = datetime.now(timezone.utc)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system_blocks,
            tools=tools_with_cache,
            messages=[{"role": "user", "content": case.question}],
        )
    except Exception as e:
        elapsed_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
        return CaseResult(
            case_id=case.id,
            model=model,
            axis=case.axis,
            expected_tool=case.expected_tool,
            actual_tool=None,
            tool_match=False,
            expected_args=case.expected_args,
            actual_args=None,
            strict_arg_match=None,
            freeform_verdicts=None,
            overall_pass=False,
            latency_ms=elapsed_ms,
            cache_read_input_tokens=None,
            cache_creation_input_tokens=None,
            error=f"{type(e).__name__}: {e}",
        )

    elapsed_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000

    # Extract first tool call (if any)
    actual_tool: str | None = None
    actual_args: dict[str, Any] | None = None
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            actual_tool = block.name
            actual_args = dict(block.input) if block.input else {}
            break

    tool_match = case.expected_tool == actual_tool

    # Score arg fidelity (only meaningful if tool was matched correctly)
    strict_arg_match: dict[str, bool] | None = None
    freeform_verdicts: dict[str, dict] | None = None
    if case.axis == "argument_fidelity" and tool_match:
        if case.expected_args:
            strict_arg_match = {}
            for key, expected_value in case.expected_args.items():
                actual_value = actual_args.get(key) if actual_args else None
                strict_arg_match[key] = actual_value == expected_value
        if case.freeform_args:
            freeform_verdicts = {}
            for key, rubric in case.freeform_args.items():
                actual_value = actual_args.get(key) if actual_args else None
                verdict = run_judge(client, case.question, key, rubric, actual_value)
                freeform_verdicts[key] = verdict

    # Overall pass
    if case.axis in ("tool_selection", "negative"):
        overall_pass = tool_match
    elif case.axis == "argument_fidelity":
        if not tool_match:
            overall_pass = False
        else:
            strict_ok = (
                all(strict_arg_match.values()) if strict_arg_match else True
            )
            freeform_ok = (
                all(v["verdict"] == 1 for v in freeform_verdicts.values())
                if freeform_verdicts
                else True
            )
            overall_pass = strict_ok and freeform_ok
    else:
        overall_pass = False

    return CaseResult(
        case_id=case.id,
        model=model,
        axis=case.axis,
        expected_tool=case.expected_tool,
        actual_tool=actual_tool,
        tool_match=tool_match,
        expected_args=case.expected_args,
        actual_args=actual_args,
        strict_arg_match=strict_arg_match,
        freeform_verdicts=freeform_verdicts,
        overall_pass=overall_pass,
        latency_ms=elapsed_ms,
        cache_read_input_tokens=getattr(response.usage, "cache_read_input_tokens", None),
        cache_creation_input_tokens=getattr(response.usage, "cache_creation_input_tokens", None),
    )


def run_judge(
    client: Anthropic,
    question: str,
    arg_name: str,
    rubric: str,
    actual_value: Any,
) -> dict:
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        question=question,
        arg_name=arg_name,
        rubric=rubric,
        actual_value=json.dumps(actual_value),
    )
    try:
        response = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = next(
            (b.text for b in response.content if getattr(b, "type", None) == "text"),
            "",
        ).strip()
        # Strip optional code-fence wrapping
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        parsed = json.loads(text)
        return {
            "verdict": int(parsed.get("verdict", 0)),
            "reasoning": str(parsed.get("reasoning", "")),
        }
    except Exception as e:
        return {
            "verdict": 0,
            "reasoning": f"judge error: {type(e).__name__}: {str(e)[:200]}",
        }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def summarise(results: list[CaseResult]) -> dict:
    summary: dict = {}
    for r in results:
        m = summary.setdefault(r.model, {})
        a = m.setdefault(
            r.axis, {"pass": 0, "total": 0, "total_latency_ms": 0.0}
        )
        a["total"] += 1
        a["total_latency_ms"] += r.latency_ms
        if r.overall_pass:
            a["pass"] += 1

    for model in summary:
        overall_pass = 0
        overall_total = 0
        for axis_key, s in list(summary[model].items()):
            if axis_key == "__overall__":
                continue
            s["pass_rate"] = s["pass"] / s["total"] if s["total"] else 0
            s["mean_latency_ms"] = (
                s["total_latency_ms"] / s["total"] if s["total"] else 0
            )
            overall_pass += s["pass"]
            overall_total += s["total"]
        summary[model]["__overall__"] = {
            "pass": overall_pass,
            "total": overall_total,
            "pass_rate": overall_pass / overall_total if overall_total else 0,
        }
    return summary


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def write_results(
    output_dir: Path,
    results: list[CaseResult],
    summary: dict,
    models: list[str],
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    json_path = output_dir / f"{ts}.json"
    md_path = output_dir / f"{ts}.md"

    json_path.write_text(
        json.dumps(
            {
                "timestamp_utc": ts,
                "models": models,
                "results": [asdict(r) for r in results],
                "summary": summary,
            },
            indent=2,
        )
    )

    lines = [
        f"# Eval results — {ts} UTC",
        "",
        f"**Models:** {', '.join(models)}",
        "",
        f"**Cases:** {len(results) // len(models)} per model × {len(models)} models = {len(results)} runs",
        "",
        "Methodology: see [docs/ADR-003-eval-methodology.md](../docs/ADR-003-eval-methodology.md).",
        "",
        "## Pass rates by model × axis",
        "",
        "| Model | Tool selection | Argument fidelity | Negative | Overall |",
        "|---|---|---|---|---|",
    ]

    def fmt_rate(m: dict, axis: str) -> str:
        s = m.get(axis, {})
        return (
            f"{s['pass']}/{s['total']} ({s['pass_rate']:.0%})"
            if s.get("total")
            else "—"
        )

    for model in models:
        m = summary.get(model, {})
        overall = m.get("__overall__", {})
        lines.append(
            f"| `{model}` | {fmt_rate(m, 'tool_selection')} "
            f"| {fmt_rate(m, 'argument_fidelity')} "
            f"| {fmt_rate(m, 'negative')} "
            f"| {overall.get('pass', 0)}/{overall.get('total', 0)} "
            f"({overall.get('pass_rate', 0):.0%}) |"
        )

    lines.extend(
        [
            "",
            "## Mean latency by model × axis (ms)",
            "",
            "| Model | Tool selection | Argument fidelity | Negative |",
            "|---|---|---|---|",
        ]
    )
    for model in models:
        m = summary.get(model, {})

        def fmt_lat(axis: str) -> str:
            s = m.get(axis, {})
            return f"{s['mean_latency_ms']:.0f}" if s.get("total") else "—"

        lines.append(
            f"| `{model}` | {fmt_lat('tool_selection')} "
            f"| {fmt_lat('argument_fidelity')} "
            f"| {fmt_lat('negative')} |"
        )

    # Cache stats
    total_cache_read = sum(
        r.cache_read_input_tokens or 0 for r in results
    )
    total_cache_create = sum(
        r.cache_creation_input_tokens or 0 for r in results
    )
    lines.extend(
        [
            "",
            "## Cache stats",
            "",
            f"- Total cache-read tokens: **{total_cache_read:,}**",
            f"- Total cache-creation tokens: **{total_cache_create:,}**",
            f"- Cache hit ratio: **{total_cache_read / (total_cache_read + total_cache_create):.1%}**"
            if (total_cache_read + total_cache_create) > 0
            else "- Cache hit ratio: n/a",
            "",
            "Prompt caching applied to system prompt + tools block. The first case of each model primes the cache; subsequent cases read from it.",
            "",
            "## Files",
            "",
            f"- Full per-case results: `{json_path.name}`",
            f"- This summary: `{md_path.name}`",
        ]
    )

    md_path.write_text("\n".join(lines) + "\n")
    return json_path, md_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def build_cached_tools(tools: list[dict]) -> list[dict]:
    """Attach cache_control to the final tool so the whole block is cached."""
    if not tools:
        return tools
    cached = [dict(t) for t in tools]
    cached[-1] = {**cached[-1], "cache_control": {"type": "ephemeral"}}
    return cached


def build_system_blocks() -> list[dict]:
    return [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test-set", type=Path, default=Path("evals/test_set.jsonl")
    )
    parser.add_argument(
        "--schemas", type=Path, default=Path("evals/tool_schemas.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("evals/results")
    )
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    args = parser.parse_args()

    if "ANTHROPIC_API_KEY" not in os.environ:
        sys.exit("ANTHROPIC_API_KEY not set in environment.")

    client = Anthropic()
    cases = load_test_set(args.test_set)
    tools = load_tool_schemas(args.schemas)
    tools_cached = build_cached_tools(tools)
    system_blocks = build_system_blocks()

    print(f"Loaded {len(cases)} test cases and {len(tools)} tool schemas.")
    print(f"Models: {', '.join(args.models)}")
    print(f"Judge: {JUDGE_MODEL}")
    print()

    results: list[CaseResult] = []
    for model in args.models:
        print(f"=== {model} ===")
        for i, case in enumerate(cases, 1):
            result = run_case(client, model, case, tools_cached, system_blocks)
            status = "PASS" if result.overall_pass else "FAIL"
            err = f" ERROR: {result.error}" if result.error else ""
            print(
                f"  [{i:2d}/{len(cases)}] {case.id:8s} [{case.axis:18s}] {status}  "
                f"{result.latency_ms:6.0f}ms{err}"
            )
            results.append(result)
        print()

    summary = summarise(results)
    json_path, md_path = write_results(args.output, results, summary, args.models)
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
