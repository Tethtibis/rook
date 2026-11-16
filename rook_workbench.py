#!/usr/bin/env python3
"""
==============================================================================
ROOK MODULE 6: DETERMINISTIC EVIDENCE WORKBENCH, MATH/OCR & PRIME AUDIT BRIDGE
==============================================================================
Enforces the core Rykr/Rook law:
  "An LLM is a reasoning router, NEVER a calculator or parser."

Responsibilities:
  1. Evidence Tray (`/var/tmp/rook/inbox/`):
     Stages uploaded files (CSV, logs, configs, screenshots) and produces a
     compact, deterministic manifest (path, SHA256, schema/headers, line count)
     so the LLM routes deterministic tools against the file instead of guessing.
  2. Deterministic Math & CSV Engine (`calc` / `audit_csv`):
     Uses Python `decimal.Decimal` (exact base-10 financial math) and in-memory
     `sqlite3` to compute provable sums, averages, anomalies, and SQL queries.
  3. Offline Screenshot & Document OCR (`ocr_file`):
     Uses `tesseract` (and `pdftotext` fallback) to extract line-numbered text
     from screenshots, error dialogs, and scanned paperwork.
  4. Push-Button Forger & Rykr-Prime Co-Worker Audit Exporter:
     - Executes registered push-buttons (`rockwell`, `lazarus`, custom buttons).
     - Allows Rook or Operator to forge new deterministic scripts in `~/rook/buttons/`.
     - Exports dense Session Audit Packets to `prime_inbox/` so Rykr-Prime can
       review sessions and crystallize new buttons in seconds.
==============================================================================
"""

import argparse
import ast
import csv
import decimal
from decimal import Decimal, InvalidOperation
import hashlib
import json
import operator
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

INBOX_DIR = Path("/var/tmp/rook/inbox")
BUTTONS_DIR = Path(os.path.expanduser("~/rook/buttons"))
PRIME_INBOX_DIR = Path(os.path.expanduser("~/rook/prime_inbox"))
SERVER_PRIME_INBOX = Path(os.path.expanduser(os.environ.get("ROOK_PRIME_INBOX", "~/rook/prime_inbox")))
SCRIPT_DIR = Path(os.path.dirname(os.path.realpath(__file__)))


def _resolve_operator_profile_path() -> Path:
    env_path = os.environ.get("ROOK_OPERATOR_PROFILE", "").strip()
    if env_path:
        return Path(os.path.expanduser(env_path))
    for cand in (SCRIPT_DIR / "ROOK_OPERATOR.md", Path("/opt/rook/ROOK_OPERATOR.md")):
        if cand.is_file():
            return cand
    return SCRIPT_DIR / "ROOK_OPERATOR.md"


def remember_operator_fact(fact: str) -> Dict[str, Any]:
    """Appends a permanent learned fact into ROOK_OPERATOR.md (T3 memory)."""
    clean_fact = " ".join((fact or "").strip().split())
    if not clean_fact:
        return {"status": "ERROR", "error": "Fact string cannot be empty."}

    profile_path = _resolve_operator_profile_path()
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    if profile_path.is_file():
        with open(profile_path, "r", encoding="utf-8", errors="replace") as f:
            existing = f.read()
    else:
        existing = "# ROOK OPERATOR PROFILE\n\n## 3. LEARNED OPERATOR FACTS\n"

    section_header = "## 3. LEARNED OPERATOR FACTS"
    if section_header not in existing:
        existing = existing.rstrip() + f"\n\n{section_header}\n"

    lines = existing.splitlines()
    norm_new = clean_fact.lower()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("* "):
            body = stripped[2:].strip()
            if body.startswith("[") and "] " in body:
                body = body.split("] ", 1)[1].strip()
            if body.lower() == norm_new:
                return {
                    "status": "PROVEN",
                    "action": "OPERATOR_FACT_ALREADY_PRESENT",
                    "file": str(profile_path),
                    "entry": stripped,
                }

    entry = f"* [{time.strftime('%Y-%m-%d')}] {clean_fact}"
    hdr_idx = next(i for i, ln in enumerate(lines) if ln.strip() == section_header)
    insert_idx = hdr_idx + 1
    while insert_idx < len(lines) and not lines[insert_idx].strip().startswith("## "):
        insert_idx += 1
    while insert_idx > hdr_idx + 1 and not lines[insert_idx - 1].strip():
        insert_idx -= 1
    lines.insert(insert_idx, entry)

    new_text = "\n".join(lines).rstrip() + "\n"
    with open(profile_path, "w", encoding="utf-8") as f:
        f.write(new_text)
        f.flush()
        os.fsync(f.fileno())

    return {
        "status": "PROVEN",
        "action": "OPERATOR_FACT_SAVED",
        "file": str(profile_path),
        "entry": entry,
    }


