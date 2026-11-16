#!/usr/bin/env python3
"""
==============================================================================
ROOK ACTUATOR (MODULE 5): DUAL-HEMISPHERE INTERLOCK, SYNTAX FIREWALL,
14B FENCE-TOLERANT XML PARSER, & MICRO-STEP DOWNSHIFT GOVERNOR
==============================================================================
Fixes the "Rook Passive Chatbot Bug":
  - 14B local models (`Qwen2.5-Coder-14B`) frequently wrap `<rykr_read>`,
    `<rykr_write>`, and `<rykr_cmd>` inside ```xml ... ``` fences, or wrap the
    inner body of `<rykr_write>` in ```python ... ``` fences.
  - `extract_tool_calls()` now extracts `<rykr_*>` tags whether or not the 14B
    model wrapped them in markdown fences, and sanitizes inner fences before
    passing the code through the In-Memory Syntax Firewall (`ast.parse` / `bash -n`).
==============================================================================
"""

import argparse
import ast
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

MAX_TOOL_STEPS = 3
STATE_FILE = "/tmp/rook_engine_state.json"
HERMETIC_KEYWORDS = ("abliterated", "hermes", "uncensored", "dolphin", "hermetic")

ORANGE = "\033[38;2;204;85;0m"
AMBER = "\033[38;2;255;140;0m"
GREEN = "\033[38;2;80;220;100m"
RED = "\033[38;2;255;85;85m"
BOLD = "\033[1m"
RESET = "\033[0m"


def is_hermetic_locked(explicit_hemisphere: str = "") -> Tuple[bool, str]:
    if explicit_hemisphere.upper() == "HERMETIC":
        return True, "Explicit HERMETIC Brainstorm Mode selected."
    if os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                st = json.load(f)
            if st.get("execution_locked") or str(st.get("hemisphere", "")).upper() == "HERMETIC":
                return True, f"Active model ({os.path.basename(st.get('model_path', 'hermetic'))}) is in HERMETIC Read-Only mode."
            mpath = str(st.get("model_path", "")).lower()
            if any(k in mpath for k in HERMETIC_KEYWORDS):
                return True, f"Abliterated/Hermetic model detected ({os.path.basename(mpath)})."
        except Exception:
            pass
    return False, ""


def unwrap_inner_code_fence(content: str) -> str:
    """
    If a 14B model wraps the body of <rykr_write> or <rykr_cmd> inside
    ```python ... ``` or ```bash ... ```, cleanly unwraps the outer fence
    so the written file or command contains pure executable code.
    """
    stripped = content.strip()
    m = re.match(r"^```[a-zA-Z0-9_-]*\n([\s\S]*?)\n```$", stripped)
    if m:
        return m.group(1)
    return content


def validate_syntax_firewall(target_path: Path, content: str) -> Tuple[bool, str]:
    """
    In-Memory Syntax Firewall:
    Checks .py, .json, and .sh files in memory before allowing a disk write.
    """
    suffix = target_path.suffix.lower()
    if suffix == ".py":
        try:
            ast.parse(content, filename=str(target_path))
            return True, "Python AST valid"
        except SyntaxError as exc:
            return False, f"Python SyntaxError on line {exc.lineno}, offset {exc.offset}: {exc.msg}"

    if suffix == ".json":
        try:
            json.loads(content)
            return True, "JSON schema valid"
        except Exception as exc:
            return False, f"Invalid JSON syntax: {exc}"

    if suffix == ".sh" or content.startswith("#!/bin/bash") or content.startswith("#!/usr/bin/env bash"):
        try:
            res = subprocess.run(
                ["bash", "-n"],
                input=content,
                text=True,
                capture_output=True,
                timeout=5,
            )
            if res.returncode != 0:
                return False, f"Bash syntax error: {res.stderr.strip()}"
            return True, "Bash syntax valid"
        except Exception:
            pass

    return True, "Unchecked text format"


