#!/usr/bin/env python3
"""Verify the merged Flight engine, or reproduce the historical patch build."""
import argparse
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent


def apply(engine):
    sources = json.loads((ROOT / "upstream.json").read_text())
    pinned = sources["implementation_commit"]
    base = sources["flight_patch_base_commit"]
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=engine, text=True).strip()
    if head not in (pinned, base):
        raise ValueError("Engine HEAD must match the pinned merged engine or historical Flight patch base")
    patch = ROOT / "engine" / "flight-sql.patch"
    command = ["git", "apply", "--whitespace=error", str(patch)]
    if head == pinned:
        if subprocess.check_output(["git", "diff", "HEAD", "--name-only"], cwd=engine):
            raise ValueError("Use a clean pinned engine checkout; tracked changes obscure its identity")
        subprocess.run(["git", "apply", "--reverse", "--check", str(patch)],
                       cwd=engine, check=True, capture_output=True)
        print("Pinned merged engine already contains Flight SQL; no patch applied.")
        return
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
