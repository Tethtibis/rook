#!/usr/bin/env python3
"""
==============================================================================
ROOK-HARNESS: DETERMINISTIC 5-PILLAR LOCAL OPERATING SYSTEM HARNESS
==============================================================================
Powered by The Rykr Framework (Zero-Pip Python 3 Standard Library).
Unifies the isolated Rook modules:
  • Module 1 (`rook_snap.py`)     : Snap-To Multiplexer & Atomic Rollback
  • Module 2 (`rook_governor.py`) : Packet Ingress & Genesis State Machine
  • Module 3 (`rook_context.py`)  : Rook Memory Bus & Dynamic Token Capper
  • Module 4 (`rook_engine.py`)   : Local Loopback GGUF Socket
  • Module 5 (`rook_actuator.py`) : Code-Fence-Safe XML Sensor & Tool Loop
==============================================================================
"""

import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from rook_snap import HarnessLedger, render_snap_summary, DEFAULT_STATE_DIR, DEFAULT_SNAP_DIR
from rook_governor import evaluate_turn
from rook_context import assemble_memory_bus
from rook_engine import dispatch_inference, DEFAULT_VAULT_PATH
from rook_actuator import process_llm_response, MAX_TOOL_STEPS


def enforce_rook_nomenclature(text: str) -> str:
    """
    Deterministically ensures that local models (including fine-tuned weights
    such as rykr-sat-14b.gguf) never self-identify as 'Rykr-Prime' or 'Rykr'.
    """
    if not text:
        return text
    out = re.sub(r"\bI am Rykr-Prime\b", "I am Rook (Local Field Unit)", text, flags=re.IGNORECASE)
    out = re.sub(r"\bI am Rykr\b", "I am Rook", out, flags=re.IGNORECASE)
    out = re.sub(r"\bRYKR-PRIME\b", "ROOK-LOCAL", out)
    return out


