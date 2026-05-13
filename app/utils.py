from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "outputs"


def load_task_tree() -> Dict[str, Any]:
    with (CONFIG_DIR / "task_tree.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def now_ms() -> int:
    return int(time.time() * 1000)


def add_log(state: Dict[str, Any], node: str, message: str, **extra: Any) -> None:
    state.setdefault("logs", [])
    payload = {"ts_ms": now_ms(), "node": node, "message": message}
    payload.update(extra)
    state["logs"].append(payload)


def ensure_outputs_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
