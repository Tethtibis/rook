#!/usr/bin/env python3
"""
==============================================================================
ROOK (RYKR FIELD UNIT): SINGLE-WINDOW GIMP-STYLE LOCAL AI APPLIANCE
==============================================================================
Unifies:
  • Module 0 (`rook_gguf_loader.py`) : Zero-Ollama GGUF Loader & GPU Manager
  • Module 1 (`rykr_snap.py`)        : Atomic Filesystem & Turn Rollback
  • Module 2 (`rykr_governor.py`)    : Ingress Parser & Genesis State Lock
  • Module 3 (`rykr_context.py`)     : T0–T3 Memory Bus & Token Capper
  • Module 4 (`rykr_engine.py`)      : Local Loopback Inference Socket
  • Module 5 (`rykr_actuator.py`)    : 3-Step XML Tool & Appliance Executor
  • Module 6 (`rook_workbench.py`)   : Deterministic Math, CSV, OCR & Prime Bridge

Desktop Lifecycle Guarantee:
  When the single app window is closed (or [QUIT & FREE VRAM] is clicked),
  Rook immediately unloads the GGUF model, returns 100% of GPU VRAM to the OS,
  and terminates all processes (zero background daemons left behind).
==============================================================================
"""

import argparse
import atexit
import base64
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from rook_gguf_loader import (
    RookEngineManager,
    probe_gpus,
    scan_models_dir,
    recommend_gpus_for_model,
    DEFAULT_MODELS_DIR,
)
from rook_workbench import (
    stage_evidence_file,
    list_evidence_tray,
    list_push_buttons,
    execute_push_button,
    forge_custom_button,
    export_prime_audit,
)
from rook_snap import HarnessLedger, render_snap_summary
from rook_governor import evaluate_turn
from rook_context import assemble_memory_bus
from rook_engine import dispatch_inference
from rook_actuator import process_llm_response, MAX_TOOL_STEPS

DEFAULT_UI_HOST = "0.0.0.0"
DEFAULT_UI_PORT = 8490
IDLE_VRAM_TIMEOUT_SEC = 900  # 15 minutes auto-unload safety net


class RookRuntimeState:
    def __init__(self, workspace_home: str, workspace_work: str, models_dir: str):
        self.workspace_home = workspace_home
        os.makedirs(self.workspace_home, exist_ok=True)
        self.workspace_work = workspace_work
        self.models_dir = os.path.expanduser(models_dir)
        self.compartment = "Home"  # "Home" or "Work"
        self.engine_mgr = RookEngineManager(port=8491)
        self.state_dir = os.path.expanduser("~/.local/share/rook/state")
        self.snap_dir = os.path.expanduser("~/.local/share/rook/snapshots")
        self.ledger = HarnessLedger(state_dir=self.state_dir, snap_dir=self.snap_dir)
        self.staged_evidence_context: List[str] = []
        self.last_interaction = time.time()
        self.lock = threading.Lock()
        self.activity_seq = 0
        self.activity_log: deque = deque(maxlen=250)
        self.activity_lock = threading.Lock()
        self.server_ref: Optional[ThreadingHTTPServer] = None

    def emit_activity(self, tag: str, msg: str) -> None:
        with self.activity_lock:
            self.activity_seq += 1
            self.activity_log.append({
                "seq": self.activity_seq,
                "ts": time.strftime("%H:%M:%S"),
                "tag": str(tag),
                "msg": str(msg),
            })

    @property
    def active_workspace(self) -> str:
        if self.compartment == "Work":
            os.makedirs(self.workspace_work, exist_ok=True)
            return self.workspace_work
        return self.workspace_home

    def shutdown_everything(self) -> None:
        try:
            self.engine_mgr.unload()
        except Exception:
            pass
        if self.server_ref is not None:
            threading.Thread(target=self.server_ref.shutdown, daemon=True).start()


RUNTIME: Optional[RookRuntimeState] = None


