#!/usr/bin/env python3
"""
==============================================================================
ROOK MODULE 0: STANDALONE VULKAN/CUDA GGUF LOADER & UNIFIED MEMORY MANAGER
==============================================================================
Manages direct, zero-daemon native `llama-server` child processes on AMD RDNA3
Unified Memory APUs (Vulkan) or NVIDIA GPUs (CUDA), bound to parent lifecycle
via Linux kernel PR_SET_PDEATHSIG (closing or unloading immediately frees 100%
of Unified DDR5 / GPU VRAM).

Key Features:
  - Automatic Hemisphere Classification (`HERMETIC` vs `BUILDER`) from `.gguf`
    filename so abliterated/hermetic models enforce hard execution locks.
  - `--no-mmap` Unified Memory optimization on AMD APUs to prevent Linux kernel
    page-cache double-allocation of 8-10 GB `.gguf` weights.
==============================================================================
"""

import argparse
import ctypes
import glob
import json
import os
import queue
import signal
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_MODELS_DIR = os.path.expanduser("~/Models")
DEFAULT_WORKER_HOST = "127.0.0.1"
DEFAULT_WORKER_PORT = 8491
STATE_FILE = "/tmp/rook_engine_state.json"

LLAMA_SERVER_CANDIDATES = [
    
    
    "/opt/rook/bin/llama-server",
    os.path.expanduser("~/rook/bin/llama-server"),
    "/usr/local/bin/llama-server",
]

HERMETIC_KEYWORDS = ("abliterated", "hermes", "uncensored", "dolphin", "hermetic")


def classify_model_hemisphere(filename: str) -> str:
    lower = filename.lower()
    if any(k in lower for k in HERMETIC_KEYWORDS):
        return "HERMETIC"
    return "BUILDER"


def resolve_llama_server_bin() -> str:
    for cand in LLAMA_SERVER_CANDIDATES:
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    raise FileNotFoundError(
        f"Standalone llama-server binary not found in {LLAMA_SERVER_CANDIDATES}"
    )


def _bind_parent_death_signal() -> None:
    if sys.platform.startswith("linux"):
        try:
            libc = ctypes.CDLL("libc.so.6")
            PR_SET_PDEATHSIG = 1
            libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)
        except Exception:
            pass


def probe_gpus() -> List[Dict[str, Any]]:
    """
    Probes NVIDIA GPUs via nvidia-smi OR AMD Unified Memory APUs via Linux DRM sysfs.
    """
    gpus: List[Dict[str, Any]] = []
    try:
        cmd = [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,memory.used,memory.free,temperature.gpu",
            "--format=csv,noheader,nounits",
        ]
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=3)
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 6:
                gpus.append({
                    "index": int(parts[0]),
                    "name": parts[1],
                    "backend": "cuda",
                    "vram_total_mb": int(parts[2]),
                    "vram_used_mb": int(parts[3]),
                    "vram_free_mb": int(parts[4]),
                    "temp_c": int(parts[5]),
                })
        if gpus:
            return gpus
    except Exception:
        pass

    # Probe AMD APU Unified Memory (VRAM carveout + GTT pool) via sysfs
    for card_dir in sorted(glob.glob("/sys/class/drm/card[0-9]/device")):
        vram_tot_p = os.path.join(card_dir, "mem_info_vram_total")
        gtt_tot_p = os.path.join(card_dir, "mem_info_gtt_total")
        if os.path.isfile(vram_tot_p) and os.path.isfile(gtt_tot_p):
            try:
                vram_tot = int(Path(vram_tot_p).read_text().strip())
                vram_used = int(Path(os.path.join(card_dir, "mem_info_vram_used")).read_text().strip())
                gtt_tot = int(Path(gtt_tot_p).read_text().strip())
                gtt_used = int(Path(os.path.join(card_dir, "mem_info_gtt_used")).read_text().strip())

                total_mb = (vram_tot + gtt_tot) // (1024 * 1024)
                used_mb = (vram_used + gtt_used) // (1024 * 1024)
                free_mb = max(0, total_mb - used_mb)

                temp_c = 40
                for tfile in glob.glob(os.path.join(card_dir, "hwmon/hwmon*/temp1_input")):
                    try:
                        temp_c = int(Path(tfile).read_text().strip()) // 1000
                        break
                    except Exception:
                        pass

                gpus.append({
                    "index": 0,
                    "name": "AMD Radeon 780M (RADV Phoenix3 Unified DDR5)",
                    "backend": "vulkan",
                    "vram_carveout_mb": vram_tot // (1024 * 1024),
                    "gtt_pool_mb": gtt_tot // (1024 * 1024),
                    "vram_total_mb": total_mb,
                    "vram_used_mb": used_mb,
                    "vram_free_mb": free_mb,
                    "temp_c": temp_c,
                })
                break
            except Exception:
                pass
    return gpus


