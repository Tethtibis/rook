#!/usr/bin/env python3
"""
==============================================================================
ROOK-ENGINE (MODULE 4): HOT-SWAPPABLE LLM SOCKET & ENCRYPTED KEY VAULT
==============================================================================
Part of the Rook Local Appliance (Zero-Pip Python 3 Standard Library).
Responsibilities:
  1. Authenticated Encrypted API Key Vault (`~/.config/rykr/providers.enc`):
     - Uses 100% Python stdlib `hashlib.pbkdf2_hmac` (200,000 iterations) +
       HMAC-SHA256 authenticated keystream encryption so API keys are never
       stored in plain text on disk, while working identically on Linux,
       Windows, and macOS without external libraries.
  2. Universal Hot-Swappable LLM Drivers (`urllib.request`):
     - `rook`: Local Rook GGUF Worker (`127.0.0.1:8491/v1/chat/completions`)
     - `gemini`: Google Generative Language REST API (`v1beta/models/...`)
     - `openai`: Any OpenAI-compatible `/v1/chat/completions` server
                 (LM Studio, llama.cpp, vLLM, OpenRouter)
==============================================================================
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Any, List, Optional

DEFAULT_VAULT_PATH = os.path.expanduser("~/.config/rykr/providers.enc")
DEFAULT_SUDO_KEY_PATH = os.path.expanduser("~/.rykr_sudo")


def _derive_keys(passphrase: str, salt: bytes):
    """Derives a 32-byte encryption key and 32-byte HMAC key via PBKDF2-HMAC-SHA256."""
    dk = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, 200_000, dklen=64)
    return dk[:32], dk[32:]


def _xor_keystream(data: bytes, enc_key: bytes, nonce: bytes) -> bytes:
    """Generates a deterministic SHA-256 counter-mode keystream and XORs with data."""
    out = bytearray(len(data))
    block_count = (len(data) + 31) // 32
    for counter in range(block_count):
        ctr_bytes = counter.to_bytes(8, "big")
        keystream_block = hashlib.sha256(enc_key + nonce + ctr_bytes).digest()
        start = counter * 32
        end = min(start + 32, len(data))
        for i in range(start, end):
            out[i] = data[i] ^ keystream_block[i - start]
    return bytes(out)


def encrypt_vault_payload(data_dict: Dict[str, Any], passphrase: str) -> str:
    """Encrypts a dictionary into an authenticated JSON envelope (PBKDF2 + SHA256-CTR + HMAC-SHA256)."""
    plaintext = json.dumps(data_dict, indent=2).encode("utf-8")
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    enc_key, mac_key = _derive_keys(passphrase, salt)
    ciphertext = _xor_keystream(plaintext, enc_key, nonce)
    tag = hmac.new(mac_key, salt + nonce + ciphertext, hashlib.sha256).digest()
    envelope = {
        "kdf": "PBKDF2-HMAC-SHA256-200K",
        "cipher": "SHA256-CTR-HMAC",
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
    }
    return json.dumps(envelope, indent=2)


def decrypt_vault_payload(envelope_json: str, passphrase: str) -> Dict[str, Any]:
    """Verifies HMAC-SHA256 tag and decrypts the provider vault dictionary."""
    env = json.loads(envelope_json)
    salt = base64.b64decode(env["salt"])
    nonce = base64.b64decode(env["nonce"])
    ciphertext = base64.b64decode(env["ciphertext"])
    expected_tag = base64.b64decode(env["tag"])
    enc_key, mac_key = _derive_keys(passphrase, salt)
    actual_tag = hmac.new(mac_key, salt + nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(actual_tag, expected_tag):
        raise ValueError("Vault authentication failed: invalid passphrase or tampered file.")
    plaintext = _xor_keystream(ciphertext, enc_key, nonce)
    return json.loads(plaintext.decode("utf-8"))


def get_default_passphrase(explicit_pass: Optional[str] = None) -> str:
    if explicit_pass:
        return explicit_pass
    if os.environ.get("RYKR_VAULT_PASSPHRASE"):
        return os.environ["RYKR_VAULT_PASSPHRASE"]
    if os.path.isfile(DEFAULT_SUDO_KEY_PATH):
        try:
            with open(DEFAULT_SUDO_KEY_PATH, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            pass
    return "rykr-local-default-key"


def load_provider_vault(vault_path: str = DEFAULT_VAULT_PATH, passphrase: Optional[str] = None) -> Dict[str, Any]:
    vp = Path(vault_path)
    if not vp.is_file():
        return {
            "gemini": {
                "api_key": os.environ.get("GEMINI_API_KEY", ""),
                "model": "gemini-2.5-pro",
            },
            "ollama": {
                "endpoint": "http://127.0.0.1:11434",
                "model": "local-model",
            },
            "rook": {
                "endpoint": "http://127.0.0.1:8491/v1",
                "model": "local-gguf",
            },
            "openai": {
                "endpoint": "http://127.0.0.1:1234/v1",
                "api_key": os.environ.get("OPENAI_API_KEY", "lm-studio"),
                "model": "local-model",
            },
        }
    pw = get_default_passphrase(passphrase)
    return decrypt_vault_payload(vp.read_text(encoding="utf-8"), pw)


def save_provider_vault(data: Dict[str, Any], vault_path: str = DEFAULT_VAULT_PATH, passphrase: Optional[str] = None):
    vp = Path(vault_path)
    vp.parent.mkdir(parents=True, exist_ok=True)
    pw = get_default_passphrase(passphrase)
    enc_text = encrypt_vault_payload(data, pw)
    vp.write_text(enc_text, encoding="utf-8")
    try:
        os.chmod(vp, 0o600)
    except OSError:
        pass


def call_gemini(system_instruction: str, messages: List[Dict[str, str]], model: str, api_key: str, timeout: int = 120) -> str:
    if not api_key:
        raise RuntimeError("Missing Gemini API key. Store via `rykr_engine.py set-key --provider gemini --key ...` or GEMINI_API_KEY.")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    contents = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})

    payload = {
        "system_instruction": {"parts": [{"text": system_instruction}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.2},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    candidates = body.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates: {body}")
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


def call_ollama(system_instruction: str, messages: List[Dict[str, str]], endpoint: str, model: str, timeout: int = 180) -> str:
    url = f"{endpoint.rstrip('/')}/api/chat"
    ollama_msgs = [{"role": "system", "content": system_instruction}]
    for m in messages:
        ollama_msgs.append({"role": m["role"], "content": m["content"]})

    payload = {
        "model": model,
        "messages": ollama_msgs,
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": 8192},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body.get("message", {}).get("content", "")


def call_openai_compat(
    system_instruction: str,
    messages: List[Dict[str, str]],
    endpoint: str,
    model: str,
    api_key: str = "local",
    timeout: int = 180,
) -> str:
    url = f"{endpoint.rstrip('/')}/chat/completions"
    oai_msgs = [{"role": "system", "content": system_instruction}]
    for m in messages:
        oai_msgs.append({"role": m["role"], "content": m["content"]})

    payload = {
        "model": model,
        "messages": oai_msgs,
        "temperature": 0.2,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    choices = body.get("choices", [])
    if not choices:
        raise RuntimeError(f"OpenAI-compatible endpoint returned no choices: {body}")
    return choices[0].get("message", {}).get("content", "")


def dispatch_inference(
    engine_spec: str,
    system_instruction: str,
    messages: List[Dict[str, str]],
    vault_path: str = DEFAULT_VAULT_PATH,
    passphrase: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Routes inference to the selected engine profile:
      - `rook` or `rook:<model>`
      - `gemini` or `gemini:<model>`
      - `ollama` or `ollama:<model>`
      - `openai` or `openai:<model>`
      - `mock` (deterministic offline test driver)
    """
    parts = engine_spec.split(":", 1)
    provider = parts[0].lower()
    model_override = parts[1] if len(parts) > 1 else None

    if provider == "mock":
        last_msg = messages[-1]["content"] if messages else ""
        reply = (
            "[PARSED INTENT: Execute deterministic mock validation | SCOPE: Verification]\n"
            f"Mock Engine received {len(messages)} message(s). Last input length: {len(last_msg)} chars."
        )
        return {"status": "SUCCESS", "provider": "mock", "model": "mock-v1", "response": reply}

    vault = load_provider_vault(vault_path, passphrase=passphrase)

    if provider == "gemini":
        cfg = vault.get("gemini", {})
        model = model_override or cfg.get("model", "gemini-2.5-pro")
        key = cfg.get("api_key") or os.environ.get("GEMINI_API_KEY", "")
        text = call_gemini(system_instruction, messages, model, key)
        return {"status": "SUCCESS", "provider": "gemini", "model": model, "response": text}

    if provider == "ollama":
        cfg = vault.get("ollama", {})
        endpoint = cfg.get("endpoint", "http://127.0.0.1:11434")
        model = model_override or cfg.get("model", "local-model")
        text = call_ollama(system_instruction, messages, endpoint, model)
        return {"status": "SUCCESS", "provider": provider, "model": model, "endpoint": endpoint, "response": text}

    if provider in ("rook", "openai"):
        cfg = vault.get(provider, {})
        default_ep = "http://127.0.0.1:8491/v1" if provider == "rook" else "http://127.0.0.1:1234/v1"
        endpoint = cfg.get("endpoint", default_ep)
        model = model_override or cfg.get("model", "local-gguf")
        key = cfg.get("api_key", "local")
        text = call_openai_compat(system_instruction, messages, endpoint, model, key)
        return {"status": "SUCCESS", "provider": provider, "model": model, "endpoint": endpoint, "response": text}

    raise ValueError(f"Unsupported engine provider '{provider}'. Use rook, gemini, ollama, openai, or mock.")


