# Evaluating an MCP Gateway: A Methodology

*This file is the source content for a Notion page under **Swift Lab**. Paste into Notion and the formatting renders cleanly (tables, code blocks, headings all work via Notion's markdown import). Keep this file in sync if the Notion page is edited — but Notion is the recruiter-facing canonical surface; this file is the offline backup.*

---

**Date:** 2026-05-18
**Author:** Michael Blake ([mblake4u](https://github.com/mblake4u))
**Status:** First baseline run complete. Methodology and harness frozen for reference.

**Source code:** [github.com/mblake4u/swift-mcp-gateway](https://github.com/mblake4u/swift-mcp-gateway) (`evals/` directory)

---

## Why this exists

MCP (Model Context Protocol) gateways are proliferating across finance — Grasshopper / Narmi (US bank), Griffin (UK BaaS), Stripe, Coinbase x402, Slash, and others. All ship tools and documentation. **None** ship a published evaluation methodology as of mid-2026.

That gap matters. An MCP gateway is a thin wrapper around an existing API surface — its value to a model (and thus to an agent, and thus to a user) comes from *how well the model can use the tools*. That's not measurable by inspecting the wrapper code. It needs deliberate measurement against a real model + real questions + a real grading rule.

This page describes the methodology, applies it to the Swift MCP Gateway as the worked example, and reports the first baseline run.

---

## The methodology — three orthogonal axes

The three axes are chosen because they decouple cleanly. Each measures something a real consumer (human or agent) cares about. Each has a reproducible scoring rule. None subsumes another — and the first baseline run produced a finding (cluster 5 below) that only axis 3 could surface.

### Axis 1 — Tool-selection accuracy

**What.** Given a natural-language question, does the model pick the correct MCP tool?

**Why.** A gateway with the right tools is useless if the model can't reliably pick the right one. This axis stress-tests the tool **descriptions** and **naming**, not the underlying API.

**Scoring.** Strict equality on tool name. The special case "no tool" — the model should refuse or ask clarification — is an explicit expected value for negative cases.

### Axis 2 — Argument fidelity

**What.** Given the right tool was picked, did the model populate the right arguments?

**Why.** Wrong arguments produce silent failures (wrong distribution acked, malformed message sent). Tool-selection accuracy alone overstates real-world success.

**Scoring.** Strict equality for typed/enumerated args (IDs, ints, BICs, enums). LLM-as-judge with an explicit per-case rubric for free-text args (e.g. a `reason` field, an XML or MT payload body). Judge prompt asks for a 0/1 verdict against the rubric.

### Axis 3 — Operational metrics

**What.** Latency (P50, P95 per tool, against the live API, 20 runs each), coverage (% of upstream API endpoints reachable through the gateway), freshness (N/A by design for a transparent-proxy gateway).

**Why.** A gateway can be functionally correct but operationally unusable. Latency in particular separates an agent that completes a task from one that times out.

**Scoring.** Numeric, reported with caveats (sandbox-vs-production differential, single-region measurement, network conditions at run time).

---

## Test set

30 hand-curated cases: 18 tool-selection (all 10 gateway tools represented, extra weight on ambiguous pairs and industry-jargon decoding), 6 argument-fidelity (typed args plus three free-text cases going through LLM-judge), 6 negative (off-topic, unsupported capabilities, ambiguous-without-clarification).

Hand-curated, not LLM-generated. A model that wrote the questions has a self-reference advantage when answering them. Manual authorship is the academic norm and worth the 30 minutes for the gold standard.

---

## Harness

- **Anthropic API direct** for axes 1+2, not the live MCP transport. Faster, deterministic at the API level, isolates eval signal from transport noise.
- **Prompt caching** on the system prompt and tools block. Cuts cost ~10× because the 10 tool definitions are large and identical across all cases.
- **Live MCP transport** is used only by the axis-3 latency probe.
- **Tool schemas frozen** in `evals/tool_schemas.json`; a separate `dump_schemas.py` regenerates from the live FastMCP server.
- **LLM-judge model pinned** (`claude-sonnet-4-5-20250929`) so verdict drift doesn't corrupt cross-run comparability.

Full harness: [`evals/run_evals.py`](https://github.com/mblake4u/swift-mcp-gateway/blob/staging/evals/run_evals.py) (axes 1+2) and [`evals/probe.py`](https://github.com/mblake4u/swift-mcp-gateway/blob/staging/evals/probe.py) (axis 3).

---

## First baseline — 2026-05-18

### Run A — latest each tier

Real-world question: *what does a user get if they pick the best at each tier today?*

| Model | Tool selection | Argument fidelity | Negative | **Overall** |
|---|---|---|---|---|
| `claude-opus-4-7` | 78% (14/18) | 100% (6/6) | 100% (6/6) | **87% (26/30)** |
| `claude-sonnet-4-6` | 72% (13/18) | 100% (6/6) | 67% (4/6) | 77% (23/30) |
| `claude-haiku-4-5` | 61% (11/18) | 100% (6/6) | 100% (6/6) | 77% (23/30) |

### Run B — matched generation 4.5 (fully pinned)

Methodology control: removes generation effects, isolates per-tier capability.

| Model | Tool selection | Argument fidelity | Negative | **Overall** |
|---|---|---|---|---|
| `claude-opus-4-5-20251101` | 67% (12/18) | 100% | 100% | 80% (24/30) |
| `claude-sonnet-4-5-20250929` | 72% (13/18) | 100% | 83% (5/6) | 80% (24/30) |
| `claude-haiku-4-5-20251001` | 67% (12/18) | 100% | 100% | 80% (24/30) |

**Two headline findings.** (1) Argument fidelity is 100% across every model — once the right tool is picked, argument extraction is solved; the bottleneck is tool selection. (2) Cache hit ratio is **96.7%** — prompt caching works as designed; first case per model primes the cache, the remaining 29 read from it.

### Axis 3 — latency and coverage

**Coverage.** 10 tools exposed against 43 endpoints in Swift Messaging API v2.1.0 = 23% raw, **29% excluding FileAct** (out of v1 scope per ADR-002). Gap is operational/reporting endpoints (delivery reports, archives, exports, transmission reports, batch).

**Latency.** 20 runs per tool against the live sandbox over a multi-hop path; production co-located deployment would show materially lower numbers. All 6 read-only tools 20/20 success after the v0.1.1 fix below.

| Tool | P50 (ms) | P95 (ms) |
|---|---|---|
| `list_distributions` | 1,216 | 2,470 |
| `get_distribution` | 1,206 | 1,370 |
| `download_fin_messages` | 1,331 | 3,181 |
| `download_fin_message` | 1,288 | 2,402 |
| `download_interact_messages` | 1,299 | 1,558 |
| `download_interact_message` | 1,480 | 3,875 |

Read as directional, not as SLA. Mutating tools (ACK, NAK, sends) deliberately not probed — running 20 sends or NAKs against the sandbox spams state and isn't a fair latency benchmark.

---

## What the methodology surfaced — five clusters

This is the central artefact of the run. The 30-case test set, applied to 3+3 = 6 model runs, produced 30 individual failures. They sort into **five distinct clusters — only one of which is "the model is bad."**

### Cluster 1 — Test-set bug (4 cases × every model)

Four send-tool cases asked the model to *"send X from Y to Z"* without providing a payload. **Every model on Run A refused to call the tool** — the correct real-world behaviour. Inventing an MT103 payload from thin air would be a catastrophic agent failure.

**Verdict.** Test set is wrong; the gold-standard answer for these cases should be "no tool / ask clarification."

After stripping cluster 1, `opus-4-7` jumps from 87% to **100%** on the remaining 26 cases.

### Cluster 2 — Product naming issue

Multiple models confused `download_fin_messages` (plural, list endpoint) with `download_fin_message` (singular, get-by-id). The singular/plural distinction is one character apart and semantically distinct — a design smell. Tool descriptions tried to disambiguate; didn't fully work.

**Recommendation.** Rename to a consistent verb pattern (`list_*` / `get_*`). Captured for a future iteration.

### Cluster 3 — Small-model jargon limit

Only Haiku failed *"What MX messages do we have queued?"* — both runs. Mapped to `list_distributions` instead of `download_interact_messages`. The MX-format industry jargon (= InterAct) wasn't bridged. Both Sonnet and Opus tiers handled it cleanly.

**Finding.** Small models lose precision on industry jargon even when larger models in the same family handle it. Real datum for agent system design — jargon-heavy domains may need additional prompt engineering or fine-tuning at the smallest-model tier.

### Cluster 4 — Refusal-instruction non-compliance

Sonnet (both 4-5 and 4-6) substituted near-match tools despite an explicit system-prompt instruction: *"Do not silently substitute a similar tool for one that doesn't exist."* The two failures: *"cancel distribution"* → `nak_distribution` (cancel ≈ reject semantically); *"search messages from yesterday"* → `list_distributions` (no date filter, but called anyway).

Notably **Opus 4-7 and Haiku 4-5 both got 6/6 on negatives** — the substitution-prone behaviour is Sonnet-tier-specific in this dataset. Worth deeper investigation in a future run.

### Cluster 5 — Tool/API contract mismatch (probe-found, FIXED)

The most interesting finding because it was caught by **axis 3 only** — neither axis 1 nor axis 2 surfaced it.

Two tools declared `distribution_id` as **optional**:

```python
def download_fin_messages(distribution_id: str | None = None) -> dict:
    """Download one or several FIN messages ready for distribution."""
```

But the upstream Swift API requires `distribution-id` as a query parameter and returns HTTP 400 (`SwAP504`) without it. An agent calling either tool without args got a confusing 400 with no actionable diagnostic.

**Methodology takeaway.** Operational probing catches contract-mismatch bugs that pure model evaluation misses. The axes are genuinely orthogonal — each catches things the others don't.

---

## What got fixed in this session

**Cluster 5.** `distribution_id` made required in `app/main.py` and `tool_schemas.json`; probe paths updated. **Gateway v0.1.1 built and deployed** on dev + staging. Probe re-run: all 6 read-only tools 20/20 success.

Other findings deferred to the v2 backlog below.

---

## Limitations and v2 backlog

Honest accounting.

**What this is good for.** Establishing a baseline. Validating the methodology. Surfacing test-set bugs, product issues, and tier-specific findings.

**What this is NOT good for.** Treating any one headline number as final (cluster 1 contaminates Run A; Run B is the cleaner methodology control). Recommending a model based on these results alone (30 cases is a baseline, not a verdict). Inferring SLA-grade latency (single region, single time of day, sandbox).

**v2 backlog (captured, deferred):**

1. Test-set v2 — fix cluster-1 cases, diversity audit.
2. Temperature = 0 or N-run aggregation — eliminate non-determinism observed between two pinned-snapshot runs of the same Haiku model.
3. Stronger refusal pathway — add a `report_unsupported_request` meta-tool; re-measure cluster-4 substitution.
4. Tool renaming (`list_*` / `get_*`) — re-measure cluster-2.
5. MX synonym enrichment — re-measure cluster-3.
6. Multi-turn dimension — current cases are single-turn.
7. Latency from co-located deployment — cleaner numbers.

The methodology generalises cleanly. **Any MCP gateway can be evaluated using the same three axes; the test set is the only domain-specific artefact.**

---

## Code and reproducibility

- Repository: [github.com/mblake4u/swift-mcp-gateway](https://github.com/mblake4u/swift-mcp-gateway)
- Methodology ADR: [`docs/ADR-003-eval-methodology.md`](https://github.com/mblake4u/swift-mcp-gateway/blob/staging/docs/ADR-003-eval-methodology.md)
- Harness: [`evals/run_evals.py`](https://github.com/mblake4u/swift-mcp-gateway/blob/staging/evals/run_evals.py), [`evals/probe.py`](https://github.com/mblake4u/swift-mcp-gateway/blob/staging/evals/probe.py)
- Test set: [`evals/test_set.jsonl`](https://github.com/mblake4u/swift-mcp-gateway/blob/staging/evals/test_set.jsonl)
- Raw results: [`evals/results/`](https://github.com/mblake4u/swift-mcp-gateway/tree/staging/evals/results)
- Full analysis with adjusted-number tables: [`evals/results/2026-05-18-analysis.md`](https://github.com/mblake4u/swift-mcp-gateway/blob/staging/evals/results/2026-05-18-analysis.md)

Run yourself:

```bash
git clone https://github.com/mblake4u/swift-mcp-gateway
cd swift-mcp-gateway
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-evals.in
export ANTHROPIC_API_KEY=sk-ant-...

make eval                # latest each tier (~$2)
make eval-matched-gen    # matched gen 4.5 control (~$2)
make probe               # axis 3 against your token-server proxy
```

Total run cost: ~$5 in Anthropic API credits for both eval runs combined.