def extract_tool_calls(llm_output: str) -> List[Dict[str, Any]]:
    """
    Extracts <rykr_read>, <rykr_write>, and <rykr_cmd> tags even when a 14B
    local model wraps them inside ```xml ... ``` fences.
    """
    positioned_calls = []

    # 1. <rykr_read .../> (supports any attribute order & optional quotes)
    for m in re.finditer(
        r"^[ \t]*<rykr_read\s+([^>\n]+?)/?>",
        llm_output,
        re.MULTILINE,
    ):
        attrs = m.group(1)
        pm = re.search(r"path\s*=\s*[\"']([^\"']+)[\"']", attrs)
        if not pm:
            continue
        sm = re.search(r"start\s*=\s*[\"']?(\d+)[\"']?", attrs)
        em = re.search(r"end\s*=\s*[\"']?(\d+)[\"']?", attrs)
        positioned_calls.append((m.start(), {
            "tool": "read",
            "path": pm.group(1),
            "start": int(sm.group(1)) if sm else 1,
            "end": int(em.group(1)) if em else 120,
        }))

    # 2. <rykr_write path="...">...</rykr_write>
    for m in re.finditer(
        r"^[ \t]*<rykr_write\s+path=[\"']([^\"']+)[\"']>\n?([\s\S]*?)\n?[ \t]*</rykr_write>",
        llm_output,
        re.MULTILINE,
    ):
        positioned_calls.append((m.start(), {
            "tool": "write",
            "path": m.group(1),
            "content": unwrap_inner_code_fence(m.group(2)),
        }))

    # 3. <rykr_cmd>...</rykr_cmd> (separate from 3B ```rykr_cmd> ... ``` fence quirk so inner ```bash never truncates)
    cmd_spans = []
    for m in re.finditer(
        r"^[ \t]*<rykr_cmd>\n?([\s\S]*?)\n?[ \t]*</rykr_cmd>",
        llm_output,
        re.MULTILINE,
    ):
        cmd_spans.append((m.start(), m.end()))
        positioned_calls.append((m.start(), {
            "tool": "cmd",
            "command": unwrap_inner_code_fence(m.group(1)).strip(),
        }))

    for m in re.finditer(
        r"^[ \t]*```rykr_cmd>?\n?([\s\S]*?)\n?[ \t]*```",
        llm_output,
        re.MULTILINE,
    ):
        if any(s <= m.start() < e for s, e in cmd_spans):
            continue
        positioned_calls.append((m.start(), {
            "tool": "cmd",
            "command": unwrap_inner_code_fence(m.group(1)).strip(),
        }))

    positioned_calls.sort(key=lambda item: item[0])
    return [c for _, c in positioned_calls]


