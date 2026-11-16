#!/usr/bin/env python3
"""
==============================================================================
ROOK-CONTEXT (MODULE 3): 4-TIER MEMORY BUS LOADER & DYNAMIC TOKEN CAPPER
==============================================================================
Powered by The Rykr Framework (Zero-Pip Python 3 Standard Library).
Responsibilities:
  1. Assembles Rook's 4-Tier Memory Bus (T0 ROOK_KERNEL.md + T1 XML Tool
     Contract + T3 ROOK_OPERATOR.md).
  2. Dynamically caps conversation history tokens from `live_session.jsonl`
     to prevent context collapse on local GPU models.
==============================================================================
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

SCRIPT_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

ROOK_TOOL_CONTRACT = """
## [T1: ROOK DETERMINISTIC XML TOOL CONTRACT (ZERO-JSON-ESCAPE)]
When you need to inspect sensors, read/write files, or run deterministic math/CSV/OCR tools, emit one or more of the following tags at the start of a line (NEVER inside markdown ``` code fences when you want them executed):

1. Read a file (optional line bounds):
<rykr_read path="/abs/or/rel/path" start="1" end="200"/>

2. Write or overwrite a file (pre-turn snapshot is active):
<rykr_write path="/abs/or/rel/path">
...exact file contents...
</rykr_write>

3. Execute a POSIX shell command or deterministic Rook Workbench tool (`--calc`, `--audit-csv`, `--ocr`, `--run-button`, `--remember`):
<rykr_cmd>
python3 /opt/rook/rook_workbench.py --calc "(650 * 12) - 125.50"
</rykr_cmd>

CRITICAL RULES:
- Your name is **Rook** (Deterministic Local Field Unit). You are NOT `Rykr-Prime`.
- Never guess or mentally calculate math, CSV column sums, or image contents. Rely on deterministic receipts from `rook_workbench.py`.
- Whenever the Operator asks you to remember a preference/fact, run `rook_workbench.py --remember "<fact>"` immediately (check Workbench path below if not in `/opt/rook`).
- Never emit bare `ping <host>` without `-c 2`; use `curl -fsSL -m 10 <url>` for web/repo checks.
- When you emit an executable tag, stop generating and wait for `<TOOL_TELEMETRY>` in the next step.
""".strip()


def estimate_tokens(text: str) -> int:
    """Fast heuristic token estimator (~4 chars per token)."""
    return max(1, len(text) // 4)


def read_file_safe(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def assemble_memory_bus(
    workspace_root: str,
    turns: List[Dict[str, Any]],
    current_conditioned_prompt: str,
    engine_profile: str = "rook",
    archive_tail_lines: int = 20,
) -> Dict[str, Any]:
    """
    Loads T0 (ROOK_KERNEL.md), T1 (ROOK_TOOL_CONTRACT), and T3 (ROOK_OPERATOR.md)
    and slices conversation history to fit the local GPU context budget.
    """
    ws = Path(workspace_root).resolve()

    # T0: Rook Kernel (ROOK_KERNEL.md)
    for cand in (SCRIPT_DIR / "ROOK_KERNEL.md", Path("/opt/rook/ROOK_KERNEL.md"), ws / "ROOK_KERNEL.md"):
        if cand.is_file():
            t0_path = cand
            break
    else:
        t0_path = SCRIPT_DIR / "ROOK_KERNEL.md"
    t0_text = read_file_safe(t0_path)

    # T3: Rook Operator Profile (ROOK_OPERATOR.md)
    for cand in (SCRIPT_DIR / "ROOK_OPERATOR.md", Path("/opt/rook/ROOK_OPERATOR.md"), ws / "ROOK_OPERATOR.md"):
        if cand.is_file():
            t3_path = cand
            break
    else:
        t3_path = SCRIPT_DIR / "ROOK_OPERATOR.md"
    t3_text = read_file_safe(t3_path)

    system_instruction = (
        f"{t0_text}\n\n"
        f"{ROOK_TOOL_CONTRACT}\n\n"
        f"Active Workbench Script: `{SCRIPT_DIR / 'rook_workbench.py'}`\n\n"
        f"## [T3: ROOK OPERATOR PROFILE]\n{t3_text}"
    ).strip()

    is_local = any(k in engine_profile.lower() for k in ("rook", "ollama", "local", "necro", "openai"))
    history_budget = 3500 if is_local else 64000

    selected_turns = []
    accumulated_tokens = 0
    for t in reversed(turns):
        t_tokens = estimate_tokens(t.get("content", ""))
        if accumulated_tokens + t_tokens > history_budget and selected_turns:
            break
        selected_turns.append({
            "role": "assistant" if t.get("role") == "assistant" else "user",
            "content": t.get("content", ""),
        })
        accumulated_tokens += t_tokens

    selected_turns.reverse()
    selected_turns.append({
        "role": "user",
        "content": current_conditioned_prompt,
    })

    sys_tokens = estimate_tokens(system_instruction)
    prompt_tokens = estimate_tokens(current_conditioned_prompt)

    return {
        "engine_profile": engine_profile,
        "token_telemetry": {
            "system_tokens_est": sys_tokens,
            "history_tokens_est": accumulated_tokens,
            "current_turn_tokens_est": prompt_tokens,
            "total_input_tokens_est": sys_tokens + accumulated_tokens + prompt_tokens,
            "history_budget_cap": history_budget,
            "turns_included": len(selected_turns),
        },
        "system_instruction": system_instruction,
        "messages": selected_turns,
    }


def main():
    parser = argparse.ArgumentParser(description="Rook-Context (Module 3): Memory Bus Loader")
    parser.add_argument("--workspace", default="~/rook", help="Workspace root directory")
    parser.add_argument("--prompt", required=True, help="Conditioned user prompt from Module 2")
    parser.add_argument("--engine", default="rook", help="Active engine profile")
    parser.add_argument("--turns-json", default="[]", help="JSON array of prior turns")
    args = parser.parse_args()
    turns = json.loads(args.turns_json)
    bus = assemble_memory_bus(args.workspace, turns, args.prompt, args.engine)
    sys.stdout.write(json.dumps(bus, indent=2) + "\n")


if __name__ == "__main__":
    main()
