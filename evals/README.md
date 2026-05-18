# Evals

Evaluation harness for the Swift MCP Gateway.

**Methodology:** see [`docs/ADR-003-eval-methodology.md`](../docs/ADR-003-eval-methodology.md).

## Files

| File | Purpose |
|---|---|
| `test_set.jsonl` | 30 hand-curated cases across three axes (tool selection · argument fidelity · negative) |
| `tool_schemas.json` | Frozen Anthropic-format tool schemas — source of truth for runs |
| `run_evals.py` | Harness for axes 1 + 2 (tool-selection accuracy, argument fidelity). Anthropic API direct, prompt-cached, multi-model |
| `probe.py` | Harness for axis 3 (latency, coverage). Hits the live gateway (read-only tools only — mutating tools deliberately not probed). |
| `dump_schemas.py` | Best-effort schema refresher — introspects FastMCP and rewrites `tool_schemas.json` |
| `results/` | Append-only results directory; one JSON + one Markdown per run |

## Install

The eval harness has its own dependencies (separate from the gateway runtime). Install once:

```bash
pip install -r requirements-evals.in
```

## Run

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python evals/run_evals.py
```

Optional flags:

```bash
python evals/run_evals.py --models claude-sonnet-4-5 claude-haiku-4-5
python evals/run_evals.py --test-set evals/test_set.jsonl --output evals/results
```

Or via `make`:

```bash
make eval               # run evals against default models
make refresh-schemas    # regenerate tool_schemas.json from app/main.py
```

## Cost

Per full run (30 cases × 3 models + judge calls on 3 free-text args):

- Without prompt caching: ~90 full schema reads. Schema is ~3k tokens.
- With prompt caching (default): one schema read per model = 3 cache writes + 87 cache reads. **~10× cost reduction.**

Actual cache hit ratio is printed in each results Markdown.

## Adding test cases

Edit `test_set.jsonl`. Each case is one JSON object per line with this shape:

```json
{
  "id": "<short id>",
  "axis": "tool_selection" | "argument_fidelity" | "negative",
  "question": "<natural-language user question>",
  "expected_tool": "<tool name>" | null,
  "expected_args": {"<arg>": <typed value>, ...} | null,
  "freeform_args": {"<arg>": "<rubric describing expected semantic content>"} | null,
  "notes": "<one-line explanation>"
}
```

For `argument_fidelity` cases: `expected_args` holds args scored by strict equality; `freeform_args` holds args scored by LLM-judge with the rubric as the prompt.

For `negative` cases: `expected_tool` is `null` — the model should respond in natural language without calling any tool.
