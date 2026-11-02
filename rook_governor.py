#!/usr/bin/env python3
"""
==============================================================================
RYKR-GOVERNOR (MODULE 2): PACKET INGRESS & NON-HANDCUFFED GENESIS TRACKER
==============================================================================
Part of the Sovereign Rykr Harness (Zero-Pip Python 3 Standard Library).
Responsibilities:
  1. Structured Packet Ingress (`intent:` -> `scope:` -> `context:`):
     - Parses explicit Operator packet headers (including multi-intent prompts).
     - Triggers the Reverse-Header Echo Fallback (`[PARSED INTENT | SCOPE]`)
       whenever the Operator inputs an untagged bottom-up info dump.
  2. Non-Handcuffed Genesis State Machine (`IDLE`, `PLAN`, `REDTEAM`, `EXECUTE`,
     `CRYSTALLIZE`):
     - Guides the active cognitive posture without crippling self-modification.
     - Automatically flags `take_pre_turn_snapshot: True` so Module 1 (`rykr_snap`)
       guarantees 1-step atomic rollback (`~rollback`) on every turn.
==============================================================================
"""

import argparse
import json
import re
import sys
from typing import Dict, Any, Optional

GENESIS_DIRECTIVES = {
    "IDLE": (
        "[GENESIS POSTURE: STANDARD EXECUTION]\n"
        "Apply the 5 Laws of Rykr. Absorb administrative friction and present a binary checkpoint when needed."
    ),
    "PLAN": (
        "[GENESIS POSTURE: PHASE 1 (~plan) — SKELETON & MAP]\n"
        "Output a high-level logical skeleton mapping the data flow and defining exact inputs/outputs for each module.\n"
        "Treat Operator 'what-if' material/substrate inquiries as Phase 1 Tire-Kicking Calibration."
    ),
    "REDTEAM": (
        "[GENESIS POSTURE: PHASE 2 (~redteam) — ADVERSARIAL AUDIT]\n"
        "Adopt a rigorous Devil's Advocate stance against the Phase 1 blueprint. Hunt for logic flaws, "
        "security vulnerabilities, edge-case failures, and architectural entropy."
    ),
    "EXECUTE": (
        "[GENESIS POSTURE: PHASE 3 (~execute) — MODULAR UNIX PIPE EXECUTION]\n"
        "Construct and validate modules with strict input/output boundaries. You possess full evolutionary "
        "self-modification autonomy (backed by automatic pre-turn atomic snapshots)."
    ),
    "CRYSTALLIZE": (
        "[GENESIS POSTURE: PHASE 4 (~crystallize) — TRIAD PRUNING FILTER]\n"
        "Audit completed modules against Gate 1 (Generality), Gate 2 (100% Zero-Pip Stdlib Purity), "
        "and Gate 3 (Context ROI Ratio). Output a PROMOTED vs. PRUNED receipt."
    ),
}

MACRO_PATTERNS = [
    (r"(?:^|\s)~/plan\b|(?:^|\s)~plan\b", "PLAN"),
    (r"(?:^|\s)~/redteam\b|(?:^|\s)~redteam\b", "REDTEAM"),
    (r"(?:^|\s)~/execute\b|(?:^|\s)~execute\b", "EXECUTE"),
    (r"(?:^|\s)~/crystallize\b|(?:^|\s)~crystallize\b|(?:^|\s)~harvest\b", "CRYSTALLIZE"),
]


def parse_harness_action(raw_text: str) -> Optional[Dict[str, Any]]:
    """Checks if the Operator invoked a direct harness control macro (~rollback, ~engine, ~status, ~close)."""
    stripped = raw_text.strip()
    if re.match(r"^~(rollback|undo)\b", stripped, re.IGNORECASE):
        parts = stripped.split()
        snap_id = parts[1] if len(parts) > 1 else None
        return {"harness_action": "ROLLBACK", "snapshot_id": snap_id}

    m_eng = re.match(r"^~engine\s+([a-zA-Z0-9_\-\.:/]+)", stripped, re.IGNORECASE)
    if m_eng:
        return {"harness_action": "SWITCH_ENGINE", "target_engine": m_eng.group(1)}

    if re.match(r"^~status\b", stripped, re.IGNORECASE):
        return {"harness_action": "STATUS"}

    if re.match(r"^~close\b", stripped, re.IGNORECASE):
        return {"harness_action": "CLOSE"}

    return None


