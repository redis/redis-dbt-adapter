#!/usr/bin/env python3
"""Verify a clean checkout of the immutable engine commit in upstream.json."""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent


def verify(engine):
    pinned = json.loads((ROOT / "upstream.json").read_text())["implementation_commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", pinned):
        raise ValueError("Engine commit must be an immutable 40-character SHA")
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=engine, text=True).strip()
    head = git("rev-parse", "HEAD")
    if head != pinned:
        raise ValueError("Engine HEAD must match the pinned engine commit")
    if git("diff", "HEAD", "--name-only"):
        raise ValueError("Use a clean pinned engine checkout; tracked changes obscure its identity")
    return {"engine_commit": head, "engine_tree": git("rev-parse", "HEAD^{tree}"),
            "engine_source_state": "merged-pinned"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.engine.resolve()), indent=2))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Cannot verify pinned engine: {error}\n")