def ensure_dirs() -> None:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    BUTTONS_DIR.mkdir(parents=True, exist_ok=True)
    PRIME_INBOX_DIR.mkdir(parents=True, exist_ok=True)
    try:
        SERVER_PRIME_INBOX.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def file_sha256_short(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()[:12]


# ==============================================================================
# 1. DETERMINISTIC BASE-10 ARITHMETIC EVALUATOR (ZERO FLOATING-POINT DRIFT)
# ==============================================================================
_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_decimal_node(node: ast.AST) -> Decimal:
    if isinstance(node, ast.Expression):
        return _eval_decimal_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str)):
        return Decimal(str(node.value))
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
        left = _eval_decimal_node(node.left)
        right = _eval_decimal_node(node.right)
        return _SAFE_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_eval_decimal_node(node.operand))
    raise ValueError(f"Unsupported arithmetic syntax: {ast.dump(node)}")


def deterministic_calc(expression: str) -> Dict[str, Any]:
    """
    Evaluates a mathematical expression using 28-digit IEEE 754-2008 base-10
    `decimal.Decimal` arithmetic. Never uses float approximation or LLM guessing.
    """
    decimal.getcontext().prec = 28
    cleaned = expression.strip().replace("$", "").replace(",", "")
    try:
        tree = ast.parse(cleaned, mode="eval")
        result = _eval_decimal_node(tree)
        quantized_2dp = result.quantize(Decimal("0.01"), rounding=decimal.ROUND_HALF_UP)
        return {
            "status": "PROVEN",
            "engine": "Python stdlib decimal.Decimal (Base-10 Exact)",
            "expression": expression,
            "normalized": cleaned,
            "exact_result": str(result.normalize() if result != 0 else Decimal("0")),
            "currency_2dp": str(quantized_2dp),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    except Exception as exc:
        return {
            "status": "ERROR",
            "expression": expression,
            "error": str(exc),
        }


# ==============================================================================
# 2. DETERMINISTIC CSV / LEDGER AUDITOR (DECIMAL + IN-MEMORY SQLITE3)
# ==============================================================================
def _clean_numeric(val: str) -> Optional[Decimal]:
    s = val.strip().replace("$", "").replace(",", "")
    if not s:
        return None
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def deterministic_csv_audit(csv_path: str, sql_query: Optional[str] = None) -> Dict[str, Any]:
    """
    Loads a CSV file, computes exact base-10 `Decimal` sums/min/max/averages for
    every numeric column, checks for blank/duplicate rows, and optionally runs
    a deterministic SQLite query against table `csv_data`.
    """
    p = Path(os.path.expanduser(csv_path)).resolve()
    if not p.is_file():
        return {"status": "ERROR", "error": f"CSV not found: {p}"}

    with open(p, "r", encoding="utf-8", errors="replace", newline="") as f:
        reader = list(csv.reader(f))

    if not reader:
        return {"status": "ERROR", "error": "CSV file is empty"}

    raw_headers = reader[0]
    headers = [
        h.strip() or f"col_{i}"
        for i, h in enumerate(raw_headers)
    ]
    rows = reader[1:]

    col_decimals: Dict[str, List[Decimal]] = {h: [] for h in headers}
    blank_rows = 0
    seen_rows = set()
    duplicate_rows = 0

    for r in rows:
        if not any(cell.strip() for cell in r):
            blank_rows += 1
            continue
        row_tuple = tuple(c.strip() for c in r)
        if row_tuple in seen_rows:
            duplicate_rows += 1
        else:
            seen_rows.add(row_tuple)

        for idx, h in enumerate(headers):
            if idx < len(r):
                d = _clean_numeric(r[idx])
                if d is not None:
                    col_decimals[h].append(d)

    numeric_summaries: Dict[str, Any] = {}
    for h, vals in col_decimals.items():
        if vals and len(vals) >= max(1, len(rows) // 4):
            total = sum(vals, Decimal("0"))
            avg = (total / Decimal(len(vals))).quantize(Decimal("0.01"), rounding=decimal.ROUND_HALF_UP)
            numeric_summaries[h] = {
                "count": len(vals),
                "exact_sum": str(total.quantize(Decimal("0.01"), rounding=decimal.ROUND_HALF_UP)),
                "min": str(min(vals)),
                "max": str(max(vals)),
                "mean_2dp": str(avg),
            }

    sql_result: Optional[List[Dict[str, Any]]] = None
    if sql_query:
        conn = sqlite3.connect(":memory:")
        cur = conn.cursor()
        safe_cols = [
            "".join(ch if ch.isalnum() else "_" for ch in h).strip("_") or f"col_{i}"
            for i, h in enumerate(headers)
        ]
        col_defs = ", ".join(f'"{c}" TEXT' for c in safe_cols)
        cur.execute(f"CREATE TABLE csv_data ({col_defs})")
        placeholders = ", ".join("?" for _ in safe_cols)
        for r in rows:
            padded = [(r[i].strip() if i < len(r) else "") for i in range(len(safe_cols))]
            cur.execute(f"INSERT INTO csv_data VALUES ({placeholders})", padded)
        conn.commit()
        try:
            cur.execute(sql_query)
            col_names = [desc[0] for desc in cur.description] if cur.description else []
            sql_result = [dict(zip(col_names, row)) for row in cur.fetchall()[:100]]
        except Exception as exc:
            sql_result = [{"sql_error": str(exc)}]
        finally:
            conn.close()

    return {
        "status": "PROVEN",
        "engine": "Rook Deterministic CSV/Decimal Auditor",
        "file": str(p),
        "sha256_short": file_sha256_short(p),
        "total_data_rows": len(rows),
        "blank_rows": blank_rows,
        "exact_duplicate_rows": duplicate_rows,
        "columns": headers,
        "numeric_column_totals": numeric_summaries,
        "sample_first_3_rows": rows[:3],
        "sql_query_result": sql_result,
    }


# ==============================================================================
# 3. OFFLINE SCREENSHOT & IMAGE OCR EXTRACTOR
# ==============================================================================
def deterministic_ocr(image_path: str) -> Dict[str, Any]:
    """
    Runs offline `tesseract` OCR on an image/screenshot and saves a
    line-numbered transcript next to the file in `/var/tmp/rook/inbox/`.
    """
    p = Path(os.path.expanduser(image_path)).resolve()
    if not p.is_file():
        return {"status": "ERROR", "error": f"Image file not found: {p}"}

    if not shutil.which("tesseract"):
        return {
            "status": "ERROR",
            "error": "tesseract binary not installed. Run: sudo apt-get install -y tesseract-ocr",
        }

    try:
        out = subprocess.check_output(
            ["tesseract", str(p), "stdout", "--oem", "1", "-l", "eng"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=25,
        )
        lines = [ln.rstrip() for ln in out.splitlines() if ln.strip()]
        numbered = "\n".join(f"{i+1:03d}: {ln}" for i, ln in enumerate(lines))
        transcript_path = p.with_suffix(p.suffix + ".ocr.txt")
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(numbered + "\n")
        return {
            "status": "PROVEN",
            "engine": "Tesseract Offline OCR",
            "source_file": str(p),
            "sha256_short": file_sha256_short(p),
            "transcript_file": str(transcript_path),
            "line_count": len(lines),
            "extracted_text": numbered,
        }
    except Exception as exc:
        return {"status": "ERROR", "source_file": str(p), "error": str(exc)}


# ==============================================================================
# 4. EVIDENCE TRAY STAGER (CALLED ON FILE UPLOAD)
# ==============================================================================
def stage_evidence_file(filename: str, raw_bytes: bytes) -> Dict[str, Any]:
    """
    Saves an uploaded file into `/var/tmp/rook/inbox/` and returns a compact
    deterministic manifest (and automatically runs deterministic CSV audit or
    OCR if applicable) so the LLM receives proven facts instead of raw bloat.
    """
    ensure_dirs()
    safe_name = "".join(c if (c.isalnum() or c in "._-") else "_" for c in os.path.basename(filename))
    if not safe_name:
        safe_name = f"upload_{int(time.time())}.bin"
    dest = INBOX_DIR / safe_name
    with open(dest, "wb") as f:
        f.write(raw_bytes)

    ext = dest.suffix.lower()
    manifest: Dict[str, Any] = {
        "name": safe_name,
        "path": str(dest),
        "size_bytes": len(raw_bytes),
        "sha256_short": file_sha256_short(dest),
        "staged_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "type": ext.lstrip(".") or "unknown",
    }

    if ext == ".csv":
        manifest["deterministic_audit"] = deterministic_csv_audit(str(dest))
    elif ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff"):
        manifest["deterministic_ocr"] = deterministic_ocr(str(dest))
    elif ext in (".txt", ".log", ".conf", ".ini", ".md", ".json", ".py", ".sh", ".yaml", ".yml"):
        text = raw_bytes.decode("utf-8", errors="replace")
        lines = text.splitlines()
        manifest["line_count"] = len(lines)
        manifest["preview_lines"] = "\n".join(f"{i+1:04d}: {ln}" for i, ln in enumerate(lines[:50]))

    return manifest


def list_evidence_tray() -> List[Dict[str, Any]]:
    ensure_dirs()
    items = []
    for p in sorted(INBOX_DIR.iterdir()):
        if p.is_file() and not p.name.endswith(".ocr.txt"):
            items.append({
                "name": p.name,
                "path": str(p),
                "size_bytes": p.stat().st_size,
                "sha256_short": file_sha256_short(p),
                "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime)),
            })
    return items


# ==============================================================================
# 5. PUSH-BUTTON CONTROL PANEL, BUTTON FORGER & PRIME AUDIT BRIDGE
# ==============================================================================
BUILTIN_BUTTONS = [
    {
        "id": "calc",
        "label": "Exact Base-10 Math (Decimal)",
        "description": "Evaluates financial/engineering arithmetic with 0 floating-point or LLM prediction error.",
        "builtin": True,
    },
    {
        "id": "audit_csv",
        "label": "Audit CSV / Ledger Totals",
        "description": "Computes exact column sums, min/max/averages, and duplicate rows on any staged CSV.",
        "builtin": True,
    },
    {
        "id": "ocr_screenshot",
        "label": "OCR Screenshot / Document",
        "description": "Extracts line-numbered text from a staged PNG/JPG screenshot via offline Tesseract.",
        "builtin": True,
    },
    {
        "id": "gpu_vram_audit",
        "label": "GPU & VRAM Telemetry",
        "description": "Queries live NVIDIA GPU clocks, temperatures, and exact VRAM allocation.",
        "builtin": True,
    },
    {
        "id": "outpost_status",
        "label": "Remote Outpost Ping Check",
        "description": "Checks WireGuard/LAN outpost reachability (configurable via ROOK_OUTPOST_IP).",
        "builtin": True,
    },
    {
        "id": "remember_fact",
        "label": "Remember Operator Fact",
        "description": "Saves a permanent fact or preference into Rook's Operator Profile (T3 memory).",
        "builtin": True,
    },
]


def list_push_buttons() -> List[Dict[str, Any]]:
    ensure_dirs()
    buttons = list(BUILTIN_BUTTONS)
    for p in sorted(BUTTONS_DIR.glob("*.json")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                meta = json.load(f)
            meta["builtin"] = False
            buttons.append(meta)
        except Exception:
            pass
    return buttons


def forge_custom_button(button_id: str, label: str, description: str, script_body: str, interpreter: str = "/usr/bin/env python3") -> Dict[str, Any]:
    """
    Allows Rook or the Operator to forge a new deterministic push-button script
    in `~/rook/buttons/` and register it immediately in the UI control panel.
    """
    ensure_dirs()
    safe_id = "".join(c if (c.isalnum() or c == "_") else "_" for c in button_id.lower()).strip("_")
    if not safe_id:
        raise ValueError("Invalid button_id")

    script_path = BUTTONS_DIR / f"{safe_id}.sh"
    if not script_body.startswith("#!"):
        script_body = f"#!{interpreter}\n" + script_body
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script_body)
    os.chmod(script_path, 0o755)

    meta = {
        "id": safe_id,
        "label": label,
        "description": description,
        "script_path": str(script_path),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(BUTTONS_DIR / f"{safe_id}.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return {"status": "FORGED", "button": meta}


def execute_push_button(button_id: str, arg: str = "") -> Dict[str, Any]:
    """Deterministically executes a builtin or custom forged push-button."""
    ensure_dirs()
    if button_id == "calc":
        return deterministic_calc(arg or "0")
    if button_id == "audit_csv":
        target = arg.strip()
        if not target:
            csvs = sorted(INBOX_DIR.glob("*.csv"))
            if not csvs:
                return {"status": "ERROR", "error": "No CSV file specified or staged in Evidence Tray."}
            target = str(csvs[-1])
        return deterministic_csv_audit(target)
    if button_id == "ocr_screenshot":
        target = arg.strip()
        if not target:
            imgs = [p for p in sorted(INBOX_DIR.iterdir()) if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
            if not imgs:
                return {"status": "ERROR", "error": "No screenshot/image found in Evidence Tray."}
            target = str(imgs[-1])
        return deterministic_ocr(target)
    if button_id == "gpu_vram_audit":
        try:
            from rook_gguf_loader import probe_gpus
            gpus = probe_gpus()
            if gpus:
                return {"status": "PROVEN", "engine": "Hardware GPU/APU Probe", "gpus": gpus}
        except Exception:
            pass
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=index,name,temperature.gpu,utilization.gpu,memory.used,memory.total", "--format=csv"],
                text=True,
                timeout=5,
            )
            return {"status": "PROVEN", "engine": "nvidia-smi", "output": out.strip()}
        except Exception as exc:
            return {"status": "ERROR", "error": str(exc)}
    if button_id in ("outpost_status", "rockwell_status"):
        target_ip = arg.strip() or os.environ.get("ROOK_OUTPOST_IP", "10.5.5.8")
        try:
            out = subprocess.check_output(
                ["ping", "-c", "2", "-W", "2", target_ip],
                text=True,
                stderr=subprocess.STDOUT,
                timeout=6,
            )
            return {"status": "PROVEN", "engine": f"ICMP Probe ({target_ip})", "output": out.strip()}
        except subprocess.CalledProcessError as exc:
            return {"status": "OFFLINE", "engine": f"ICMP Probe ({target_ip})", "output": (exc.output or "").strip()}
        except Exception as exc:
            return {"status": "ERROR", "error": str(exc)}

    if button_id == "remember_fact":
        return remember_operator_fact(arg)

    # Check custom forged buttons
    meta_file = BUTTONS_DIR / f"{button_id}.json"
    if meta_file.is_file():
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
        script_path = meta["script_path"]
        try:
            out = subprocess.check_output(
                [script_path, arg] if arg else [script_path],
                text=True,
                stderr=subprocess.STDOUT,
                timeout=30,
            )
            return {
                "status": "PROVEN",
                "engine": f"Custom Button ({meta['label']})",
                "script": script_path,
                "output": out.strip(),
            }
        except Exception as exc:
            return {"status": "ERROR", "button": button_id, "error": str(exc)}

    return {"status": "ERROR", "error": f"Unknown button_id: {button_id}"}


def export_prime_audit(
    session_turns: List[Dict[str, Any]],
    operator_note: str = "",
    active_model: str = "",
    compartment: str = "Home",
) -> Dict[str, Any]:
    """
    Writes a compact, token-efficient Session Audit Packet to `prime_inbox/`
    so the Operator can simply tell Rykr-Prime: "check rook" and Rykr-Prime
    can immediately review Rook's work, audit flaws, or crystallize new tools.
    """
    ensure_dirs()
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    custom_buttons = [b for b in list_push_buttons() if not b.get("builtin")]
    evidence = list_evidence_tray()

    lines = [
        f"# ROOK -> RYKR-PRIME SESSION AUDIT PACKET ({ts})",
        f"* **Active Local Engine:** `{active_model or 'unloaded'}`",
        f"* **Compartment:** `{compartment}`",
        f"* **Operator Note / Request for Prime:** {operator_note or '(General session review & button harvesting)'}",
        "",
        "## 0. Learned Operator Facts",
    ]
    prof_path = _resolve_operator_profile_path()
    learned_facts: List[str] = []
    if prof_path.is_file():
        with open(prof_path, "r", encoding="utf-8", errors="replace") as pf:
            in_sec = False
            for raw_ln in pf:
                st_ln = raw_ln.strip()
                if st_ln == "## 3. LEARNED OPERATOR FACTS":
                    in_sec = True
                    continue
                if in_sec and st_ln.startswith("## "):
                    break
                if in_sec and st_ln.startswith("* "):
                    learned_facts.append(st_ln)
    if learned_facts:
        lines.extend(learned_facts)
    else:
        lines.append("* *(None)*")

    lines.extend([
        "",
        "## 1. Staged Evidence Files",
    ])
    if evidence:
        for ev in evidence:
            lines.append(f"* `{ev['path']}` ({ev['size_bytes']} bytes, sha256:`{ev['sha256_short']}`)")
    else:
        lines.append("* *(None)*")

    lines.append("")
    lines.append("## 2. Forged Local Push-Buttons (Candidates for Phase 4 ~crystallize)")
    if custom_buttons:
        for cb in custom_buttons:
            lines.append(f"* **`{cb['id']}` ({cb['label']}):** {cb['description']} -> `{cb['script_path']}`")
    else:
        lines.append("* *(No new custom buttons forged yet)*")

    lines.append("")
    lines.append("## 3. Compact Conversation & Tool Telemetry (Last 12 Turns)")
    for t in session_turns[-12:]:
        role = t.get("role", "unknown").upper()
        content = (t.get("content", "") or "").strip()
        if len(content) > 600:
            content = content[:600] + " ...[truncated]"
        lines.append(f"### [{role}]")
        lines.append(content)
        lines.append("")

    report_md = "\n".join(lines) + "\n"
    local_latest = PRIME_INBOX_DIR / "latest_audit.md"
    local_archive = PRIME_INBOX_DIR / f"audit_{ts}.md"
    with open(local_latest, "w", encoding="utf-8") as f:
        f.write(report_md)
    with open(local_archive, "w", encoding="utf-8") as f:
        f.write(report_md)

    synced_paths = [str(local_latest)]
    if SERVER_PRIME_INBOX.is_dir():
        try:
            srv_latest = SERVER_PRIME_INBOX / "latest_audit.md"
            with open(srv_latest, "w", encoding="utf-8") as f:
                f.write(report_md)
            synced_paths.append(str(srv_latest))
        except OSError:
            pass

    return {
        "status": "EXPORTED",
        "timestamp": ts,
        "paths": synced_paths,
        "instruction_for_operator": "Open Rykr-Prime and type: check rook",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Rook Module 6: Deterministic Workbench")
    parser.add_argument("--calc", type=str, help="Run exact base-10 Decimal calculation")
    parser.add_argument("--audit-csv", type=str, help="Run deterministic CSV column & SQLite audit")
    parser.add_argument("--sql", type=str, default=None, help="Optional SQL query against csv_data")
    parser.add_argument("--ocr", type=str, help="Run offline Tesseract OCR on an image")
    parser.add_argument("--remember", type=str, help="Persist a durable Operator fact into ROOK_OPERATOR.md")
    parser.add_argument("--list-buttons", action="store_true", help="List available deterministic push-buttons")
    parser.add_argument("--run-button", type=str, help="Execute a push-button by ID")
    parser.add_argument("--arg", type=str, default="", help="Argument for --run-button")
    args = parser.parse_args()

    if args.calc:
        print(json.dumps(deterministic_calc(args.calc), indent=2))
        return 0
    if args.audit_csv:
        print(json.dumps(deterministic_csv_audit(args.audit_csv, args.sql), indent=2))
        return 0
    if args.ocr:
        print(json.dumps(deterministic_ocr(args.ocr), indent=2))
        return 0
    if args.remember:
        print(json.dumps(remember_operator_fact(args.remember), indent=2))
        return 0
    if args.list_buttons:
        print(json.dumps(list_push_buttons(), indent=2))
        return 0
    if args.run_button:
        print(json.dumps(execute_push_button(args.run_button, args.arg), indent=2))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