def run_turn_pipeline(
    user_input: str,
    workspace_dir: str,
    ledger: HarnessLedger,
    engine_override: str = None,
    vault_path: str = DEFAULT_VAULT_PATH,
    max_steps: int = MAX_TOOL_STEPS,
) -> dict:
    """Executes one complete 5-module Rook turn (with up to `max_steps` closed-loop tool calls)."""
    summary = render_snap_summary(ledger, tail_count=1)
    current_state = summary["active_genesis_state"]
    active_engine = engine_override or "rook"

    # 1. Module 2: Governor evaluation
    directive = evaluate_turn(user_input, current_state=current_state)

    if directive["type"] == "HARNESS_COMMAND":
        action = directive["harness_action"]
        if action == "ROLLBACK":
            rb = ledger.rollback_latest(directive.get("snapshot_id"))
            return {"type": "HARNESS_COMMAND", "action": "ROLLBACK", "result": rb}
        if action == "SWITCH_ENGINE":
            new_eng = directive["target_engine"]
            turns, _ = ledger.load_turns()
            ledger._save_meta(genesis_state=current_state, engine=new_eng, turn_count=len(turns))
            return {"type": "HARNESS_COMMAND", "action": "SWITCH_ENGINE", "engine": new_eng}
        if action == "STATUS":
            return {"type": "HARNESS_COMMAND", "action": "STATUS", "status": render_snap_summary(ledger)}
        if action == "CLOSE":
            return {"type": "HARNESS_COMMAND", "action": "CLOSE"}

    next_state = directive["genesis_state"]

    # 2. Module 1: Pre-Turn Atomic Snapshot
    snapshot_meta = None
    if directive.get("take_pre_turn_snapshot", True):
        snapshot_meta = ledger.create_checkpoint(workspace_dir, label=f"turn_{next_state.lower()}")

    # 3. Module 3: Rook Memory Bus assembly
    prior_turns, _ = ledger.load_turns()
    bus = assemble_memory_bus(
        workspace_root=workspace_dir,
        turns=prior_turns,
        current_conditioned_prompt=directive["conditioned_prompt"],
        engine_profile=active_engine,
    )

    messages = list(bus["messages"])
    system_instruction = bus["system_instruction"]
    seen_tool_signatures = set()
    tool_steps_executed = 0
    mutation_steps_executed = 0
    read_steps_executed = 0
    step_logs = []
    final_response = ""

    is_local_brain = any(k in active_engine.lower() for k in ("rook", "ollama", "local", "openai"))
    max_total_steps = min(max_steps, 3) if is_local_brain else max_steps
    max_mutations = 1 if is_local_brain else max_steps

    # 4. Module 4 & Module 5: Closed-Loop Inference + Actuator Cycle
    while True:
        try:
            inf = dispatch_inference(
                engine_spec=active_engine,
                system_instruction=system_instruction,
                messages=messages,
                vault_path=vault_path,
            )
        except Exception as exc:
            if step_logs:
                final_response = f"[Engine interrupted after step {tool_steps_executed}: {exc}]"
                break
            raise
        assistant_text = enforce_rook_nomenclature(inf.get("response", ""))
        final_response = assistant_text

        if tool_steps_executed >= max_total_steps:
            break

        has_calls, tool_results, telemetry_block = process_llm_response(
            llm_output=assistant_text,
            workspace_root=workspace_dir,
            seen_signatures=seen_tool_signatures,
            downshift_gate=is_local_brain,
        )
        if not has_calls:
            break

        tool_steps_executed += 1
        if any(r.get("tool") in ("write", "cmd") for r in tool_results):
            mutation_steps_executed += 1
        else:
            read_steps_executed += 1

        step_logs.append({"step": tool_steps_executed, "results": tool_results})
        if tool_steps_executed >= max_total_steps or mutation_steps_executed >= max_mutations:
            telemetry_block += (
                "\n\n[SYSTEM: Tool execution complete. Directly answer the Operator's latest message in plain text "
                "using the telemetry above. Do NOT emit any <rykr_read>, <rykr_write>, or <rykr_cmd> tags.]"
            )
        else:
            telemetry_block += (
                "\n\n[SYSTEM: If you have all facts needed to answer the Operator's latest message, reply directly "
                "in plain text. Only emit another tool tag if essential information is still missing.]"
            )
        messages.append({"role": "assistant", "content": assistant_text})
        messages.append({"role": "user", "content": telemetry_block})

        if any(r.get("status") in ("CIRCUIT_BREAKER_TRIPPED", "HERMETIC_READONLY_LOCK", "SYNTAX_FIREWALL_BLOCKED", "OPERATOR_DEFERRED_MICROSTEP") for r in tool_results):
            break

        if mutation_steps_executed >= max_mutations:
            max_total_steps = tool_steps_executed

    if step_logs:
        cleaned_summary = re.sub(r"<rykr_(?:write|cmd|read)[\s\S]*?(?:</rykr_(?:write|cmd|read)>|/>)", "", final_response)
        cleaned_summary = re.sub(r"\[?<?TOOL_TELEMETRY>?\]?[\s\S]*?\[?</?TOOL_TELEMETRY>?\]?", "", cleaned_summary).strip()
        if cleaned_summary:
            final_response = cleaned_summary

    # 5. Persist completed turn to fault-tolerant JSONL ledger
    ledger.append_turn("user", user_input, genesis_state=next_state, engine=active_engine)
    ledger.append_turn("assistant", final_response, genesis_state=next_state, engine=active_engine)

    return {
        "type": "LLM_TURN",
        "engine": active_engine,
        "genesis_state": next_state,
        "snapshot_id": snapshot_meta["snapshot_id"] if snapshot_meta else None,
        "token_telemetry": bus["token_telemetry"],
        "tool_steps_executed": tool_steps_executed,
        "tool_logs": step_logs,
        "response": final_response,
    }
