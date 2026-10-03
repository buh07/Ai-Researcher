"""Validate the standalone Omnigent research coordinator bundle."""

from __future__ import annotations

from pathlib import Path

from omnigent.spec import load


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "agents" / "research-director"


def main() -> int:
    spec = load(BUNDLE)
    print(f"validated Omnigent agent bundle: {spec.name}")
    print(f"bundle path: {BUNDLE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

