"""
common/config.py — Repo-root resolution, .env loading and shared paths/settings.

Every script in this repo does:

    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from common import config

so `common` is importable regardless of the working directory the script is run from.
Credentials are read as `env var → JSON config file fallback`, exactly like the POC, so the
same code runs locally (with .env / bc_config.json) and in CI (env vars only).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Windows consoles default to cp1252 — make emoji/Swedish output safe everywhere.
import sys as _sys

for _stream in (_sys.stdout, _sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pragma: no cover
            pass


def _find_repo_root() -> Path:
    """Walk up from this file until a folder containing .env or requirements.txt is found."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".env").exists() or (parent / "requirements.txt").exists():
            return parent
    return here.parents[1]


REPO_ROOT: Path = _find_repo_root()
load_dotenv(REPO_ROOT / ".env")

# --- Paths -------------------------------------------------------------------------------
DISCOVERY_DIR = REPO_ROOT / "discovery"
AGENTS_DIR = REPO_ROOT / "agents"
EVALUATION_DIR = REPO_ROOT / "evaluation"
OUTPUT_DIR = Path(os.getenv("BC_OUTPUT_DIR", REPO_ROOT / "output"))

REPOS_CONFIG_FILE = Path(os.getenv("REPOS_CONFIG_FILE", DISCOVERY_DIR / "repos_config.json"))
BC_CONFIG_FILE = DISCOVERY_DIR / "bc_config.json"
KNOWN_EXTENSIONS_FILE = DISCOVERY_DIR / "known_extensions.json"
DOC_STATE_FILENAME = ".doc_state.json"

# --- Foundry -----------------------------------------------------------------------------
PROJECT_CONNECTION_STRING = os.getenv("PROJECT_CONNECTION_STRING", "")
MODEL_DEPLOYMENT_NAME = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-5.4")
APPINSIGHTS_CONNECTION_STRING = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "")

CODE_ANALYST_AGENT_NAME = os.getenv("CODE_ANALYST_AGENT_NAME", "bc-code-analyst")
CHANGE_TRACKER_AGENT_NAME = os.getenv("CHANGE_TRACKER_AGENT_NAME", "bc-change-tracker")

# --- Limits -------------------------------------------------------------------------------
# AL source sent to the model per repo (~80k tokens). Beyond this, files are summarised only.
MAX_AL_CHARS = int(os.getenv("MAX_AL_CHARS", "300000"))
# Patch text per changed file passed to the change tracker.
MAX_PATCH_CHARS = int(os.getenv("MAX_PATCH_CHARS", "6000"))
MAX_TOTAL_PATCH_CHARS = int(os.getenv("MAX_TOTAL_PATCH_CHARS", "120000"))


# --- Helpers --------------------------------------------------------------------------------
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def slugify(name: str) -> str:
    """File-system-safe slug that still carries the human name (spaces → underscores)."""
    slug = re.sub(r"[^\w\-. ]+", "", name, flags=re.UNICODE).strip()
    slug = re.sub(r"\s+", "_", slug)
    return slug or "unnamed"


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(path: Path, data) -> None:
    """Write JSON via temp file + rename so an interrupted run never corrupts the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def github_token() -> str:
    """GITHUB_TOKEN env var. Raises a clear error if missing."""
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set (see .env.example)")
    return token


def bc_credentials() -> dict:
    """
    Business Central auth settings: env vars first, discovery/bc_config.json as fallback.
    Returns {client_id, client_secret, tenant_id, environment, company_name, own_publisher}.
    """
    file_cfg = load_json(BC_CONFIG_FILE, default={}) or {}
    ad = file_cfg.get("azure_ad", {})
    bc = file_cfg.get("bc", {})
    creds = {
        "client_id": os.getenv("BC_CLIENT_ID") or ad.get("client_id", ""),
        "client_secret": os.getenv("BC_CLIENT_SECRET") or ad.get("client_secret", ""),
        "tenant_id": os.getenv("BC_TENANT_ID") or ad.get("tenant_id", ""),
        "environment": os.getenv("BC_ENVIRONMENT") or bc.get("environment", "Production"),
        "company_name": os.getenv("BC_COMPANY_NAME") or bc.get("company_name", ""),
        "own_publisher": os.getenv("BC_OWN_PUBLISHER") or bc.get("own_publisher", ""),
    }
    missing = [k for k in ("client_id", "client_secret") if not creds[k]]
    if missing:
        raise RuntimeError(
            f"Business Central credentials missing: {', '.join(missing)} "
            "(set BC_CLIENT_ID/BC_CLIENT_SECRET or create discovery/bc_config.json)"
        )
    return creds


def load_repos_config(path: Path | None = None) -> dict:
    path = path or REPOS_CONFIG_FILE
    cfg = load_json(path)
    if cfg is None:
        raise FileNotFoundError(
            f"{path} not found — copy discovery/repos_config.example.json and add your customers"
        )
    return cfg


def customer_output_dir(customer_name: str) -> Path:
    return OUTPUT_DIR / slugify(customer_name)


def foundry_account_endpoint() -> str:
    """
    Derive the account-level endpoint (https://<account>.services.ai.azure.com) from the
    project endpoint. Used as `azure_endpoint` for the evaluation judge model.
    """
    conn = PROJECT_CONNECTION_STRING
    if "/api/projects/" in conn:
        return conn.split("/api/projects/")[0]
    return os.getenv("FOUNDRY_ENDPOINT", "").rstrip("/")