def main():
    parser = argparse.ArgumentParser(description="Rook-Engine (Module 4): Hot-Swappable LLM Socket & Encrypted Vault")
    parser.add_argument("--vault", default=DEFAULT_VAULT_PATH, help="Encrypted provider vault path")
    sub = parser.add_subparsers(dest="action")

    p_set = sub.add_parser("set-key", help="Encrypt and store a provider API key or endpoint in the vault")
    p_set.add_argument("--provider", required=True, choices=["rook", "gemini", "ollama", "openai"])
    p_set.add_argument("--key", default=None, help="API key to encrypt")
    p_set.add_argument("--endpoint", default=None, help="Endpoint URL override")
    p_set.add_argument("--model", default=None, help="Default model name")

    p_list = sub.add_parser("providers", help="List configured providers (keys masked)")

    p_run = sub.add_parser("infer", help="Run inference against the specified engine")
    p_run.add_argument("--engine", default="mock", help="Engine spec (e.g., rook, gemini, openai, mock)")
    p_run.add_argument("--system", default="You are Rykr.")
    p_run.add_argument("--prompt", required=True)

    args = parser.parse_args()
    if args.action == "set-key":
        vault = load_provider_vault(args.vault)
        entry = vault.setdefault(args.provider, {})
        if args.key is not None:
            entry["api_key"] = args.key
        if args.endpoint is not None:
            entry["endpoint"] = args.endpoint
        if args.model is not None:
            entry["model"] = args.model
        save_provider_vault(vault, args.vault)
        sys.stdout.write(json.dumps({"status": "SUCCESS", "provider": args.provider, "vault": args.vault}, indent=2) + "\n")
    elif args.action == "providers":
        vault = load_provider_vault(args.vault)
        masked = {}
        for k, v in vault.items():
            c = dict(v)
            if c.get("api_key"):
                raw_k = c["api_key"]
                c["api_key"] = (raw_k[:4] + "..." + raw_k[-4:]) if len(raw_k) > 8 else "***ENCRYPTED***"
            masked[k] = c
        sys.stdout.write(json.dumps(masked, indent=2) + "\n")
    elif args.action == "infer":
        res = dispatch_inference(args.engine, args.system, [{"role": "user", "content": args.prompt}], args.vault)
        sys.stdout.write(json.dumps(res, indent=2) + "\n")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
