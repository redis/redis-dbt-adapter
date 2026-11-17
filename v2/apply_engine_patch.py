#!/usr/bin/env python3
"""Apply the reviewable Flight implementation to the pinned external dbt engine."""
import argparse
import json
from pathlib import Path
import subprocess


def apply(engine):
    root = Path(__file__).resolve().parent
    base = json.loads((root / "upstream.json").read_text())["implementation_commit"]
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=engine, text=True).strip()
    if head != base:
        raise ValueError("Engine HEAD must match v2/upstream.json before applying the Flight patch")
    patch = root / "engine" / "flight-sql.patch"
    command = ["git", "apply", "--whitespace=error", str(patch)]
    if subprocess.run(["git", "apply", "--reverse", "--check", str(patch)],
                      cwd=engine, capture_output=True).returncode == 0:
        print("Flight engine patch is already applied.")
        return
    if subprocess.check_output(["git", "diff", "HEAD", "--name-only"], cwd=engine):
        raise ValueError("Use a clean engine checkout; existing tracked changes would obscure the patch")
    subprocess.run([*command[:2], "--check", *command[2:]], cwd=engine, check=True)
    subprocess.run(command, cwd=engine, check=True)
    print("Applied experimental Flight engine patch. Build and qualify before use.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path)
    args = parser.parse_args()
    try:
        apply(args.engine.resolve())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Cannot apply Flight engine patch: {error}\n")
