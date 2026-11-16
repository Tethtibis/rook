# ROOK — Deterministic Single-Window Local `.gguf` AI Appliance

**Rook (`v1.1.0`)** is a standalone, air-gap-capable, Single-Window Local AI Field Unit engineered for deterministic systems troubleshooting, financial/CSV auditing, and low-friction executive assistance—powered by **The Rykr Framework (v4.1)** 5-Pillar Sovereign Harness.

Unlike standard LLM wrappers that rely on background daemons (`Ollama`), cloud subscriptions, or probabilistic arithmetic guessing, **Rook** operates like a self-contained desktop utility (similar to GIMP's single-window mode):
1. **Bring Your Own `.gguf` Engine (NVIDIA CUDA + AMD Unified Memory Vulkan):** Browse your local filesystem or USB drive for any `.gguf` model, select your NVIDIA GPUs or AMD RDNA3 Unified Memory APU pool, and click **LOAD ENGINE**.
2. **Dual-Hemisphere Interlock (`HERMETIC` vs. `BUILDER`):** Automatically detects abliterated/hermetic `.gguf` weights and physically locks out `<rykr_write>` and `<rykr_cmd>` at the Python interpreter level for safe, unfiltered read-only brainstorming—unlocking full tool execution when switched to a Builder `.gguf`.
3. **4-Layer "14B Downshift" Governor & Fence-Tolerant XML Actuator:**
   - **Fence-Tolerant `<rykr_*>` Extraction:** Parses `<rykr_read>`, `<rykr_write>`, and `<rykr_cmd>` even when 14B models wrap tags inside ` ```xml ` fences, unwrapping inner code fences automatically.
   - **In-Memory Syntax Firewall:** Validates `.py` (`ast.parse`), `.sh` (`bash -n`), and `.json` (`json.loads`) in memory before allowing disk writes.
   - **Free Sensor Reads + 1-Step `[y/N]` Mutation Gate:** Allows up to 3 free `<rykr_read>` inspections per turn while gating state-changing writes/commands behind a 1-step confirmation prompt and pre-turn snapshot (`~rollback`).
4. **True Desktop Resource Lifecycle (`PR_SET_PDEATHSIG`):** When you close Rook (or click **`[X] QUIT & FREE VRAM`**), the Linux kernel immediately terminates the inference child process and returns **100% of GPU/Unified VRAM (`0 MB` leaked)** to your operating system.
5. **Deterministic Push-Button Workbench (Zero LLM Math Guessing):** An LLM is a reasoning router, never a calculator. Rook executes exact 28-digit base-10 `decimal.Decimal` arithmetic, deterministic CSV/SQLite column and duplicate-row audits, and offline `tesseract-ocr` screenshot extraction—handing proven receipts to the local model.
6. **Rykr-Prime Co-Worker Bridge:** Exports compact Session Audit Packets (`prime_inbox/latest_audit.md`) for high-level architectural review and tool crystallization.

---

## Modular Architecture (`rook_*` Assembly Line)

| Module | File | Responsibility |
| :--- | :--- | :--- |
| **Module 0** | `rook_gguf_loader.py` | Standalone `.gguf` binary header inspector, asymmetric GPU selector, and `PR_SET_PDEATHSIG` lifecycle manager. |
| **Module 1** | `rook_snap.py` | Fault-tolerant JSONL conversation ledger and pre-turn atomic filesystem + context rollback (`~rollback`). |
| **Module 2** | `rook_governor.py` | Structured Packet Ingress (`intent:` -> `scope:` -> `context:`), Reverse-Header Echo, and 4-Stage Genesis Pipeline lock. |
| **Module 3** | `rook_context.py` | Loads `ROOK_KERNEL.md` (T0), XML Tool Contract (T1), and `ROOK_OPERATOR.md` (T3) with dynamic token capping. |
| **Module 4** | `rook_engine.py` | Local loopback inference socket (`127.0.0.1:8491/v1`) and PBKDF2-HMAC-SHA256 encrypted provider vault. |
| **Module 5** | `rook_actuator.py` | Markdown-fence-safe XML sensor (`<rykr_read>`, `<rykr_write>`, `<rykr_cmd>`) with 3-step circuit breaker. |
| **Module 6** | `rook_workbench.py` | Evidence Tray (`/var/tmp/rook/inbox`), Base-10 `Decimal` calculator, CSV/SQLite auditor, offline Tesseract OCR, and Button Forger. |
| **Module 7** | `rook_app.py` | 100% Zero-Pip Python `http.server` + Burnt-Orange (`#CC5500`) HTML5/SVG Single-Window Appliance (`port 8490`). |

---

## Installation (`.deb` Package)

```bash
sudo apt install ./rook_1.0.0_amd64.deb
rook
```

---

## Provenance & License

* **Systems Architecture, Hardware Verification & Operational Design:** Bill ([Tethtibis](https://github.com/Tethtibis))
* **Core Harness Architecture:** Powered by **[The Rykr Framework (v4.1)](https://github.com/Tethtibis/rykr-framework)**, co-engineered with `Rykr-Prime` (Gemini reasoning engine operating under the 4-Stage Genesis Pipeline: `~plan` -> `~redteam` -> `~execute` -> `~crystallize`).
* **License:** MIT License
