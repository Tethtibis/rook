#!/usr/bin/env python3
"""
==============================================================================
RYKR-ACTUATOR (MODULE 5): CODE-FENCE-SAFE XML INTERCEPTOR & 3-STEP GOVERNOR
==============================================================================
Part of the Sovereign Rykr Harness (Zero-Pip Python 3 Standard Library).
Responsibilities:
  1. Markdown-Fence-Safe XML Parsing (Red-Team Flaw #3 Mitigation):
     - Strips ```...``` fenced blocks before scanning for executable tags so
       documentation examples never self-trigger execution.
  2. Closed-Loop Sensor & Appliance Execution:
     - `<rykr_read path="..." start="1" end="200"/>`
     - `<rykr_write path="...">...</rykr_write>` (Full evolutionary autonomy)
     - `<rykr_cmd>...</rykr_cmd>` (Shell & `rykr-cmd` push-button appliances)
  3. 3-Step Autonomous Governor & Identical-Call Circuit Breaker:
     - Hard-caps autonomous tool loops at `MAX_TOOL_STEPS = 3` per turn.
     - Halts immediately if the LLM emits the exact same tool call twice.
==============================================================================
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple

MAX_TOOL_STEPS = 3


def strip_markdown_fences(text: str) -> str:
    """Removes ```...``` fenced code blocks so example tags inside docs never execute."""
    return re.sub(r"```[\s\S]*?```", "", text)


def extract_tool_calls(llm_output: str) -> List[Dict[str, Any]]:
    """
    Extracts executable <rykr_read>, <rykr_write>, and <rykr_cmd> tags that
    appear at the start of a line outside markdown code fences.
    """
    clean = strip_markdown_fences(llm_output)
    positioned_calls = []

    # 1. <rykr_read path="..." [start="..."] [end="..."]/>
    for m in re.finditer(
        r"^<rykr_read\s+path=\"([^\"]+)\"(?:\s+start=\"(\d+)\")?(?:\s+end=\"(\d+)\")?\s*/?>",
        clean,
        re.MULTILINE,
    ):
        positioned_calls.append((m.start(), {
            "tool": "read",
            "path": m.group(1),
            "start": int(m.group(2)) if m.group(2) else 1,
            "end": int(m.group(3)) if m.group(3) else 250,
        }))

    # 2. <rykr_write path="...">...</rykr_write>
    for m in re.finditer(
        r"^<rykr_write\s+path=\"([^\"]+)\">\n?([\s\S]*?)\n?^</rykr_write>",
        clean,
        re.MULTILINE,
    ):
        positioned_calls.append((m.start(), {
            "tool": "write",
            "path": m.group(1),
            "content": m.group(2),
        }))

    # 3. <rykr_cmd>...</rykr_cmd>
    for m in re.finditer(
        r"^<rykr_cmd>\n?([\s\S]*?)\n?^</rykr_cmd>",
        clean,
        re.MULTILINE,
    ):
        positioned_calls.append((m.start(), {
            "tool": "cmd",
            "command": m.group(1).strip(),
        }))

    positioned_calls.sort(key=lambda item: item[0])
    return [c for _, c in positioned_calls]


def compute_call_signature(call: Dict[str, Any]) -> str:
    raw = json.dumps(call, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def execute_single_call(call: Dict[str, Any], workspace_root: str, timeout: int = 30) -> Dict[str, Any]:
    tool = call["tool"]
    ws = Path(workspace_root).resolve()

    if tool == "read":
        target = Path(os.path.expanduser(call["path"]))
        if not target.is_absolute():
            target = (ws / target).resolve()
        if not target.is_file():
            return {"tool": "read", "status": "ERROR", "path": str(target), "output": f"File not found: {target}"}
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            s = max(1, call.get("start", 1))
            e = min(len(lines), call.get("end", 250))
            snippet = "".join(f"{i}: {lines[i - 1]}" for i in range(s, e + 1))
            return {"tool": "read", "status": "SUCCESS", "path": str(target), "lines": f"{s}-{e}", "output": snippet}
        except Exception as exc:
            return {"tool": "read", "status": "ERROR", "path": str(target), "output": str(exc)}

    if tool == "write":
        target = Path(os.path.expanduser(call["path"]))
        if not target.is_absolute():
            target = (ws / target).resolve()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            content = call["content"]
            if not content.endswith("\n"):
                content += "\n"
            with open(target, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            return {
                "tool": "write",
                "status": "SUCCESS",
                "path": str(target),
                "bytes_written": len(content.encode("utf-8")),
            }
        except Exception as exc:
            return {"tool": "write", "status": "ERROR", "path": str(target), "output": str(exc)}

    if tool == "cmd":
        cmd_str = call["command"]
        try:
            res = subprocess.run(
                cmd_str,
                shell=True,
                cwd=str(ws),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            combined = (res.stdout + ("\n" + res.stderr if res.stderr else "")).strip()
            if len(combined) > 8000:
                combined = combined[:8000] + "\n...[TRUNCATED AT 8000 CHARS]..."
            return {
                "tool": "cmd",
                "status": "SUCCESS" if res.returncode == 0 else "NON_ZERO_EXIT",
                "exit_code": res.returncode,
                "command": cmd_str,
                "output": combined,
            }
        except subprocess.TimeoutExpired:
            return {"tool": "cmd", "status": "TIMEOUT", "command": cmd_str, "output": f"Timed out after {timeout}s"}
        except Exception as exc:
            return {"tool": "cmd", "status": "ERROR", "command": cmd_str, "output": str(exc)}

    return {"tool": tool, "status": "ERROR", "output": f"Unknown tool: {tool}"}


def process_llm_response(
    llm_output: str,
    workspace_root: str,
    seen_signatures: set,
    timeout: int = 30,
) -> Tuple[bool, List[Dict[str, Any]], str]:
    """
    Scans `llm_output` for executable tags, enforces the Identical-Call Circuit Breaker,
    executes any valid calls, and formats the `<TOOL_TELEMETRY>` feedback block.
    Returns: (has_tool_calls, results_list, formatted_telemetry_str)
    """
    calls = extract_tool_calls(llm_output)
    if not calls:
        return False, [], ""

    results = []
    for c in calls:
        sig = compute_call_signature(c)
        if sig in seen_signatures:
            results.append({
                "tool": c["tool"],
                "status": "CIRCUIT_BREAKER_TRIPPED",
                "reason": "Identical tool call emitted twice in the same turn. Halting loop.",
            })
            break
        seen_signatures.add(sig)
        results.append(execute_single_call(c, workspace_root, timeout=timeout))

    telemetry_str = "<TOOL_TELEMETRY>\n" + json.dumps(results, indent=2) + "\n</TOOL_TELEMETRY>"
    return True, results, telemetry_str


def main():
    parser = argparse.ArgumentParser(description="Rykr-Actuator (Module 5): Code-Fence-Safe XML Tool Interceptor")
    parser.add_argument("--workspace", default=os.path.expanduser("~/rook"), help="Workspace root directory")
    parser.add_argument("--response", required=True, help="Raw LLM output string containing potential XML tool tags")
    args = parser.parse_args()

    seen = set()
    has_calls, results, telemetry = process_llm_response(args.response, args.workspace, seen)
    sys.stdout.write(json.dumps({"has_calls": has_calls, "results": results, "telemetry_block": telemetry}, indent=2) + "\n")


if __name__ == "__main__":
    main()
