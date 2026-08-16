#!/usr/bin/env python3
"""Render deployable Agent Cards with Cloud Run service URLs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recall-url", required=True)
    parser.add_argument("--supply-url", required=True)
    parser.add_argument("--finance-url", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    urls = {
        "recall-agent.json": args.recall_url,
        "supply-agent.json": args.supply_url,
        "finance-agent.json": args.finance_url,
    }
    for filename, base_url in urls.items():
        card = json.loads((ROOT / "agent_cards" / filename).read_text(encoding="utf-8"))
        card["url"] = f"{base_url.rstrip('/')}/a2a"
        (args.output / filename).write_text(
            json.dumps(card, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
