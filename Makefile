.PHONY: eval refresh-schemas test help

help:
	@echo "Available targets:"
	@echo "  eval              Run evals against latest-each-tier models (opus-4-7, sonnet-4-6, haiku-4-5)"
	@echo "  eval-matched-gen  Run evals against matched-generation 4.5 (fully pinned, methodology control)"
	@echo "  probe             Run the operational probe (axis 3 — latency + coverage) against live gateway"
	@echo "  refresh-schemas   Regenerate evals/tool_schemas.json from app/main.py"
	@echo "  test              Run pytest smoke tests"

eval:
	python evals/run_evals.py

eval-matched-gen:
	python evals/run_evals.py \
		--models claude-opus-4-5-20251101 claude-sonnet-4-5-20250929 claude-haiku-4-5-20251001

probe:
	python evals/probe.py

refresh-schemas:
	python evals/dump_schemas.py

test:
	pytest tests/ -v
