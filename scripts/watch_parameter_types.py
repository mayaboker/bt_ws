#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from pathlib import Path

from generate_parameter_types import DEFAULT_INPUT, DEFAULT_OUTPUT_DIR, ROOT, generate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Watch parameter YAML and regenerate typed helpers")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--interval", type=float, default=0.5)
    return parser


def regenerate(input_path: Path, output_dir: Path) -> None:
    changed = generate(input_path, output_dir)
    if changed:
        for path in changed:
            print(f"generated {path.relative_to(ROOT)}", flush=True)
    else:
        print("parameter generated files are up to date", flush=True)


def main() -> None:
    args = build_parser().parse_args()
    input_path = args.input
    output_dir = args.output_dir

    print(f"watching {input_path.relative_to(ROOT)}", flush=True)
    regenerate(input_path, output_dir)
    last_mtime_ns = input_path.stat().st_mtime_ns

    while True:
        time.sleep(args.interval)
        try:
            current_mtime_ns = input_path.stat().st_mtime_ns
        except FileNotFoundError:
            print(f"waiting for {input_path}", flush=True)
            continue

        if current_mtime_ns == last_mtime_ns:
            continue

        last_mtime_ns = current_mtime_ns
        try:
            regenerate(input_path, output_dir)
        except Exception as exc:
            print(f"parameter generation failed: {exc}", flush=True)


if __name__ == "__main__":
    main()