# ==============================================================================
# SINGLE-WINDOW BURNT-ORANGE (#CC5500) HTML5 + VECTOR SVG INTERFACE
# ==============================================================================
SINGLE_WINDOW_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ROOK // Deterministic Local Field Unit (Rykr Offspring)</title>
<style>
  :root {
    --bg: #050505;
    --panel: #0d0d0d;
    --panel-alt: #141414;
    --border: #3a1d00;
    --orange: #CC5500;
    --amber: #FF8C00;
    --text: #e8e6e3;
    --muted: #8c8275;
    --green: #00e676;
    --red: #ff3d00;
    --font: 'JetBrains Mono', 'Fira Code', 'DejaVu Sans Mono', monospace;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    font-size: 13px;
    height: 100vh;
    width: 100vw;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }
  /* TOP DOCK: ENGINE & GPU LOADER */
  .top-dock {
    background: var(--panel);
    border-bottom: 2px solid var(--orange);
    padding: 8px 12px;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    min-height: 58px;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 800;
    font-size: 16px;
    color: var(--orange);
    letter-spacing: 1px;
    padding-right: 10px;
    border-right: 1px solid var(--border);
  }
  .brand span.sub {
    font-size: 10px;
    color: var(--muted);
    display: block;
    font-weight: 400;
  }
  .loader-group {
    display: flex;
    align-items: center;
    gap: 6px;
    background: var(--panel-alt);
    border: 1px solid var(--border);
    padding: 5px 8px;
    border-radius: 4px;
  }
  select, input[type="text"], textarea {
    background: #000;
    color: var(--text);
    border: 1px solid var(--orange);
    padding: 5px 8px;
    border-radius: 3px;
    font-family: var(--font);
    font-size: 12px;
  }
  button {
    background: #1a0b00;
    color: var(--amber);
    border: 1px solid var(--orange);
    padding: 5px 10px;
    border-radius: 3px;
    font-family: var(--font);
    font-size: 12px;
    font-weight: 700;
    cursor: pointer;
    transition: all 0.12s;
  }
  button:hover {
    background: var(--orange);
    color: #000;
  }
  button.primary {
    background: var(--orange);
    color: #000;
  }
  button.primary:hover {
    background: var(--amber);
  }
  button.danger {
    border-color: var(--red);
    color: var(--red);
    background: #1a0300;
  }
  button.danger:hover {
    background: var(--red);
    color: #000;
  }
  .gpu-pills {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
  }
  .gpu-pill {
    display: flex;
    align-items: center;
    gap: 5px;
    background: #080808;
    border: 1px solid var(--border);
    padding: 4px 8px;
    border-radius: 3px;
    font-size: 11px;
  }
  .gpu-pill input { accent-color: var(--orange); cursor: pointer; }
  .vram-bar {
    width: 55px;
    height: 7px;
    background: #222;
    border-radius: 2px;
    overflow: hidden;
  }
  .vram-fill {
    height: 100%;
    background: var(--orange);
  }
  .engine-badge {
    padding: 4px 8px;
    border-radius: 3px;
    font-size: 11px;
    font-weight: 800;
    border: 1px solid var(--muted);
    color: var(--muted);
  }
  .engine-badge.online {
    border-color: var(--green);
    color: var(--green);
    background: rgba(0, 230, 118, 0.08);
  }
  /* MAIN WORKSPACE: 3-COLUMN GIMP SINGLE-WINDOW LAYOUT */
  .main-grid {
    flex: 1;
    display: grid;
    grid-template-columns: 280px 1fr 310px;
    overflow: hidden;
  }
  .dock-left, .dock-right {
    background: var(--panel);
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    padding: 10px;
    gap: 12px;
  }
  .dock-left { border-right: 1px solid var(--border); }
  .dock-right { border-left: 1px solid var(--border); }
  .section-box {
    background: var(--panel-alt);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 8px;
  }
  .section-title {
    color: var(--orange);
    font-size: 11px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 8px;
    padding-bottom: 4px;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .led-list { display: flex; flex-direction: column; gap: 5px; font-size: 11px; }
  .led-row { display: flex; align-items: center; justify-content: space-between; }
  .led-dot {
    width: 8px; height: 8px; border-radius: 50%;
    display: inline-block; margin-right: 6px;
    background: var(--green);
    box-shadow: 0 0 6px var(--green);
  }
  .led-dot.off { background: var(--muted); box-shadow: none; }
  .btn-stack { display: flex; flex-direction: column; gap: 6px; }
  .btn-stack button { text-align: left; display: flex; justify-content: space-between; align-items: center; }
  .stage-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; }
  .stage-btn.active { background: var(--orange); color: #000; }

  /* CENTER CHAT & STREAM */
  .center-pane {
    display: flex;
    flex-direction: column;
    background: var(--bg);
    overflow: hidden;
  }
  .chat-stream {
    flex: 1;
    overflow-y: auto;
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .msg-card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-left: 4px solid var(--orange);
    border-radius: 4px;
    padding: 10px 12px;
  }
  .msg-card.user {
    border-left-color: var(--amber);
    background: #100c08;
  }
  .msg-card.receipt {
    border-left-color: var(--green);
    background: #06120b;
  }
  .msg-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 11px;
    color: var(--amber);
    margin-bottom: 6px;
    padding-bottom: 4px;
    border-bottom: 1px solid #222;
  }
  .msg-body {
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.45;
    font-size: 13px;
  }
  /* LIVE TERMINAL & ACTUATOR FEED */
  .term-feed {
    background: #060606;
    border-top: 2px solid var(--orange);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
  }
  .term-bar {
    background: #100902;
    border-bottom: 1px solid var(--border);
    padding: 4px 10px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 11px;
    font-weight: 800;
    color: var(--orange);
  }
  .term-bar .term-status {
    font-size: 10px;
    color: var(--muted);
    margin-left: 8px;
  }
  .term-bar .term-status.busy {
    color: var(--green);
  }
  .term-body {
    height: 150px;
    overflow-y: auto;
    padding: 6px 10px;
    font-size: 11.5px;
    line-height: 1.38;
    background: #030303;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .term-feed.collapsed .term-body { display: none; }
  .term-line { margin-bottom: 2px; }
  .term-ts { color: #666; margin-right: 6px; }
  .term-tag { font-weight: 800; margin-right: 6px; }
  .term-tag.ENGINE { color: var(--orange); }
  .term-tag.CMD { color: #ffb300; }
  .term-tag.STDOUT { color: #a7f3d0; }
  .term-tag.WRITE, .term-tag.READ { color: #60a5fa; }
  .term-tag.CMDOK, .term-tag.DONE { color: var(--green); }
  .term-tag.CMDERR, .term-tag.TIMEOUT, .term-tag.ERROR, .term-tag.ANTI-LOOP, .term-tag.FIREWALL, .term-tag.LOCKED { color: var(--red); }
  /* INPUT COMPOSER */
  .composer {
    background: var(--panel);
    border-top: 2px solid var(--border);
    padding: 10px 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .ingress-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  .compose-main {
    display: flex;
    gap: 8px;
  }
  .compose-main textarea {
    flex: 1;
    height: 62px;
    resize: none;
  }
  /* MODAL */
  .modal-backdrop {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.82);
    z-index: 100;
    align-items: center;
    justify-content: center;
  }
  .modal-backdrop.open { display: flex; }
  .modal-box {
    background: var(--panel);
    border: 2px solid var(--orange);
    border-radius: 6px;
    width: 640px;
    max-width: 94vw;
    max-height: 85vh;
    display: flex;
    flex-direction: column;
    padding: 14px;
    gap: 10px;
  }
  .file-list {
    overflow-y: auto;
    max-height: 360px;
    border: 1px solid var(--border);
    background: #000;
    padding: 6px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .file-item {
    padding: 6px 8px;
    border: 1px solid #1a1a1a;
    cursor: pointer;
    display: flex;
    justify-content: space-between;
  }
  .file-item:hover { background: #1f0d00; border-color: var(--orange); }
</style>
<style id="rookLiveTheme"></style>
</head>
<body>

<!-- TOP HARDWARE & GGUF LOADER BAR -->
<div class="top-dock">
  <div class="brand">
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#CC5500" stroke-width="2.2">
      <path d="M5 3h3v3h3V3h2v3h3V3h3v6l-2 2v7h2v3H5v-3h2v-7L5 9V3z"/>
    </svg>
    <div>
      ROOK v1.0
      <span class="sub">DETERMINISTIC FIELD UNIT</span>
    </div>
  </div>

  <div class="loader-group">
    <label style="color:var(--amber);font-size:11px;font-weight:700;">GGUF ENGINE:</label>
    <select id="modelSelect" style="min-width:250px;"></select>
    <button onclick="openDiskBrowser()" title="Browse any folder or USB drive for a .gguf file">Browse Disk...</button>
  </div>

  <div class="loader-group">
    <label style="color:var(--amber);font-size:11px;font-weight:700;">GPUs:</label>
    <div id="gpuContainer" class="gpu-pills"></div>
  </div>

  <div class="loader-group">
    <button class="primary" id="btnLoadEngine" onclick="loadSelectedEngine()">LOAD ENGINE</button>
    <button id="btnUnloadEngine" onclick="unloadEngine()">UNLOAD VRAM</button>
    <span id="engineBadge" class="engine-badge">UNLOADED (0 MB)</span>
  </div>

  <div style="margin-left:auto;">
    <button class="danger" onclick="quitProgramAndFreeVram()" title="Closes Rook and immediately frees 100% of GPU VRAM">
      [X] QUIT &amp; FREE VRAM
    </button>
  </div>
</div>

<!-- 3-COLUMN SINGLE-WINDOW WORKSPACE -->
<div class="main-grid">

  <!-- LEFT DOCK: MODULE LEDS, COMPARTMENT, GENESIS STATE, ROLLBACK -->
  <div class="dock-left">
    <div class="section-box">
      <div class="section-title">
        <span>Assembly Line LEDs</span>
        <button style="padding:2px 6px;font-size:10px;" onclick="refreshTelemetry()">Refresh</button>
      </div>
      <div class="led-list">
        <div class="led-row"><span><i id="ledM0" class="led-dot off"></i>M0: GGUF CUDA Worker</span><span id="lblM0">IDLE</span></div>
        <div class="led-row"><span><i class="led-dot"></i>M1: Atomic Snap/Rollback</span><span>READY</span></div>
        <div class="led-row"><span><i class="led-dot"></i>M2: Ingress Governor</span><span id="lblStage">PLAN</span></div>
        <div class="led-row"><span><i class="led-dot"></i>M3: T0-T3 Memory Bus</span><span id="lblComp">Home</span></div>
        <div class="led-row"><span><i class="led-dot"></i>M5: 3-Step XML Actuator</span><span>ARMED</span></div>
        <div class="led-row"><span><i class="led-dot"></i>M6: Evidence Workbench</span><span>READY</span></div>
      </div>
    </div>

    <div class="section-box">
      <div class="section-title">Compartment Isolation</div>
      <div class="stage-grid">
        <button id="compHome" class="stage-btn active" onclick="setCompartment('Home')">HOME MODE</button>
        <button id="compWork" class="stage-btn" onclick="setCompartment('Work')">WORK MODE</button>
      </div>
    </div>

    <div class="section-box">
      <div class="section-title">Genesis Pipeline Stage</div>
      <div class="stage-grid">
        <button class="stage-btn" onclick="sendMacro('~plan')">1. ~plan</button>
        <button class="stage-btn" onclick="sendMacro('~redteam')">2. ~redteam</button>
        <button class="stage-btn" onclick="sendMacro('~execute')">3. ~execute</button>
        <button class="stage-btn" onclick="sendMacro('~crystallize')">4. ~harvest</button>
      </div>
      <div style="margin-top:8px;display:flex;gap:6px;">
        <button style="flex:1;" onclick="sendMacro('~rollback')" title="Revert filesystem & chat to pre-turn snapshot">~rollback</button>
        <button style="flex:1;" onclick="clearChatSession()" title="Start fresh conversation ledger">Clear Chat</button>
      </div>
    </div>

    <div class="section-box">
      <div class="section-title">Rykr-Prime Co-Worker Bridge</div>
      <p style="font-size:11px;color:var(--muted);margin-bottom:8px;">
        Packages recent turns, staged files, and custom buttons into <code>prime_inbox/latest_audit.md</code> so Rykr-Prime can review in 1 command.
      </p>
      <button class="primary" style="width:100%;" onclick="exportAuditForPrime()">
        Export Session Audit for Prime
      </button>
    </div>
  </div>

  <!-- CENTER PANE: CHAT STREAM + COMPOSER -->
  <div class="center-pane">
    <div id="chatStream" class="chat-stream"></div>

    <div id="termFeed" class="term-feed">
      <div class="term-bar">
        <span>LIVE TERMINAL &amp; ACTUATOR FEED <span id="termStatus" class="term-status">IDLE</span></span>
        <div style="display:flex;gap:6px;">
          <button style="padding:1px 7px;font-size:10px;" id="btnToggleTerm" onclick="toggleTermFeed()">Hide</button>
          <button style="padding:1px 7px;font-size:10px;" onclick="clearTermFeed()">Clear</button>
        </div>
      </div>
      <div id="termBody" class="term-body"></div>
    </div>

    <div class="composer">
      <div class="ingress-row">
        <input type="text" id="inpIntent" placeholder="intent: (optional target objective — or leave blank for auto-parse)">
        <input type="text" id="inpScope" placeholder="scope: (optional boundary, e.g. audit / plan / execute)">
      </div>
      <div class="compose-main">
        <textarea id="inpContext" placeholder="Type message or paste telemetry here... (Press Enter to SEND, Shift+Enter for new line)" onkeydown="if(event.key==='Enter' && !event.shiftKey){event.preventDefault(); sendChatTurn();}"></textarea>
        <div style="display:flex;flex-direction:column;gap:6px;min-width:140px;">
          <button class="primary" style="flex:1;font-size:13px;" id="btnSend" onclick="sendChatTurn()">SEND TURN</button>
          <label style="background:#1a0b00;color:var(--amber);border:1px solid var(--orange);padding:5px 8px;border-radius:3px;font-size:11px;font-weight:700;text-align:center;cursor:pointer;">
            + Attach File / Image
            <input type="file" id="fileUploadInput" style="display:none;" onchange="uploadEvidenceFile(this)">
          </label>
        </div>
      </div>
    </div>
  </div>

  <!-- RIGHT DOCK: DETERMINISTIC PUSH-BUTTONS & EVIDENCE TRAY -->
  <div class="dock-right">
    <div class="section-box">
      <div class="section-title">
        <span>Deterministic Push-Buttons</span>
        <button style="padding:2px 6px;font-size:10px;" onclick="openForgeModal()">+ Forge Button</button>
      </div>
      <div style="margin-bottom:8px;display:flex;gap:4px;">
        <input type="text" id="btnArgInput" style="flex:1;" placeholder="Math formula / CSV SQL / Arg...">
      </div>
      <div id="pushButtonStack" class="btn-stack"></div>
    </div>

    <div class="section-box" style="flex:1;display:flex;flex-direction:column;">
      <div class="section-title">
        <span>Staged Evidence Tray</span>
        <span style="font-size:10px;color:var(--muted);">/var/tmp/rook/inbox</span>
      </div>
      <div id="evidenceList" style="display:flex;flex-direction:column;gap:6px;overflow-y:auto;font-size:11px;"></div>
    </div>
  </div>

</div>

<!-- DISK BROWSER MODAL FOR GGUF FILES -->
<div id="diskModal" class="modal-backdrop">
  <div class="modal-box">
    <div class="section-title">
      <span>Browse Filesystem for .gguf Model</span>
      <button onclick="closeDiskBrowser()">Close</button>
    </div>
    <div style="display:flex;gap:6px;">
      <input type="text" id="browseDirInput" style="flex:1;" value="~/Models">
      <button class="primary" onclick="browseDirectory(document.getElementById('browseDirInput').value)">Go</button>
      <button onclick="browseParentDir()">Up (..)</button>
    </div>
    <div id="diskFileList" class="file-list"></div>
  </div>
</div>

<!-- FORGE NEW PUSH-BUTTON MODAL -->
<div id="forgeModal" class="modal-backdrop">
  <div class="modal-box">
    <div class="section-title">
      <span>Forge New Deterministic Push-Button</span>
      <button onclick="closeForgeModal()">Close</button>
    </div>
    <input type="text" id="forgeId" placeholder="Button ID (e.g. rv_lot_sum)">
    <input type="text" id="forgeLabel" placeholder="Button Display Label (e.g. RV Lot Balance Sum)">
    <input type="text" id="forgeDesc" placeholder="Short description of what this deterministic script proves">
    <textarea id="forgeScript" style="height:180px;" placeholder="#!/usr/bin/env python3&#10;import sys&#10;print('Proven deterministic output:', sys.argv[1:])"></textarea>
    <button class="primary" onclick="submitForgeButton()">Save &amp; Register Push-Button</button>
  </div>
</div>

<script>
let CURRENT_MODELS = [];
let CURRENT_GPUS = [];

function escapeHtml(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function copyText(btn, text) {
  navigator.clipboard.writeText(text);
  const orig = btn.innerText;
  btn.innerText = 'COPIED!';
  setTimeout(() => btn.innerText = orig, 1200);
}

async function refreshTelemetry() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    CURRENT_MODELS = data.available_models || [];
    CURRENT_GPUS = data.gpus || [];

    // Populate model dropdown while preserving selection
    const sel = document.getElementById('modelSelect');
    const prevVal = sel.value;
    sel.innerHTML = '';
    CURRENT_MODELS.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m.path;
      opt.innerText = `${m.name} (${m.size_gb} GB)`;
      sel.appendChild(opt);
    });
    if (data.active_worker && data.active_worker.model_path) {
      sel.value = data.active_worker.model_path;
    } else if (prevVal) {
      sel.value = prevVal;
    } else if (CURRENT_MODELS.length > 0) {
      const pref = CURRENT_MODELS.find(m => m.name.includes('rykr-sat')) || CURRENT_MODELS[0];
      sel.value = pref.path;
    }

    // Populate GPU checkboxes (preserving checked state if already rendered)
    const gpuBox = document.getElementById('gpuContainer');
    const existingChecks = {};
    gpuBox.querySelectorAll('input[type=checkbox]').forEach(cb => {
      existingChecks[cb.dataset.gpuIdx] = cb.checked;
    });
    gpuBox.innerHTML = '';
    const maxVramIdx = CURRENT_GPUS.reduce((bestIdx, g, i, arr) => g.vram_total_mb > (arr[bestIdx]?.vram_total_mb || 0) ? i : bestIdx, 0);
    CURRENT_GPUS.forEach((g, idx) => {
      const pct = Math.min(100, Math.round((g.vram_used_mb / Math.max(1, g.vram_total_mb)) * 100));
      const checked = (g.index in existingChecks) ? existingChecks[g.index] : (idx === maxVramIdx);
      const pill = document.createElement('label');
      pill.className = 'gpu-pill';
      pill.innerHTML = `
        <input type="checkbox" data-gpu-idx="${g.index}" ${checked ? 'checked' : ''}>
        <span>GPU ${g.index}: ${escapeHtml(g.name.replace('NVIDIA GeForce ',''))}</span>
        <div class="vram-bar"><div class="vram-fill" style="width:${pct}%"></div></div>
        <span style="color:var(--amber)">${g.vram_used_mb}/${g.vram_total_mb}MB (${g.temp_c}°C)</span>
      `;
      gpuBox.appendChild(pill);
    });

    // Engine badge & LED
    const badge = document.getElementById('engineBadge');
    const ledM0 = document.getElementById('ledM0');
    const lblM0 = document.getElementById('lblM0');
    if (data.engine_online && data.active_worker) {
      badge.className = 'engine-badge online';
      badge.innerText = `ONLINE: ${data.active_worker.model} (GPU ${data.active_worker.gpu_indices.join(',')})`;
      ledM0.className = 'led-dot';
      lblM0.innerText = 'ONLINE';
    } else {
      badge.className = 'engine-badge';
      badge.innerText = 'UNLOADED (0 MB VRAM)';
      ledM0.className = 'led-dot off';
      lblM0.innerText = 'STANDBY';
    }

    document.getElementById('lblStage').innerText = data.genesis_state || 'PLAN';
    document.getElementById('lblComp').innerText = data.compartment || 'Home';
    document.getElementById('compHome').className = 'stage-btn' + (data.compartment === 'Home' ? ' active' : '');
    document.getElementById('compWork').className = 'stage-btn' + (data.compartment === 'Work' ? ' active' : '');

    // Render Push Buttons
    const stack = document.getElementById('pushButtonStack');
    stack.innerHTML = '';
    (data.push_buttons || []).forEach(b => {
      const btn = document.createElement('button');
      btn.title = b.description || '';
      btn.innerHTML = `<span>${escapeHtml(b.label)}</span><span style="font-size:10px;color:var(--muted);">[RUN]</span>`;
      btn.onclick = () => runPushButton(b.id, b.label);
      stack.appendChild(btn);
    });

    // Render Evidence Tray
    const evList = document.getElementById('evidenceList');
    evList.innerHTML = '';
    if ((data.evidence_tray || []).length === 0) {
      evList.innerHTML = '<div style="color:var(--muted);">No files staged yet. Use [+ Attach File / Image] to stage CSVs, logs, or screenshots.</div>';
    } else {
      data.evidence_tray.forEach(ev => {
        const d = document.createElement('div');
        d.style.cssText = 'padding:5px;border:1px solid #222;background:#070707;border-radius:3px;';
        d.innerHTML = `<div style="color:var(--amber);font-weight:700;">${escapeHtml(ev.name)}</div>
                       <div style="color:var(--muted);font-size:10px;">${ev.size_bytes} B | sha256:${ev.sha256_short}</div>`;
        evList.appendChild(d);
      });
    }

    const themeEl = document.getElementById('rookLiveTheme');
    if (themeEl && typeof data.theme_css === 'string' && themeEl.textContent !== data.theme_css) {
      themeEl.textContent = data.theme_css;
    }
  } catch (e) {
    console.error(e);
  }
}

function appendCard(role, title, bodyText, cardClass='') {
  const stream = document.getElementById('chatStream');
  const card = document.createElement('div');
  card.className = 'msg-card ' + cardClass;
  const header = document.createElement('div');
  header.className = 'msg-header';
  const left = document.createElement('span');
  left.innerHTML = `<strong>${escapeHtml(role)}</strong> // ${escapeHtml(title)}`;
  const copyBtn = document.createElement('button');
  copyBtn.style.cssText = 'padding:2px 8px;font-size:10px;';
  copyBtn.innerText = 'COPY';
  copyBtn.onclick = () => copyText(copyBtn, bodyText);
  header.appendChild(left);
  header.appendChild(copyBtn);

  const body = document.createElement('div');
  body.className = 'msg-body';
  body.textContent = bodyText;

  card.appendChild(header);
  card.appendChild(body);
  stream.appendChild(card);
  stream.scrollTop = stream.scrollHeight;
}

async function loadSelectedEngine() {
  const modelPath = document.getElementById('modelSelect').value;
  if (!modelPath) return alert('Select a .gguf file first.');
  const checkedGpus = [];
  document.querySelectorAll('#gpuContainer input[type=checkbox]:checked').forEach(cb => {
    checkedGpus.push(parseInt(cb.dataset.gpuIdx, 10));
  });
  const btn = document.getElementById('btnLoadEngine');
  btn.innerText = 'LOADING INTO VRAM...';
  btn.disabled = true;
  try {
    const res = await fetch('/api/engine/load', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({model_path: modelPath, gpu_indices: checkedGpus})
    });
    const out = await res.json();
    if (out.error) {
      appendCard('SYSTEM', 'Engine Load Error', out.error, 'user');
    } else {
      appendCard('MODULE 0', 'GGUF Engine Online', JSON.stringify(out.health, null, 2), 'receipt');
    }
  } finally {
    btn.innerText = 'LOAD ENGINE';
    btn.disabled = false;
    refreshTelemetry();
  }
}

async function unloadEngine() {
  const res = await fetch('/api/engine/unload', {method: 'POST'});
  const out = await res.json();
  appendCard('MODULE 0', 'VRAM Released (0 MB Model Footprint)', JSON.stringify(out.gpus, null, 2), 'receipt');
  refreshTelemetry();
}

let LAST_ACTIVITY_SEQ = 0;
let TERM_POLL_TIMER = null;

function toggleTermFeed() {
  const feed = document.getElementById('termFeed');
  const btn = document.getElementById('btnToggleTerm');
  const collapsed = feed.classList.toggle('collapsed');
  btn.innerText = collapsed ? 'Show' : 'Hide';
}

function clearTermFeed() {
  document.getElementById('termBody').innerHTML = '';
}

async function pollActivity() {
  try {
    const res = await fetch('/api/activity?since=' + LAST_ACTIVITY_SEQ);
    const data = await res.json();
    const events = data.events || [];
    if (events.length > 0) {
      const body = document.getElementById('termBody');
      events.forEach(ev => {
        const line = document.createElement('div');
        line.className = 'term-line';
        const tagClass = String(ev.tag || '').replace(/[^A-Za-z0-9_-]/g, '');
        line.innerHTML = `<span class="term-ts">[${escapeHtml(ev.ts)}]</span><span class="term-tag ${tagClass}">[${escapeHtml(ev.tag)}]</span><span>${escapeHtml(ev.msg)}</span>`;
        body.appendChild(line);
      });
      while (body.children.length > 300) {
        body.removeChild(body.firstChild);
      }
      body.scrollTop = body.scrollHeight;
    }
    if (typeof data.seq === 'number' && data.seq > LAST_ACTIVITY_SEQ) {
      LAST_ACTIVITY_SEQ = data.seq;
    }
  } catch (e) {}
}

async function sendChatTurn() {
  const intent = document.getElementById('inpIntent').value.trim();
  const scope = document.getElementById('inpScope').value.trim();
  const ctx = document.getElementById('inpContext').value.trim();
  if (!intent && !scope && !ctx) return;

  let packet = '';
  if (intent) packet += `intent: ${intent}\n`;
  if (scope) packet += `scope: ${scope}\n`;
  if (ctx) packet += (intent || scope) ? `context: ${ctx}` : ctx;

  appendCard('OPERATOR', 'Ingress Packet', packet, 'user');
  document.getElementById('inpContext').value = '';

  const btn = document.getElementById('btnSend');
  const tStatus = document.getElementById('termStatus');
  btn.innerText = 'WORKING...';
  btn.disabled = true;
  if (tStatus) { tStatus.innerText = 'LIVE'; tStatus.className = 'term-status busy'; }
  await pollActivity();
  if (TERM_POLL_TIMER) clearInterval(TERM_POLL_TIMER);
  TERM_POLL_TIMER = setInterval(pollActivity, 500);
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({prompt: packet})
    });
    const out = await res.json();
    if (out.error) {
      appendCard('ROOK ERROR', 'Engine Notice', out.error, 'user');
    } else if (out.type === 'HARNESS_COMMAND') {
      if (out.action === 'ROLLBACK') {
        const hRes = await fetch('/api/history');
        const hist = await hRes.json();
        document.getElementById('chatStream').innerHTML = '';
        (hist.turns || []).forEach(t => {
          const clean = String(t.content || '').replace(/\n\[tools_executed:[^\]]*\]$/, '');
          appendCard(t.role === 'user' ? 'OPERATOR' : 'ROOK', t.timestamp || '', clean, t.role === 'user' ? 'user' : 'rook');
        });
      }
      appendCard('ROOK HARNESS', out.action || 'COMMAND', JSON.stringify(out, null, 2), 'receipt');
    } else {
      if (out.tool_logs && out.tool_logs.length > 0) {
        appendCard('MODULE 5 (ACTUATOR)', `Executed ${out.tool_steps_executed} Deterministic Step(s)`, JSON.stringify(out.tool_logs, null, 2), 'receipt');
      }
      appendCard('ROOK', `State: ${out.genesis_state} | Snap: ${out.snapshot_id || 'none'}`, out.response || JSON.stringify(out, null, 2), 'rook');
    }
  } finally {
    if (TERM_POLL_TIMER) { clearInterval(TERM_POLL_TIMER); TERM_POLL_TIMER = null; }
    await pollActivity();
    if (tStatus) { tStatus.innerText = 'IDLE'; tStatus.className = 'term-status'; }
    btn.innerText = 'SEND TURN';
    btn.disabled = false;
    refreshTelemetry();
  }
}