def inspect_gguf_header(path: Path) -> Dict[str, Any]:
    hemi = classify_model_hemisphere(path.name)
    info = {
        "name": path.name,
        "path": str(path.resolve()),
        "size_bytes": 0,
        "size_gb": 0.0,
        "valid_gguf": False,
        "gguf_version": None,
        "hemisphere": hemi,
        "execution_locked": (hemi == "HERMETIC"),
    }
    try:
        st = path.stat()
        info["size_bytes"] = st.st_size
        info["size_gb"] = round(st.st_size / (1024 ** 3), 2)
        with open(path, "rb") as f:
            header = f.read(8)
            if len(header) == 8 and header[:4] == b"GGUF":
                version = struct.unpack("<I", header[4:8])[0]
                info["valid_gguf"] = True
                info["gguf_version"] = version
    except OSError:
        pass
    return info


def scan_models_dir(models_dir: str = DEFAULT_MODELS_DIR) -> List[Dict[str, Any]]:
    p = Path(os.path.expanduser(models_dir))
    if not p.is_dir():
        return []
    models = []
    for item in sorted(p.glob("*.gguf")):
        if item.is_file() or item.is_symlink():
            meta = inspect_gguf_header(item)
            if meta["valid_gguf"] and meta["size_bytes"] > 1024 * 1024:
                models.append(meta)
    return models


def recommend_gpus_for_model(model_size_gb: float, gpus: List[Dict[str, Any]]) -> List[int]:
    if not gpus:
        return []
    sorted_gpus = sorted(gpus, key=lambda g: g["vram_total_mb"], reverse=True)
    needed_mb = int((model_size_gb + 1.1) * 1024)
    best = sorted_gpus[0]
    if best["vram_total_mb"] >= needed_mb:
        return [best["index"]]
    selected = []
    accum = 0
    for g in sorted_gpus:
        selected.append(g["index"])
        accum += g["vram_total_mb"]
        if accum >= needed_mb:
            break
    return sorted(selected)


