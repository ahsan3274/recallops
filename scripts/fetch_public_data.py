#!/usr/bin/env python3
"""Fetch compact public-data snapshots for build-time enrichment.

This script is deliberately not part of the runtime. Review source terms,
store credentials outside the repository, and add provenance/checksums before
committing any processed snapshot.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"


def fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "RecallOps-Hackathon/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.load(response)


def fetch_usda(query: str, limit: int) -> list[dict[str, Any]]:
    key = os.environ.get("USDA_API_KEY")
    if not key:
        raise RuntimeError("Set USDA_API_KEY before fetching FoodData Central")
    params = urllib.parse.urlencode(
        {"api_key": key, "query": query, "dataType": "Branded", "pageSize": limit}
    )
    data = fetch_json(f"https://api.nal.usda.gov/fdc/v1/foods/search?{params}")
    return data.get("foods", [])


def fetch_openfda(limit: int) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": min(limit, 1000)}
    key = os.environ.get("OPENFDA_API_KEY")
    if key:
        params["api_key"] = key
    data = fetch_json(
        "https://api.fda.gov/food/enforcement.json?" + urllib.parse.urlencode(params)
    )
    return data.get("results", [])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-query", default="peanut butter")
    parser.add_argument("--product-limit", type=int, default=50)
    parser.add_argument("--recall-limit", type=int, default=50)
    args = parser.parse_args()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    products = fetch_usda(args.product_query, args.product_limit)
    recalls = fetch_openfda(args.recall_limit)
    (RAW_DIR / "usda_products.json").write_text(json.dumps(products, indent=2), encoding="utf-8")
    (RAW_DIR / "openfda_recalls.json").write_text(json.dumps(recalls, indent=2), encoding="utf-8")
    print(f"Fetched {len(products)} USDA products and {len(recalls)} openFDA recalls")


if __name__ == "__main__":
    main()
