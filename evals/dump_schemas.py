"""
Best-effort tool-schema dumper. Introspects the FastMCP server defined in
app/main.py and writes Anthropic-compatible tool schemas to evals/tool_schemas.json.

Used by `make refresh-schemas`. If FastMCP's introspection API changes and this
script breaks, `evals/tool_schemas.json` can be hand-edited as a fallback —
the file is the source of truth for evals at run time.

Usage:
    python evals/dump_schemas.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Add repo root so we can import the app package
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

OUTPUT_PATH = REPO_ROOT / "evals" / "tool_schemas.json"


async def _list_tools_async(mcp) -> list[dict]:
    """Call FastMCP's async list_tools() and normalise to Anthropic format."""
    tools = await mcp.list_tools()
    out: list[dict] = []
    for tool in tools:
        # FastMCP Tool objects expose .name, .description, .inputSchema.
        # Accept either object-attribute or dict access.
        if isinstance(tool, dict):
            name = tool.get("name")
            description = tool.get("description", "")
            input_schema = tool.get("inputSchema") or tool.get("input_schema")
        else:
            name = getattr(tool, "name", None)
            description = getattr(tool, "description", "") or ""
            input_schema = getattr(tool, "inputSchema", None) or getattr(
                tool, "input_schema", None
            )

        if not name or input_schema is None:
            raise RuntimeError(
                f"Could not extract name/inputSchema from tool: {tool!r}"
            )

        out.append(
            {
                "name": name,
                "description": description,
                "input_schema": input_schema,
            }
        )
    return out


def main() -> None:
    try:
        from app.main import mcp  # type: ignore
    except ImportError as e:
        sys.exit(
            f"Could not import app.main.mcp: {e}\n"
            "Run this script from the repo root, or install fastmcp."
        )

    try:
        schemas = asyncio.run(_list_tools_async(mcp))
    except Exception as e:
        sys.exit(
            f"FastMCP introspection failed: {type(e).__name__}: {e}\n"
            f"Hand-edit {OUTPUT_PATH} as a fallback."
        )

    OUTPUT_PATH.write_text(json.dumps(schemas, indent=2) + "\n")
    print(f"Wrote {len(schemas)} tool schemas to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
