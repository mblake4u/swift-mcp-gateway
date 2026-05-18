# ADR-003: Swift MCP Gateway — Evaluation Methodology

**Date:** 2026-05-01
**Status:** Accepted
**Deciders:** Michael Blake

---

## Context

SwiftOps is closing out as a portfolio OSS piece. Before close, this repo publishes a reproducible evaluation methodology for the Swift MCP Gateway. The methodology serves three purposes:

1. **Portfolio signal.** Methodology rigour is the rarest engineering trait in the MCP-gateway space as of mid-2026. Most published gateways ship tools and docs but no evaluation framework.
2. **Successor-project seed.** A separate commercial project in early scoping has evals-as-marketing as a founding pillar. The harness built here is a direct seed for that work.
3. **Honest measurement.** Claims about MCP-gateway quality should be testable. "It works in Claude Desktop" is not a benchmark.

Existing public MCP gateways in adjacent finance categories (Grasshopper/Narmi, Griffin, Stripe, Coinbase x402, Slash) ship tools and documentation but no published eval methodology. The category lacks a methodological baseline; this ADR proposes one tailored to the gateway-as-tool-surface shape.

---

## Decision

Three orthogonal evaluation axes. Each measures something a real consumer (human or agent) cares about, with a reproducible scoring rule.

### Axis 1 — Tool-selection accuracy

**What.** Given a natural-language question, does the model pick the correct MCP tool?

**Why.** A gateway with the right tools is useless if the model can't reliably pick the right one. This axis stress-tests the tool **descriptions** and **naming**, not the underlying API.

**Scoring.** Strict equality on tool name. Special case `null` (model should refuse or ask clarification, no tool call) handled as an explicit expected value — see Axis 1's negative cases.

### Axis 2 — Argument fidelity

**What.** Given that the model picked the right tool, did it populate the right arguments?

**Why.** Wrong arguments produce silent failures (wrong distribution acked, malformed message sent). Tool-selection accuracy alone overstates real-world success.

**Scoring.**

- **Strict equality** for typed and enumerated args: distribution IDs, BIC codes, MT/MX type strings, integers, sender references.
- **LLM-as-judge** with explicit rubric for free-text args. Three args fall into this bucket:
  - `reason` in `nak_distribution`
  - `payload` in `send_fin_message`
  - `payload` in `send_interact_message`

  The judge prompt asks "does the populated value semantically match the user's stated intent" with a 0/1 verdict and reasoning string.

### Axis 3 — Operational metrics (latency · coverage · freshness)

**What.**
- **Latency:** P50 and P95 per tool, measured against the live Swift sandbox, 20 runs each.
- **Coverage:** Percentage of Swift Messaging API v2.1.0 endpoints reachable via the gateway. Numerator = endpoints exposed as MCP tools; denominator = total v2.1.0 endpoints documented in the OpenAPI spec.
- **Freshness:** N/A by design — the gateway is a transparent proxy with no caching layer. Documented as N/A in results rather than measured.

**Why.** A gateway can be functionally correct but operationally unusable. Latency in particular is what separates an agent that completes a task from one that times out and retries.

**Scoring.** Numeric, reported with caveats: sandbox-vs-production timing differential, single-region measurement, network conditions captured at run time.

---

## Options Considered

| Option | Notes |
|---|---|
| **Three-axis methodology (this ADR)** ✅ | Orthogonal, reproducible, recruiter-legible. Each axis decouples cleanly. |
| End-to-end LLM-as-judge on a "did the agent solve the task" rubric | More realistic but un-reproducible run-to-run. Hides whether failures are tool-selection, argument, or operational. Defer to a future ADR if multi-turn agent workflows become in-scope. |
| Single accuracy number | Loses signal — tool-selection and argument-fidelity should be reported separately so failures are attributable. |
| Manual review only | Doesn't scale to model comparisons; not reproducible. |
| Pure unit-test of tool implementations | Tests the gateway code, not the gateway-as-a-product. Misses the model-tool interaction which is the actual user experience. |

---

## Test set

30 hand-curated cases at `evals/test_set.jsonl`:

