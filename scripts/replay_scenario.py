#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def post(url: str, payload: dict, api_key: str) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Demo-Key": api_key},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", nargs="?", default="recall_peanut_01")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default="local-demo")
    args = parser.parse_args()
    path = ROOT / "scenarios" / f"{args.scenario}.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            result = post(f"{args.base_url}/api/events", json.loads(line), args.api_key)
            print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
