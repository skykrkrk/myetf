"""Build a compact next-meeting probability chart from CME's public ZQ settlements.

The subscribed CME FedWatch REST API requires an API ID/OAuth token. For this
static Pages site, use CME's public 30-Day Federal Funds futures settlement
endpoint and CME's published monthly-average pricing methodology instead.
This is an independent, settlement-based estimate and is not the licensed
real-time FedWatch API output.
"""

import csv
import json
import logging
from datetime import date, datetime, timedelta
from io import StringIO
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "site" / "data" / "fedwatch.json"
CME_URL = "https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/305/FUT"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
MONTHS = {name: number for number, name in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1
)}
MONTH_CODES = "FGHJKMNQUVXZ"
MEETINGS = [
    date(2026, 12, 9), date(2027, 1, 27), date(2027, 3, 17),
    date(2027, 4, 28), date(2027, 6, 9), date(2027, 7, 28),
    date(2027, 9, 15), date(2027, 10, 27), date(2027, 12, 8),
    date(2028, 1, 26),
]


def fetch_settlements(trade_day):
    response = requests.get(
        CME_URL,
        params={"tradeDate": trade_day.strftime("%m/%d/%Y")},
        headers={"User-Agent": "Mozilla/5.0"}, timeout=25,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("empty") or not payload.get("settlements"):
        return None
    rows = {}
    for item in payload["settlements"]:
        month = str(item.get("month", "")).upper()
        if month == "TOTAL":
            continue
        try:
            settle = float(item["settle"])
            mon, year = month.split()
            rows[(2000 + int(year), MONTHS[mon])] = settle
        except (KeyError, TypeError, ValueError):
            continue
    return rows or None


def latest_settlements():
    day = date.today()
    for _ in range(10):
        if day.weekday() < 5:
            rows = fetch_settlements(day)
            if rows:
                return day, rows
        day -= timedelta(days=1)
    raise RuntimeError("CME did not return recent Fed Funds futures settlements")


def latest_fred_value(series_id):
    response = requests.get(
        FRED_URL,
        params={"id": series_id, "cosd": (date.today() - timedelta(days=35)).isoformat(), "coed": date.today().isoformat()},
        headers={"User-Agent": "Mozilla/5.0"}, timeout=25,
    )
    response.raise_for_status()
    rows = list(csv.DictReader(StringIO(response.text)))
    for row in reversed(rows):
        raw = row.get(series_id) or row.get("value")
        if raw and raw != ".":
            return float(raw)
    raise RuntimeError(f"FRED has no recent {series_id} value")


def month_add(year, month, offset):
    value = year * 12 + month - 1 + offset
    return value // 12, value % 12 + 1


def build_data():
    trade_day, settlements = latest_settlements()
    now = date.today()
    meeting = next((item for item in MEETINGS if item >= now), None)
    if meeting is None:
        raise RuntimeError("No future FOMC meeting in the configured schedule")

    current_range = [latest_fred_value("DFEDTARL"), latest_fred_value("DFEDTARU")]
    # CME ZQ prices 100 minus the average effective rate for the delivery
    # month. The nearest preceding month without an FOMC meeting anchors the
    # rate entering the next meeting month.
    meeting_months = {(item.year, item.month) for item in MEETINGS}
    anchor = None
    for offset in range(-1, -7, -1):
        year, month = month_add(meeting.year, meeting.month, offset)
        if (year, month) not in meeting_months and (year, month) in settlements:
            anchor = (year, month)
            break
    if anchor is None:
        raise RuntimeError("No preceding non-meeting CME contract is available as an anchor")
    meeting_settle = settlements.get((meeting.year, meeting.month))
    if meeting_settle is None:
        raise RuntimeError(f"CME has no settlement for {meeting:%b %Y}")

    start_rate = 100.0 - settlements[anchor]
    average_rate = 100.0 - meeting_settle
    days = (date(meeting.year + (meeting.month == 12), meeting.month % 12 + 1, 1) - timedelta(days=1)).day
    after_days = days - meeting.day
    if after_days <= 0:
        raise RuntimeError("Meeting date does not leave post-decision days in its month")
    end_rate = (days * average_rate - meeting.day * start_rate) / after_days
    moves = (end_rate - start_rate) / 0.25
    lower_moves = int(moves // 1)
    fraction = moves - lower_moves
    probability_by_move = {lower_moves: 1 - fraction, lower_moves + 1: fraction}

    lower_bps = round(current_range[0] * 100)
    outcomes = []
    for move, probability in sorted(probability_by_move.items()):
        if probability < 0.0005:
            continue
        outcome_lower = lower_bps + move * 25
        outcomes.append({
            "range": f"{outcome_lower / 100:.2f}%–{(outcome_lower + 25) / 100:.2f}%",
            "probability": round(probability * 100, 1),
            "move": move,
            "type": "cut" if move < 0 else "hold" if move == 0 else "hike",
        })
    return {
        "available": True,
        "source": "CME 30-Day Federal Funds Futures settlement (product 305), methodology-based estimate",
        "trade_date": trade_day.isoformat(),
        "meeting_date": meeting.isoformat(),
        "current_range": current_range,
        "probabilities": outcomes,
        "generated_at": datetime.now().astimezone().isoformat(timespec="minutes"),
    }


def main():
    try:
        data = build_data()
        logging.info("Built CME settlement-based FedWatch estimate for %s (trade date %s)", data["meeting_date"], data["trade_date"])
    except Exception as exc:
        logging.exception("Unable to build FedWatch chart data")
        data = {"available": False, "error": str(exc), "generated_at": datetime.now().astimezone().isoformat(timespec="minutes")}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
