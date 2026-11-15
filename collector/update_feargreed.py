"""Save a compact CNN Fear & Greed snapshot for the static site.

The public graph endpoint is about 180KB and includes history plus seven
components. The page only needs the current score and recent comparisons.
A failed fetch keeps the previous snapshot so a transient CNN block does not
blank the card.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "site" / "data" / "feargreed.json"
CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://edition.cnn.com/markets/fear-and-greed",
    "Origin": "https://edition.cnn.com",
}


def rounded(value):
    return round(float(value), 1)


def optional_number(current, key):
    value = current.get(key)
    if value is None:
        return None
    return rounded(value)


def build_data():
    response = requests.get(CNN_URL, headers=HEADERS, timeout=25)
    response.raise_for_status()
    current = response.json().get("fear_and_greed") or {}
    if current.get("score") is None:
        raise RuntimeError("CNN response has no fear_and_greed.score")
    return {
        "available": True,
        "score": rounded(current["score"]),
        "rating": str(current.get("rating") or ""),
        "timestamp": current.get("timestamp"),
        "previous_close": optional_number(current, "previous_close"),
        "previous_1_week": optional_number(current, "previous_1_week"),
        "previous_1_month": optional_number(current, "previous_1_month"),
        "source": "CNN Fear & Greed Index",
        "generated_at": datetime.now().astimezone().isoformat(timespec="minutes"),
    }


def main():
    try:
        data = build_data()
        logging.info("Saved CNN Fear & Greed %.1f (%s)", data["score"], data["rating"])
    except Exception as exc:
        logging.exception("Unable to refresh CNN Fear & Greed")
        if OUTPUT.exists():
            logging.warning("Keeping the previous Fear & Greed snapshot")
            return
        data = {
            "available": False,
            "error": str(exc),
            "generated_at": datetime.now().astimezone().isoformat(timespec="minutes"),
        }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