async function sendMacro(macro) {
  document.getElementById('inpContext').value = macro;
  await sendChatTurn();
}

async function runPushButton(buttonId, label) {
  const arg = document.getElementById('btnArgInput').value.trim();
  const res = await fetch('/api/workbench/button', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({button_id: buttonId, arg: arg})
  });
  const out = await res.json();
  appendCard('DETERMINISTIC RECEIPT', label, JSON.stringify(out, null, 2), 'receipt');
  refreshTelemetry();
}

async function uploadEvidenceFile(inputEl) {
  if (!inputEl.files || inputEl.files.length === 0) return;
  const file = inputEl.files[0];
  const reader = new FileReader();
  reader.onload = async function(evt) {
    const b64 = evt.target.result.split(',')[1] || '';
    const res = await fetch('/api/workbench/upload', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({filename: file.name, data_b64: b64})
    });
    const out = await res.json();
    appendCard('MODULE 6 (EVIDENCE STAGED)', `${file.name} (Verified & Pinned for Rook)`, JSON.stringify(out, null, 2), 'receipt');
    inputEl.value = '';
    refreshTelemetry();
  };
  reader.readAsDataURL(file);
}

async function setCompartment(comp) {
  await fetch('/api/compartment', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({compartment: comp})
  });
  refreshTelemetry();
}

