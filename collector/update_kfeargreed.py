"""Save a compact KOSPI Fear & Greed snapshot for the static site."""

import json
import logging
import math
from datetime import datetime
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "site" / "data" / "kfeargreed.json"
KOSPI_URL = "https://kospi.feargreedchart.com/api/?action=kospi"


def optional_number(values, key):
    value = values.get(key)
    if value is None:
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"KOSPI response has an invalid {key}")
    return round(result, 1)


def build_data():
    response = requests.get(KOSPI_URL, headers={"Accept": "application/json"}, timeout=25)
    response.raise_for_status()
    payload = response.json()
    score = float(payload["score"])
    if not math.isfinite(score) or not 0 <= score <= 100:
        raise ValueError("KOSPI response has an invalid score")
    history = payload.get("history") or {}
    return {
        "available": True,
        "score": round(score, 1),
        "rating": str(payload.get("label") or ""),
        "updated": str(payload.get("updated") or ""),
        "previous_close": optional_number(history, "prev_close"),
        "previous_1_week": optional_number(history, "week"),
        "previous_1_month": optional_number(history, "month"),
        "source": "KOSPI Fear & Greed Index",
        "generated_at": datetime.now().astimezone().isoformat(timespec="minutes"),
    }


def main():
    try:
        data = build_data()
        logging.info("Saved KOSPI Fear & Greed %.1f (%s)", data["score"], data["rating"])
    except Exception:
        logging.exception("Unable to refresh KOSPI Fear & Greed")
        if OUTPUT.exists():
            logging.warning("Keeping the previous KOSPI Fear & Greed snapshot")
            return
        data = {
            "available": False,
            "error": "Unable to fetch KOSPI Fear & Greed data",
            "generated_at": datetime.now().astimezone().isoformat(timespec="minutes"),
        }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