def compute_call_signature(call: Dict[str, Any]) -> str:
    raw = json.dumps(call, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def prompt_downshift_gate(call: Dict[str, Any], syntax_note: str = "") -> bool:
    if not sys.stdin.isatty():
        return True
    tool = call["tool"].upper()
    print(f"\n{ORANGE}╔══ [14B DOWNSHIFT GATE: 1-STEP VERIFICATION] ═════════════════════════════════╗{RESET}")
    if tool == "WRITE":
        lines = call["content"].splitlines()
        is_self_mod = "/opt/rook" in call["path"] or "rykr_harness" in call["path"]
        self_badge = f" {RED}[SELF-MODIFICATION]{RESET}" if is_self_mod else ""
        print(f"{ORANGE}║{RESET} Action : {BOLD}{AMBER}WRITE FILE{RESET}{self_badge} -> {call['path']} ({len(lines)} lines | {GREEN}{syntax_note}{RESET})")
        preview = "\n".join(f"{ORANGE}║{RESET}   {line[:72]}" for line in lines[:8])
        print(preview)
        if len(lines) > 8:
            print(f"{ORANGE}║{RESET}   ... ({len(lines) - 8} more lines)")
    elif tool == "CMD":
        print(f"{ORANGE}║{RESET} Action : {BOLD}{AMBER}SHELL CMD{RESET}  -> {call['command']}")
    print(f"{ORANGE}╚══════════════════════════════════════════════════════════════════════════════╝{RESET}")
    try:
        ans = input(f"{BOLD}{AMBER}Execute this 1 micro-step? (Pre-step snapshot ready for ~rollback) [y/N]: {RESET}").strip().lower()
        return ans in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def _emit(event_cb: Optional[Callable[[str, str], None]], tag: str, msg: str) -> None:
    if event_cb is None:
        return
    try:
        event_cb(tag, msg)
    except Exception:
        pass


def _sanitize_hanging_commands(cmd_str: str) -> str:
    """Prevents un-bounded commands like bare `ping <host>` from hanging until timeout."""
    pattern = re.compile(r"(^|(?:&&|\|\||[;|])\s*)(ping6?)(\s+)([^;&|\n]+)")

    def _repl(match: re.Match) -> str:
        prefix, cmd_name, space, args = match.groups()
        if re.search(r"(?:^|\s)-c(?:\s*\d+|\b)", args):
            return match.group(0)
        return f"{prefix}{cmd_name} -c 2 -W 2{space}{args}"

    return pattern.sub(_repl, cmd_str)


def execute_single_call(
    call: Dict[str, Any],
    workspace_root: str,
    timeout: int = 30,
    explicit_hemisphere: str = "",
    downshift_gate: bool = False,
    event_cb: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    tool = call["tool"]
    ws = Path(workspace_root).resolve()
    locked, lock_reason = is_hermetic_locked(explicit_hemisphere)

    if tool == "read":
        target = Path(os.path.expanduser(call["path"]))
        if not target.is_absolute():
            target = (ws / target).resolve()
        s = max(1, call.get("start", 1))
        e = call.get("end", 80)
        _emit(event_cb, "READ", f"{target} (lines {s}-{e})")
        if not target.is_file():
            return {"tool": "read", "status": "ERROR", "path": str(target), "output": f"File not found: {target}"}
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            e = min(len(lines), e)
            snippet = "".join(f"{i}: {lines[i - 1]}" for i in range(s, e + 1))
            if len(snippet) > 2000:
                snippet = snippet[:2000] + "\n...[TRUNCATED AT 2000 CHARS FOR LOCAL APU CONTEXT]..."
            return {"tool": "read", "status": "SUCCESS", "path": str(target), "lines": f"{s}-{e}", "output": snippet}
        except Exception as exc:
            return {"tool": "read", "status": "ERROR", "path": str(target), "output": str(exc)}

    if locked and tool in ("write", "cmd"):
        _emit(event_cb, "LOCKED", f"Hermetic read-only interlock blocked {tool}")
        return {
            "tool": tool,
            "status": "HERMETIC_READONLY_LOCK",
            "reason": (
                f"PYTHON ACTUATOR INTERLOCK ENGAGED: {lock_reason} "
                "File writes and OS shell execution are physically disabled in Hermetic Brainstorm mode. "
                "Switch the Brain Selector to [BUILDER] to execute code or commands."
            ),
        }

    if tool == "write":
        target = Path(os.path.expanduser(call["path"]))
        if not target.is_absolute():
            target = (ws / target).resolve()
        content = call["content"]
        if not content.endswith("\n"):
            content += "\n"

        syntax_ok, syntax_msg = validate_syntax_firewall(target, content)
        if not syntax_ok:
            _emit(event_cb, "FIREWALL", f"Blocked {target.name}: {syntax_msg}")
            return {
                "tool": "write",
                "status": "SYNTAX_FIREWALL_BLOCKED",
                "path": str(target),
                "error": f"14B Syntax Firewall blocked write to {target.name}: {syntax_msg}. Fix syntax and retry.",
            }

        if downshift_gate and not prompt_downshift_gate(call, syntax_note=syntax_msg):
            return {
                "tool": "write",
                "status": "OPERATOR_DEFERRED_MICROSTEP",
                "path": str(target),
                "reason": "Operator declined or deferred this write micro-step at the [y/N] confirmation gate.",
            }

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            nbytes = len(content.encode("utf-8"))
            _emit(event_cb, "WRITE", f"{target} ({nbytes} bytes)")
            return {
                "tool": "write",
                "status": "SUCCESS",
                "path": str(target),
                "self_modified": ("/opt/rook" in str(target) or "rykr_harness" in str(target)),
                "syntax_check": syntax_msg,
                "bytes_written": nbytes,
            }
        except Exception as exc:
            return {"tool": "write", "status": "ERROR", "path": str(target), "output": str(exc)}

    if tool == "cmd":
        if downshift_gate and not prompt_downshift_gate(call):
            return {
                "tool": "cmd",
                "status": "OPERATOR_DEFERRED_MICROSTEP",
                "command": call["command"],
                "reason": "Operator declined or deferred this command micro-step at the [y/N] confirmation gate.",
            }

        cmd_str = _sanitize_hanging_commands(call["command"])
        _emit(event_cb, "CMD", cmd_str)
        started = time.monotonic()
        collected: List[str] = []
        streamed_lines = 0
        proc: Optional[subprocess.Popen] = None

        def _drain_stdout(pipe: Any) -> None:
            nonlocal streamed_lines
            try:
                for raw_line in iter(pipe.readline, ""):
                    collected.append(raw_line)
                    clean = raw_line.rstrip("\r\n")
                    if clean and streamed_lines < 120:
                        streamed_lines += 1
                        _emit(event_cb, "STDOUT", clean[:400])
            finally:
                try:
                    pipe.close()
                except Exception:
                    pass

        try:
            proc = subprocess.Popen(
                cmd_str,
                shell=True,
                cwd=str(ws),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            reader = threading.Thread(target=_drain_stdout, args=(proc.stdout,), daemon=True)
            reader.start()
            rc = proc.wait(timeout=timeout)
            reader.join(timeout=2.0)
            elapsed = time.monotonic() - started
            _emit(event_cb, "CMD OK" if rc == 0 else "CMD ERR", f"exit={rc} ({elapsed:.2f}s)")
            combined = "".join(collected).strip()
            if len(combined) > 2000:
                combined = combined[:2000] + "\n...[TRUNCATED AT 2000 CHARS FOR LOCAL APU CONTEXT]..."
            return {
                "tool": "cmd",
                "status": "SUCCESS" if rc == 0 else "NON_ZERO_EXIT",
                "exit_code": rc,
                "command": cmd_str,
                "output": combined,
            }
        except subprocess.TimeoutExpired:
            if proc is not None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            _emit(event_cb, "TIMEOUT", f"Timed out after {timeout}s")
            partial = "".join(collected).strip()
            msg = f"Timed out after {timeout}s"
            if partial:
                msg += "\nPartial output:\n" + partial[:1500]
            return {"tool": "cmd", "status": "TIMEOUT", "command": cmd_str, "output": msg}
        except Exception as exc:
            _emit(event_cb, "CMD ERR", str(exc))
            return {"tool": "cmd", "status": "ERROR", "command": cmd_str, "output": str(exc)}

    return {"tool": tool, "status": "ERROR", "output": f"Unknown tool: {tool}"}


def process_llm_response(
    llm_output: str,
    workspace_root: str,
    seen_signatures: set,
    timeout: int = 30,
    explicit_hemisphere: str = "",
    downshift_gate: bool = False,
    event_cb: Optional[Callable[[str, str], None]] = None,
) -> Tuple[bool, List[Dict[str, Any]], str]:
    calls = extract_tool_calls(llm_output)
    if not calls:
        return False, [], ""

    # In 14B Downshift mode, allow any <rykr_read> calls, plus at most ONE <rykr_write> or <rykr_cmd>
    if downshift_gate:
        filtered = []
        mutation_count = 0
        for c in calls:
            if c["tool"] == "read":
                filtered.append(c)
            elif mutation_count < 1:
                filtered.append(c)
                mutation_count += 1
        calls = filtered

    results = []
    for c in calls:
        sig = compute_call_signature(c)
        if sig in seen_signatures:
            _emit(event_cb, "ANTI-LOOP", f"Blocked duplicate {c['tool']} call")
            results.append({
                "tool": c["tool"],
                "status": "CIRCUIT_BREAKER_TRIPPED",
                "reason": "Identical tool call emitted twice in the same turn. Halting loop.",
            })
            break
        seen_signatures.add(sig)
        results.append(
            execute_single_call(
                c,
                workspace_root,
                timeout=timeout,
                explicit_hemisphere=explicit_hemisphere,
                downshift_gate=downshift_gate,
                event_cb=event_cb,
            )
        )

    telemetry_str = "<TOOL_TELEMETRY>\n" + json.dumps(results, indent=2) + "\n</TOOL_TELEMETRY>"
    return True, results, telemetry_str


def main():
    parser = argparse.ArgumentParser(description="Rook Actuator (Module 5): Dual-Hemisphere & 14B Downshift Governor")
    parser.add_argument("--workspace", default="~/rook", help="Workspace root directory")
    parser.add_argument("--hemisphere", default="", help="Optional explicit hemisphere override (HERMETIC or BUILDER)")
    parser.add_argument("--downshift", action="store_true", help="Enable 14B Downshift Gate & 1-step cap")
    parser.add_argument("--response", required=True, help="Raw LLM output string containing potential XML tool tags")
    args = parser.parse_args()

    seen = set()
    has_calls, results, telemetry = process_llm_response(
        args.response,
        args.workspace,
        seen,
        explicit_hemisphere=args.hemisphere,
        downshift_gate=args.downshift,
    )
    sys.stdout.write(json.dumps({"has_calls": has_calls, "results": results, "telemetry_block": telemetry}, indent=2) + "\n")


if __name__ == "__main__":
    main()