async function clearChatSession() {
  await fetch('/api/chat/clear', {method: 'POST'});
  document.getElementById('chatStream').innerHTML = '';
  appendCard('SYSTEM', 'Session Reset', 'Chat history cleared. Ready.', 'receipt');
  refreshTelemetry();
}

async function exportAuditForPrime() {
  const note = prompt('Optional note for Rykr-Prime (or leave blank):', '') || '';
  const res = await fetch('/api/workbench/audit', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({note: note})
  });
  const out = await res.json();
  navigator.clipboard.writeText('check rook');
  appendCard('PRIME BRIDGE', 'Session Audit Exported (Copied "check rook" to Clipboard)', JSON.stringify(out, null, 2), 'receipt');
}

function openDiskBrowser() {
  document.getElementById('diskModal').classList.add('open');
  browseDirectory(document.getElementById('browseDirInput').value);
}
function closeDiskBrowser() { document.getElementById('diskModal').classList.remove('open'); }

async function browseDirectory(dirPath) {
  const res = await fetch('/api/fs/browse?dir=' + encodeURIComponent(dirPath));
  const out = await res.json();
  document.getElementById('browseDirInput').value = out.current_dir || dirPath;
  const list = document.getElementById('diskFileList');
  list.innerHTML = '';
  (out.entries || []).forEach(e => {
    const row = document.createElement('div');
    row.className = 'file-item';
    if (e.is_dir) {
      row.innerHTML = `<span style="color:var(--amber)">[DIR] ${escapeHtml(e.name)}/</span><span>Open</span>`;
      row.onclick = () => browseDirectory(e.path);
    } else {
      row.innerHTML = `<span style="color:var(--green)">${escapeHtml(e.name)}</span><span>${e.size_gb} GB [Select]</span>`;
      row.onclick = () => {
        const sel = document.getElementById('modelSelect');
        let found = Array.from(sel.options).find(o => o.value === e.path);
        if (!found) {
          const opt = document.createElement('option');
          opt.value = e.path;
          opt.innerText = `${e.name} (${e.size_gb} GB)`;
          sel.appendChild(opt);
        }
        sel.value = e.path;
        closeDiskBrowser();
      };
    }
    list.appendChild(row);
  });
}

