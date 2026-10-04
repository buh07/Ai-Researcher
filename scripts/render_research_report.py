#!/usr/bin/env python3
"""Render a recorded research chain without implying missing evidence exists."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from ai_researcher.reporting import render_research_report, rubric_artifact_json


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Render a deterministic terminal receipt from a supplied research-chain "
            "or learning-receipt JSON object."
        )
    )
    parser.add_argument("research_chain", type=Path, help="input JSON object")
    parser.add_argument(
        "--rubric-output",
        type=Path,
        help="write a machine-readable rubric-to-artifact map to this path",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    with args.research_chain.open("r", encoding="utf-8") as stream:
        chain = json.load(stream)
    if not isinstance(chain, Mapping):
        raise TypeError("research-chain JSON must contain an object at its root")

    sys.stdout.write(render_research_report(chain))
    if args.rubric_output is not None:
        _atomic_write_text(args.rubric_output, rubric_artifact_json(chain))
    return 0


def _atomic_write_text(path: Path, value: str) -> None:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