- **18 tool-selection** (positive) — covers all 10 tools with extra weight on the more ambiguous pairs (`download_fin_messages` plural vs `download_fin_message` singular; `list_distributions` rephrases).
- **6 argument-fidelity** — drilling into typed-arg and free-text-arg correctness, including the two `send_*` tools with five+ required args.
- **6 negative** — questions that should yield no tool call (off-topic, unsupported capability, ambiguous-without-clarification).

Hand-curated rather than LLM-generated to keep the gold standard independent of model behaviour. A model that wrote the questions has a self-reference advantage when answering them.

---

## Models evaluated

Two complementary runs target three Anthropic models each, enabling both real-world relevance and reproducible methodology:

**Run A — Latest each tier (mixed generation).** Answers "what does a user get if they pick the best at each tier today?":

- `claude-opus-4-7` (alias)
- `claude-sonnet-4-6` (alias)
- `claude-haiku-4-5-20251001` (pinned — small-tier is one generation behind as of 2026-05)

**Run B — Matched generation 4.5 (fully pinned).** The methodology control — fully reproducible, isolates per-tier-size effects within one generation:

- `claude-opus-4-5-20251101`
- `claude-sonnet-4-5-20250929`
- `claude-haiku-4-5-20251001`

Both runs use the same judge model — `claude-sonnet-4-5-20250929`, pinned — so free-text-arg verdicts are comparable across runs.

The latest-tier aliases (`opus-4-7`, `sonnet-4-6`) carry a reproducibility caveat: they auto-track new snapshots within their generation. Results published under those aliases are timestamped and the actual snapshot resolution at run time should be considered run-specific.

Latency probe (axis 3) targets the gateway itself; model choice is out-of-scope for axis 3.

---

## Harness implementation

Captured in `evals/run_evals.py` (axes 1–2) and `evals/probe.py` (axis 3). Key design choices:

- **Anthropic API direct, not the live MCP transport.** For axes 1–2, we feed the gateway's tool schemas directly to the Anthropic API's tool-use feature. This is faster, fully deterministic at the API level, and decouples eval signal from MCP-transport noise. Live MCP transport is used only by `probe.py` for latency.
- **Prompt caching** on the system prompt + tool schemas. The 10 tool definitions are large and identical across all 30 cases × 3 models = 90 runs. Caching cuts cost ~10× and is explicitly modelled in results.
- **Tool schemas frozen** in `evals/tool_schemas.json`, regenerated via `make refresh-schemas` from the live FastMCP server. Drift between code and schemas is detected by a checksum comparison at eval start.

---

## Consequences

- Methodology is published at `evals/` in this repo and as a Notion page under Swift Lab ("Evaluating an MCP Gateway: A Methodology").
- First baseline results captured at `evals/results/2026-05-01.md`. Future runs append-only.
- README links to ADR + Notion methodology + latest results.
- The methodology is intentionally lightweight (30 cases). Successor-project work may demand more; this ADR can be referenced as the seed and deeper methodology lives there.
- **Known limitation:** 30 cases gives ~3 cases per tool on the selection axis. Statistically thin per-tool but sufficient for **cross-model aggregate comparison**. Sample size is a deliberate tradeoff against hand-curation quality — every case is one Michael wrote and would defend.
- **Known limitation:** the test set encodes one author's intuition about realistic phrasing. A test-set diversity audit is a possible future extension; out-of-scope for this ADR.
- **v1 baseline run (2026-05-18) surfaced a test-set bug.** Four send-tool cases ask the model to "send X from Y to Z" without providing a payload. The correct real-world behaviour is to refuse, which all six model runs did. v2 test-set rewrite is captured as a backlog item — see [`evals/results/2026-05-18-analysis.md`](../evals/results/2026-05-18-analysis.md) §"v2 backlog". v1 baseline is published as-is with the analysis section calling out adjusted numbers.

---

## References

- Public methodology write-up (Notion): [Evaluating an MCP Gateway: A Methodology](https://www.notion.so/Evaluating-an-MCP-Gateway-A-Methodology-364aa5f988dd8038bb21d34880ca6eab)
- Anthropic API documentation: tool use, prompt caching
- MCP specification 2025-03-26 (Streamable HTTP transport)
- Swift Messaging API v2.1.0 OpenAPI spec (definitive endpoint inventory for coverage calculation)