function browseParentDir() {
  const cur = document.getElementById('browseDirInput').value;
  const parent = cur.replace(/\/[^\/]+\/?$/, '') || '/';
  browseDirectory(parent);
}

function openForgeModal() { document.getElementById('forgeModal').classList.add('open'); }
function closeForgeModal() { document.getElementById('forgeModal').classList.remove('open'); }

async function submitForgeButton() {
  const payload = {
    button_id: document.getElementById('forgeId').value.trim(),
    label: document.getElementById('forgeLabel').value.trim(),
    description: document.getElementById('forgeDesc').value.trim(),
    script_body: document.getElementById('forgeScript').value
  };
  const res = await fetch('/api/workbench/forge', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  const out = await res.json();
  closeForgeModal();
  appendCard('BUTTON FORGER', 'New Deterministic Push-Button Registered', JSON.stringify(out, null, 2), 'receipt');
  refreshTelemetry();
}

async function quitProgramAndFreeVram() {
  await fetch('/api/quit', {method: 'POST'});
  document.body.innerHTML = '<div style="display:flex;height:100vh;align-items:center;justify-content:center;color:#CC5500;font-size:20px;font-weight:800;">ROOK TERMINATED // 100% GPU VRAM RELEASED. YOU MAY CLOSE THIS WINDOW.</div>';
  setTimeout(() => window.close(), 300);
}

window.addEventListener('DOMContentLoaded', async () => {
  await refreshTelemetry();
  const res = await fetch('/api/history');
  const hist = await res.json();
  if ((hist.turns || []).length === 0) {
    appendCard('ROOK v1.0', 'Ready on Local Node',
      '1. Pick a .gguf model and GPU(s) in the Top Bar and click [LOAD ENGINE].\n' +
      '2. Use Deterministic Push-Buttons on the Right Dock for exact base-10 math, CSV audits, or screenshot OCR.\n' +
      '3. When finished, closing the app or clicking [QUIT & FREE VRAM] returns 100% of VRAM to your system.',
      'receipt');
  } else {
    hist.turns.forEach(t => {
      const clean = String(t.content || '').replace(/\n\[tools_executed:[^\]]*\]$/, '');
      appendCard(t.role === 'user' ? 'OPERATOR' : 'ROOK', t.timestamp || '', clean, t.role === 'user' ? 'user' : 'rook');
    });
  }
  setInterval(refreshTelemetry, 5000);
  await pollActivity();
  setInterval(pollActivity, 5000);
});
</script>
</body>
</html>
"""


class RookHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        assert RUNTIME is not None
        parsed = urlparse(self.path)

        if parsed.path == "/":
            raw = SINGLE_WINDOW_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return

        if parsed.path == "/api/status":
            online = RUNTIME.engine_mgr.is_online()
            gpus = probe_gpus()
            models = scan_models_dir(RUNTIME.models_dir)
            snap = render_snap_summary(RUNTIME.ledger, tail_count=1)
            theme_css = ""
            theme_path = Path(SCRIPT_DIR) / "rook_theme.css"
            if theme_path.is_file():
                try:
                    theme_css = theme_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass
            self._send_json(200, {
                "engine_online": online is not None,
                "active_worker": online,
                "gpus": gpus,
                "available_models": models,
                "compartment": RUNTIME.compartment,
                "genesis_state": snap["active_genesis_state"],
                "push_buttons": list_push_buttons(),
                "evidence_tray": list_evidence_tray(),
                "theme_css": theme_css,
            })
            return

        if parsed.path == "/api/history":
            turns, _ = RUNTIME.ledger.load_turns()
            self._send_json(200, {"turns": turns[-30:]})
            return

        if parsed.path == "/api/activity":
            qs = parse_qs(parsed.query)
            try:
                since = int(qs.get("since", ["0"])[0])
            except ValueError:
                since = 0
            with RUNTIME.activity_lock:
                events = [e for e in RUNTIME.activity_log if e["seq"] > since]
                seq = RUNTIME.activity_seq
            self._send_json(200, {"seq": seq, "events": events})
            return

        if parsed.path == "/api/fs/browse":
            qs = parse_qs(parsed.query)
            target_dir = qs.get("dir", [RUNTIME.models_dir])[0]
            p = Path(os.path.expanduser(target_dir)).resolve()
            if not p.is_dir():
                p = Path.home()
            entries = []
            try:
                for item in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                    if item.name.startswith("."):
                        continue
                    if item.is_dir():
                        entries.append({"name": item.name, "path": str(item), "is_dir": True})
                    elif item.suffix.lower() == ".gguf":
                        sz_gb = round(item.stat().st_size / (1024 ** 3), 2)
                        entries.append({"name": item.name, "path": str(item), "is_dir": False, "size_gb": sz_gb})
            except PermissionError:
                pass
            self._send_json(200, {"current_dir": str(p), "entries": entries})
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        assert RUNTIME is not None
        RUNTIME.last_interaction = time.time()
        length = int(self.headers.get("Content-Length", "0"))
        body_raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            req = json.loads(body_raw) if body_raw else {}
        except json.JSONDecodeError:
            req = {}

        if self.path == "/api/quit":
            self._send_json(200, {"status": "terminated_and_vram_freed"})
            threading.Thread(target=RUNTIME.shutdown_everything, daemon=True).start()
            return

        if self.path == "/api/engine/load":
            model_path = req.get("model_path", "")
            gpu_indices = req.get("gpu_indices")
            try:
                res = RUNTIME.engine_mgr.load(model_path=model_path, gpu_indices=gpu_indices, bind_pdeath=True)
                self._send_json(200, res)
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return

        if self.path == "/api/engine/unload":
            res = RUNTIME.engine_mgr.unload()
            self._send_json(200, res)
            return

        if self.path == "/api/compartment":
            comp = req.get("compartment", "Home")
            RUNTIME.compartment = "Work" if comp in ("Work", "Rockwell") else "Home"
            self._send_json(200, {"compartment": RUNTIME.compartment, "workspace": RUNTIME.active_workspace})
            return

        if self.path == "/api/chat/clear":
            for p in (
                RUNTIME.ledger.ledger_path,
                RUNTIME.ledger.meta_path,
                Path(RUNTIME.state_dir) / "session_turns.jsonl",
            ):
                if p.is_file():
                    p.unlink()
            RUNTIME.staged_evidence_context.clear()
            self._send_json(200, {"status": "cleared"})
            return

        if self.path == "/api/workbench/button":
            btn_id = req.get("button_id", "")
            arg = req.get("arg", "")
            res = execute_push_button(btn_id, arg)
            RUNTIME.staged_evidence_context.append(
                f"[DETERMINISTIC PUSH-BUTTON RECEIPT ({btn_id})]:\n{json.dumps(res, indent=2)}"
            )
            self._send_json(200, res)
            return

        if self.path == "/api/workbench/upload":
            filename = req.get("filename", "upload.bin")
            data_b64 = req.get("data_b64", "")
            raw_bytes = base64.b64decode(data_b64) if data_b64 else b""
            manifest = stage_evidence_file(filename, raw_bytes)
            RUNTIME.staged_evidence_context.append(
                f"[STAGED EVIDENCE MANIFEST ({filename})]:\n{json.dumps(manifest, indent=2)}"
            )
            self._send_json(200, manifest)
            return

        if self.path == "/api/workbench/forge":
            try:
                res = forge_custom_button(
                    button_id=req.get("button_id", ""),
                    label=req.get("label", ""),
                    description=req.get("description", ""),
                    script_body=req.get("script_body", ""),
                )
                self._send_json(200, res)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
            return

        if self.path == "/api/workbench/audit":
            turns, _ = RUNTIME.ledger.load_turns()
            online = RUNTIME.engine_mgr.is_online()
            active_model = online.get("model", "unloaded") if online else "unloaded"
            res = export_prime_audit(
                session_turns=turns,
                operator_note=req.get("note", ""),
                active_model=active_model,
                compartment=RUNTIME.compartment,
            )
            self._send_json(200, res)
            return

        if self.path == "/api/chat":
            prompt = req.get("prompt", "").strip()
            if not prompt:
                self._send_json(400, {"error": "Empty prompt"})
                return

            online = RUNTIME.engine_mgr.is_online()
            if not online and not prompt.startswith("~"):
                self._send_json(400, {
                    "error": "No GGUF engine is currently loaded in VRAM. Select a .gguf model in the Top Bar and click [LOAD ENGINE] first."
                })
                return

            # Prepend any deterministic evidence or button receipts collected since last turn
            if RUNTIME.staged_evidence_context:
                evidence_block = "\n\n".join(RUNTIME.staged_evidence_context[-3:])
                prompt_with_evidence = (
                    f"{prompt}\n\n"
                    f"--- DETERMINISTIC WORKBENCH RECEIPTS (PROVEN FACTS — DO NOT GUESS MATH) ---\n"
                    f"{evidence_block}"
                )
                RUNTIME.staged_evidence_context.clear()
            else:
                prompt_with_evidence = prompt

            try:
                import importlib
                import rook_harness, rook_context, rook_actuator, rook_workbench, rook_governor, rook_engine
                for mod in (rook_governor, rook_context, rook_actuator, rook_workbench, rook_engine, rook_harness):
                    importlib.reload(mod)
                out = rook_harness.run_turn_pipeline(
                    user_input=prompt_with_evidence,
                    workspace_dir=RUNTIME.active_workspace,
                    ledger=RUNTIME.ledger,
                    engine_override="rook",
                    max_steps=MAX_TOOL_STEPS,
                    event_cb=RUNTIME.emit_activity,
                )
                RUNTIME.last_interaction = time.time()
                self._send_json(200, out)
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return

        self._send_json(404, {"error": "Unknown endpoint"})


def _idle_vram_watchdog(rt: RookRuntimeState) -> None:
    """Unloads VRAM automatically after 15 minutes of inactivity so GPUs stay cool."""
    while True:
        time.sleep(30)
        if rt.engine_mgr.is_online() is not None:
            if (time.time() - rt.last_interaction) > IDLE_VRAM_TIMEOUT_SEC:
                rt.engine_mgr.unload()


def launch_desktop_window(url: str) -> Optional[subprocess.Popen]:
    """
    Opens Rook as a GIMP-style Single-Window Desktop Application if a local X11/Wayland
    display is active. When the user closes that window, the parent process detects
    window exit and immediately unloads VRAM.
    """
    env = os.environ.copy()
    if not env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY"):
        if os.path.exists("/tmp/.X11-unix/X0"):
            env["DISPLAY"] = ":0"
        else:
            return None
    if env.get("DISPLAY") and not env.get("XAUTHORITY"):
        home_xauth = os.path.expanduser("~/.Xauthority")
        if os.path.isfile(home_xauth):
            env["XAUTHORITY"] = home_xauth
    for browser in ("chromium", "chromium-browser", "google-chrome", "brave-browser", "microsoft-edge"):
        bpath = shutil.which(browser)
        if bpath:
            profile_dir = "/tmp/rook_app_window_profile"
            lock_path = os.path.join(profile_dir, "SingletonLock")
            if os.path.islink(lock_path):
                try:
                    target = os.readlink(lock_path)
                    pid_str = target.rsplit("-", 1)[-1]
                    if pid_str.isdigit():
                        try:
                            os.kill(int(pid_str), 0)
                        except ProcessLookupError:
                            for fname in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
                                fp = os.path.join(profile_dir, fname)
                                if os.path.lexists(fp):
                                    os.unlink(fp)
                except OSError:
                    pass
            return subprocess.Popen(
                [
                    bpath,
                    f"--app={url}",
                    f"--user-data-dir={profile_dir}",
                    "--window-size=1440,900",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--password-store=basic",
                    "--disable-features=Translate",
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    if shutil.which("xdg-open"):
        return subprocess.Popen(
            ["xdg-open", url],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Rook: Single-Window Local AI Field Unit")
    parser.add_argument("--host", default=DEFAULT_UI_HOST, help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=DEFAULT_UI_PORT, help="UI port (default: 8490)")
    parser.add_argument("--models-dir", default=DEFAULT_MODELS_DIR, help="GGUF models directory")
    parser.add_argument("--workspace", default="~/rook", help="Default Home workspace directory")
    parser.add_argument("--work-dir", default=os.environ.get("ROOK_WORK_DIR", "~/rook-work"), help="Isolated Work compartment directory")
    parser.add_argument("--no-window", action="store_true", help="Run server without spawning local X11 browser window")
    args = parser.parse_args()

    global RUNTIME
    RUNTIME = RookRuntimeState(
        workspace_home=os.path.abspath(os.path.expanduser(args.workspace)),
        workspace_work=os.path.abspath(os.path.expanduser(args.work_dir)),
        models_dir=args.models_dir,
    )

    st = RUNTIME.engine_mgr.get_state_metadata()

    atexit.register(RUNTIME.shutdown_everything)
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda s, f: (RUNTIME.shutdown_everything(), sys.exit(0)))

    threading.Thread(target=_idle_vram_watchdog, args=(RUNTIME,), daemon=True).start()

    local_url = f"http://127.0.0.1:{args.port}"
    try:
        server = ThreadingHTTPServer((args.host, args.port), RookHTTPHandler)
    except OSError as exc:
        if getattr(exc, "errno", None) == 98:
            print(f"[*] Port {args.port} already active; opening Rook window to {local_url}")
            if not args.no_window:
                win_proc = launch_desktop_window(local_url)
                if win_proc is not None:
                    win_proc.wait()
            return 0
        raise
    RUNTIME.server_ref = server

    if st and st.get("model_path") and not RUNTIME.engine_mgr.is_online():
        mpath = st["model_path"]
        if os.path.isfile(mpath):
            def _bg_restore(mp: str, hemi: Optional[str]):
                try:
                    print(f"[*] Restoring active GGUF brain into VRAM: {os.path.basename(mp)}...")
                    RUNTIME.engine_mgr.load(model_path=mp, force_hemisphere=hemi)
                except Exception as exc:
                    print(f"[!] Auto-restore warning: {exc}")
            threading.Thread(target=_bg_restore, args=(mpath, st.get("hemisphere")), daemon=True).start()

    print(f"[+] ROOK Single-Window Appliance listening at {local_url}")
    print("[+] Closing the program or clicking [QUIT & FREE VRAM] immediately releases 100% of GPU VRAM.")

    win_proc = None if args.no_window else launch_desktop_window(local_url)
    if win_proc is not None:
        t_launch = time.time()
        def _watch_window(p: subprocess.Popen, rt: RookRuntimeState, launched_at: float):
            p.wait()
            if (time.time() - launched_at) >= 2.5:
                rt.shutdown_everything()
        threading.Thread(target=_watch_window, args=(win_proc, RUNTIME, t_launch), daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        RUNTIME.shutdown_everything()
    return 0


if __name__ == "__main__":
    sys.exit(main())