def parse_packet_headers(raw_text: str) -> Dict[str, Any]:
    """
    Detects whether the Operator supplied explicit `intent:`, `scope:`, `context:` tags.
    Preserves left-to-right causal conditioning order.
    """
    has_intent = bool(re.search(r"\bintent\s*:", raw_text, re.IGNORECASE))
    has_scope = bool(re.search(r"\bscope\s*:", raw_text, re.IGNORECASE))
    has_context = bool(re.search(r"\bcontext\s*:", raw_text, re.IGNORECASE))

    intents = [m.strip() for m in re.findall(r"\bintent\s*:\s*([^\n]+)", raw_text, re.IGNORECASE)]
    scopes = [m.strip() for m in re.findall(r"\bscope\s*:\s*([^\n]+)", raw_text, re.IGNORECASE)]

    return {
        "structured_ingress_detected": has_intent,
        "has_intent": has_intent,
        "has_scope": has_scope,
        "has_context": has_context,
        "extracted_intents": intents,
        "extracted_scopes": scopes,
        "requires_reverse_header_echo": not has_intent,
    }


def evaluate_turn(raw_text: str, current_state: str = "IDLE") -> Dict[str, Any]:
    """
    Transforms raw Operator input into a structured TurnDirective for Module 3 (`rykr_context`).
    """
    direct_action = parse_harness_action(raw_text)
    if direct_action:
        return {
            "type": "HARNESS_COMMAND",
            "genesis_state": current_state,
            "take_pre_turn_snapshot": False,
            **direct_action,
        }

    next_state = current_state
    for pattern, target_state in MACRO_PATTERNS:
        if re.search(pattern, raw_text, re.IGNORECASE):
            next_state = target_state
            break

    packet_info = parse_packet_headers(raw_text)
    posture_header = GENESIS_DIRECTIVES.get(next_state, GENESIS_DIRECTIVES["IDLE"])

    if packet_info["requires_reverse_header_echo"]:
        echo_instruction = (
            "[INGRESS PROTOCOL: UNTAGGED BOTTOM-UP INPUT DETECTED]\n"
            "You MUST prepend Line 1 of your response with:\n"
            "`[PARSED INTENT: <1-sentence target objective> | SCOPE: <Analysis / Audit / Execution>]`"
        )
    else:
        echo_instruction = (
            "[INGRESS PROTOCOL: STRUCTURED PACKET HEADER DETECTED]\n"
            "Condition all attention on the Operator's explicit `intent:` and `scope:` vectors."
        )

    conditioned_prompt = (
        f"{posture_header}\n"
        f"{echo_instruction}\n\n"
        f"<OPERATOR_PACKET>\n{raw_text.strip()}\n</OPERATOR_PACKET>"
    )

    return {
        "type": "LLM_TURN",
        "previous_state": current_state,
        "genesis_state": next_state,
        "take_pre_turn_snapshot": True,
        "allow_self_modification": True,
        "packet_telemetry": packet_info,
        "conditioned_prompt": conditioned_prompt,
    }


def main():
    parser = argparse.ArgumentParser(description="Rykr-Governor (Module 2): Packet Ingress & Genesis Tracker")
    parser.add_argument("--input", required=True, help="Raw Operator input string")
    parser.add_argument("--state", default="IDLE", choices=list(GENESIS_DIRECTIVES.keys()), help="Current Genesis state")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")

    args = parser.parse_args()
    directive = evaluate_turn(args.input, args.state)
    sys.stdout.write(json.dumps(directive, indent=2) + "\n")


if __name__ == "__main__":
    main()
