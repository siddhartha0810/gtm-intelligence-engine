"""
checkpoint.py
=============
Saves pipeline state to disk after every stage so a crashed or interrupted
run can resume from exactly where it left off — without re-calling APIs or
losing enrichment work already done.

How it works:
  - After each stage, the full DataFrame is saved as a Parquet file
  - The stage name is saved in a JSON metadata file
  - On the next run, the pipeline checks for these files and skips
    any stages that were already completed

Files written:
  output/checkpoint.parquet      — the DataFrame snapshot
  output/checkpoint_meta.json    — the last completed stage name

Usage:
  save(df, "enriched")           → save state after enrichment stage
  df, last_stage = load()        → load saved state (returns None, None if no checkpoint)
  clear()                        → delete checkpoint files after successful run
  should_skip("cleaned", last)   → True if "cleaned" was already done
"""

import json
import os
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

# ── File Paths ─────────────────────────────────────────────────────────────
CHECKPOINT_DF   = "output/checkpoint.parquet"
CHECKPOINT_META = "output/checkpoint_meta.json"

# ── Stage Order ────────────────────────────────────────────────────────────
# The pipeline runs these stages in order. Checkpoint logic uses this list
# to decide which stages to skip when resuming a partial run.
# "_partial" suffix means the stage started but didn't finish (e.g. enrichment
# crashed halfway). Everything before it is done; the partial stage re-runs.
STAGES = [
    "cleaned",
    "domain_resolved",
    "enriched",
    "vendor_validated",
    "email_predicted",
    "pred_validated",
    "scored",
]


def _base(stage: str) -> str:
    """Strip '_partial' suffix to get the base stage name."""
    return stage.replace("_partial", "")


def _idx(stage: str) -> int:
    """Return the position of a stage in the STAGES list (-1 if not found)."""
    try:
        return STAGES.index(_base(stage))
    except ValueError:
        return -1


# ── Public API ─────────────────────────────────────────────────────────────

def save(df: pd.DataFrame, stage: str) -> None:
    """
    Save the current DataFrame and stage name to disk.

    Called:
      - After every completed stage (cleaned, domain_resolved, enriched, etc.)
      - Every 50 leads during enrichment (so a crash loses at most 50 leads of work)

    Parquet format is used because it's fast and preserves data types exactly.
    """
    os.makedirs("output", exist_ok=True)
    df.to_parquet(CHECKPOINT_DF, index=True)
    with open(CHECKPOINT_META, "w") as f:
        json.dump({"last_stage": stage}, f)

    label = stage if not stage.endswith("_partial") else f"{stage} (mid-run)"
    print(f"    OK checkpoint saved [{label}]")


def load() -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    Load the most recent checkpoint from disk.

    Returns:
      (df, last_stage)  — if a checkpoint exists
      (None, None)      — if no checkpoint found (fresh run)
    """
    if not Path(CHECKPOINT_DF).exists() or not Path(CHECKPOINT_META).exists():
        return None, None

    df = pd.read_parquet(CHECKPOINT_DF)
    with open(CHECKPOINT_META) as f:
        meta = json.load(f)
    return df, meta.get("last_stage")


def clear() -> None:
    """
    Delete checkpoint files after a successful run (or when --restart is used).
    Called at the very end of the pipeline so the next run starts fresh.
    """
    for p in [CHECKPOINT_DF, CHECKPOINT_META]:
        Path(p).unlink(missing_ok=True)


def should_skip(stage: str, last_stage: Optional[str]) -> bool:
    """
    Decide whether a stage can be skipped on a resumed run.

    Rules:
      - If last_stage is a full stage name (e.g. "enriched"):
          everything up to and including it is done → skip if curr_idx <= last_idx
      - If last_stage ends with "_partial" (e.g. "enriched_partial"):
          the partial stage itself is NOT done yet, only earlier stages are done
          → skip if curr_idx < last_idx  (the partial stage must re-run)

    Example:
      last_stage = "domain_resolved"
      should_skip("cleaned", ...)        → True  (already done)
      should_skip("domain_resolved", ...) → True  (already done)
      should_skip("enriched", ...)        → False (not yet done)
    """
    if not last_stage:
        return False
    last_idx = _idx(last_stage)
    curr_idx = _idx(stage)
    if last_stage.endswith("_partial"):
        return curr_idx < last_idx
    return curr_idx <= last_idx