class RookEngineManager:
    """
    Manages the lifecycle of the single `llama-server` child process.
    Guarantees that unloading or closing the parent program immediately kills
    the worker and returns 100% of Unified Memory / VRAM to the OS.
    """

    def __init__(self, port: int = DEFAULT_WORKER_PORT):
        self.port = port
        self.endpoint = f"http://{DEFAULT_WORKER_HOST}:{self.port}"
        self.proc: Optional[subprocess.Popen] = None
        self.last_active: float = time.time()
        self._spawn_req_q: "queue.Queue[Any]" = queue.Queue()
        self._spawn_res_q: "queue.Queue[Any]" = queue.Queue()
        self._spawner_thread = threading.Thread(target=self._persistent_spawner_loop, daemon=True)
        self._spawner_thread.start()

    def _persistent_spawner_loop(self) -> None:
        while True:
            item = self._spawn_req_q.get()
            if item is None:
                break
            cmd, env, bind_pdeath = item
            try:
                log_file = open("/tmp/rook_engine_worker.log", "w", encoding="utf-8")
                proc = subprocess.Popen(
                    cmd,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    env=env,
                    preexec_fn=_bind_parent_death_signal if bind_pdeath else None,
                    start_new_session=(not bind_pdeath),
                    close_fds=True,
                )
                self._spawn_res_q.put((proc, None))
            except Exception as exc:
                self._spawn_res_q.put((None, exc))

    def get_state_metadata(self) -> Optional[Dict[str, Any]]:
        if os.path.isfile(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def is_online(self) -> Optional[Dict[str, Any]]:
        try:
            req = urllib.request.Request(f"{self.endpoint}/health", method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                st = self.get_state_metadata() or {}
                mname = os.path.basename(st.get("model_path", ""))
                hemi = st.get("hemisphere") or classify_model_hemisphere(mname)
                return {
                    "status": data.get("status", "ok"),
                    "pid": st.get("pid"),
                    "model": mname,
                    "model_path": st.get("model_path", ""),
                    "hemisphere": hemi,
                    "execution_locked": (hemi == "HERMETIC"),
                    "gpu_indices": st.get("gpu_indices", []),
                    "n_ctx": st.get("n_ctx", 8192),
                    "uptime_sec": round(time.time() - st.get("started_at", time.time()), 1),
                }
        except Exception:
            return None

    def unload(self) -> Dict[str, Any]:
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None

        st = self.get_state_metadata()
        if st and st.get("pid"):
            try:
                os.kill(int(st["pid"]), signal.SIGKILL)
            except Exception:
                pass
        if os.path.isfile(STATE_FILE):
            try:
                os.remove(STATE_FILE)
            except OSError:
                pass

        subprocess.run(["pkill", "-9", "-f", f"llama-server.*--port {self.port}"], stderr=subprocess.DEVNULL)
        time.sleep(0.4)
        return {
            "status": "unloaded",
            "gpus": probe_gpus(),
        }

    def load(
        self,
        model_path: str,
        gpu_indices: Optional[List[int]] = None,
        n_ctx: int = 8192,
        bind_pdeath: bool = True,
        wait_timeout: int = 120,
        force_hemisphere: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved = Path(os.path.expanduser(model_path)).resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"GGUF file not found: {resolved}")

        header = inspect_gguf_header(resolved)
        if not header["valid_gguf"]:
            raise ValueError(f"File is not a valid GGUF binary: {resolved}")

        hemi = force_hemisphere if force_hemisphere in ("HERMETIC", "BUILDER") else header["hemisphere"]
        if header["hemisphere"] == "HERMETIC":
            # Never allow an abliterated/hermetic model to unlock execution
            hemi = "HERMETIC"

        server_bin = resolve_llama_server_bin()
        self.unload()

        gpus = probe_gpus()
        if gpu_indices is None:
            gpu_indices = recommend_gpus_for_model(header["size_gb"], gpus)

        env = os.environ.copy()
        is_vulkan = any(g.get("backend") == "vulkan" for g in gpus)
        if is_vulkan:
            env["GGML_VK_VISIBLE_DEVICES"] = "0"
            ngl = "999"
        else:
            env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            if gpu_indices:
                env["CUDA_VISIBLE_DEVICES"] = ",".join(str(i) for i in gpu_indices)
                ngl = "999"
            else:
                env["CUDA_VISIBLE_DEVICES"] = ""
                ngl = "0"

        threads = str(max(2, min(8, (os.cpu_count() or 8) // 2)))
        cmd = [
            server_bin,
            "--model", str(resolved),
            "--host", DEFAULT_WORKER_HOST,
            "--port", str(self.port),
            "--parallel", "1",
            "--ctx-size", str(n_ctx),
            "--n-gpu-layers", ngl,
            "--threads", threads,
            "--jinja",
        ]

        self._spawn_req_q.put((cmd, env, bind_pdeath))
        proc, spawn_err = self._spawn_res_q.get()
        if spawn_err is not None or proc is None:
            raise RuntimeError(f"Failed to spawn llama-server: {spawn_err}")
        self.proc = proc

        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "pid": self.proc.pid,
                "model_path": str(resolved),
                "hemisphere": hemi,
                "execution_locked": (hemi == "HERMETIC"),
                "gpu_indices": gpu_indices,
                "n_ctx": n_ctx,
                "port": self.port,
                "started_at": time.time(),
            }, f, indent=2)

        deadline = time.time() + wait_timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(
                    f"llama-server exited prematurely with code {self.proc.returncode}. "
                    f"Check /tmp/rook_engine_worker.log"
                )
            health = self.is_online()
            if health and health.get("status") == "ok":
                self.last_active = time.time()
                return {
                    "status": "online",
                    "pid": self.proc.pid,
                    "health": health,
                    "gpus": probe_gpus(),
                }
            time.sleep(0.5)

        self.unload()
        raise TimeoutError(f"Timed out waiting {wait_timeout}s for GGUF model to load into Unified Memory.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rook Module 0: Standalone Vulkan/CUDA GGUF Engine Loader")
    parser.add_argument("--no-pdeath", action="store_true", help="Allow worker to survive CLI parent exit")
    parser.add_argument("--status", action="store_true", help="Report GPU/APU + Engine status + available GGUF models")
    parser.add_argument("--load", "--model", dest="load", type=str, metavar="GGUF_PATH", help="Load a .gguf file into Unified Memory")
    parser.add_argument("--hemisphere", type=str, choices=["HERMETIC", "BUILDER"], default=None, help="Force HERMETIC (read-only) or BUILDER hemisphere")
    parser.add_argument("--unload", action="store_true", help="Unload active model and free 100%% of Unified RAM")
    parser.add_argument("--gpus", type=str, default=None, help="Comma-separated GPU indices")
    parser.add_argument("--ctx", type=int, default=8192, help="Context window tokens (default: 8192)")
    parser.add_argument("--port", type=int, default=DEFAULT_WORKER_PORT, help="Worker port (default: 8491)")
    parser.add_argument("--models-dir", type=str, default=DEFAULT_MODELS_DIR, help="Directory to scan for .gguf files")
    args = parser.parse_args()

    mgr = RookEngineManager(port=args.port)

    if args.unload:
        res = mgr.unload()
        print(json.dumps(res, indent=2))
        return 0

    if args.load:
        gpu_list = [int(x) for x in args.gpus.split(",") if x.strip() != ""] if args.gpus is not None else None
        res = mgr.load(
            model_path=args.load,
            gpu_indices=gpu_list,
            n_ctx=args.ctx,
            bind_pdeath=not args.no_pdeath,
            force_hemisphere=args.hemisphere,
        )
        print(json.dumps(res, indent=2))
        return 0

    gpus = probe_gpus()
    models = scan_models_dir(args.models_dir)
    online = mgr.is_online()
    print(json.dumps({
        "engine_online": online is not None,
        "active_worker": online,
        "gpus": gpus,
        "models_dir": os.path.expanduser(args.models_dir),
        "available_models": models,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
