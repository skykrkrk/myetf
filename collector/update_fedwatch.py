"""Build a compact next-meeting probability chart from public ZQ futures prices.

The subscribed CME FedWatch REST API requires an API ID/OAuth token. For this
static Pages site, use Yahoo Finance's daily 30-Day Federal Funds futures
prices and the contract's monthly-average pricing methodology instead. This
is an independent estimate, not the licensed real-time FedWatch API output
or an official CME settlement.
"""

import csv
import json
import logging
import math
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "site" / "data" / "fedwatch.json"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
MONTH_CODES = "FGHJKMNQUVXZ"
SESSION = requests.Session()
SESSION.mount(
    "https://",
    HTTPAdapter(max_retries=Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )),
)
MEETINGS = [
    date(2026, 12, 9), date(2027, 1, 27), date(2027, 3, 17),
    date(2027, 4, 28), date(2027, 6, 9), date(2027, 7, 28),
    date(2027, 9, 15), date(2027, 10, 27), date(2027, 12, 8),
    date(2028, 1, 26),
]


def fetch_contract_prices(contract, end_day):
    year, month = contract
    symbol = f"ZQ{MONTH_CODES[month - 1]}{year % 100:02d}.CBT"
    start_day = end_day - timedelta(days=14)
    response = SESSION.get(
        YAHOO_CHART_URL.format(symbol=symbol),
        params={
            "period1": int(datetime.combine(start_day, datetime.min.time(), timezone.utc).timestamp()),
            "period2": int(datetime.combine(end_day + timedelta(days=1), datetime.min.time(), timezone.utc).timestamp()),
            "interval": "1d",
        },
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        timeout=25,
    )
    response.raise_for_status()
    payload = response.json()
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(f"Yahoo Finance returned an error for {symbol}: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise RuntimeError(f"Yahoo Finance returned no price history for {symbol}")
    result = results[0]
    timestamps = result.get("timestamp") or []
    quotes = (result.get("indicators", {}).get("quote") or [{}])[0]
    closes = quotes.get("close") or []
    prices = {}
    for timestamp, raw_close in zip(timestamps, closes):
        if raw_close is None:
            continue
        close = float(raw_close)
        if not math.isfinite(close):
            continue
        trade_day = datetime.fromtimestamp(int(timestamp), timezone.utc).date()
        if trade_day <= end_day:
            prices[trade_day] = close
    if not prices:
        raise RuntimeError(f"Yahoo Finance returned no usable prices for {symbol}")
    return prices


def latest_contract_prices(contracts, end_day):
    prices_by_contract = {
        contract: fetch_contract_prices(contract, end_day)
        for contract in contracts
    }
    common_days = set.intersection(*(set(prices) for prices in prices_by_contract.values()))
    if not common_days:
        raise RuntimeError("Yahoo Finance has no common recent date for the required ZQ contracts")
    trade_day = max(common_days)
    return trade_day, {
        contract: prices[trade_day]
        for contract, prices in prices_by_contract.items()
    }


def latest_fred_value(series_id):
    response = SESSION.get(
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


def previous_current_range():
    if not OUTPUT.exists():
        return None
    try:
        previous = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logging.warning("Unable to read the previous FedWatch snapshot: %s", exc)
        return None
    if not isinstance(previous, dict):
        return None
    values = previous.get("current_range")
    if not previous.get("available") or not isinstance(values, list) or len(values) != 2:
        return None
    try:
        current_range = [float(value) for value in values]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in current_range):
        return None
    return current_range, previous.get("current_range_fetched_at") or previous.get("generated_at")


def month_add(year, month, offset):
    value = year * 12 + month - 1 + offset
    return value // 12, value % 12 + 1


def build_data():
    now = date.today()
    meeting = next((item for item in MEETINGS if item >= now), None)
    if meeting is None:
        raise RuntimeError("No future FOMC meeting in the configured schedule")

    try:
        current_range = [latest_fred_value("DFEDTARL"), latest_fred_value("DFEDTARU")]
        current_range_fetched_at = datetime.now().astimezone().isoformat(timespec="minutes")
        current_range_stale = False
    except (requests.RequestException, RuntimeError) as exc:
        previous_range = previous_current_range()
        if previous_range is None:
            raise
        current_range, current_range_fetched_at = previous_range
        current_range_stale = True
        logging.warning("Using the previous target-rate range because FRED is unavailable: %s", exc)
    # ZQ prices 100 minus the average effective rate for the delivery
    # month. The nearest preceding month without an FOMC meeting anchors the
    # rate entering the next meeting month.
    meeting_months = {(item.year, item.month) for item in MEETINGS}
    anchor = None
    for offset in range(-1, -7, -1):
        year, month = month_add(meeting.year, meeting.month, offset)
        if (year, month) not in meeting_months:
            anchor = (year, month)
            break
    if anchor is None:
        raise RuntimeError("No preceding non-meeting ZQ contract is available as an anchor")
    trade_day, prices = latest_contract_prices(
        (anchor, (meeting.year, meeting.month)), now
    )

    start_rate = 100.0 - prices[anchor]
    average_rate = 100.0 - prices[(meeting.year, meeting.month)]
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
        "source": "Yahoo Finance daily 30-Day Federal Funds futures prices, methodology-based estimate",
        "trade_date": trade_day.isoformat(),
        "meeting_date": meeting.isoformat(),
        "current_range": current_range,
        "current_range_fetched_at": current_range_fetched_at,
        "current_range_stale": current_range_stale,
        "probabilities": outcomes,
        "generated_at": datetime.now().astimezone().isoformat(timespec="minutes"),
    }


def main():
    try:
        data = build_data()
        logging.info("Built ZQ futures-based FedWatch estimate for %s (trade date %s)", data["meeting_date"], data["trade_date"])
    except Exception as exc:
        logging.exception("Unable to build FedWatch chart data from Yahoo Finance")
        if OUTPUT.exists():
            try:
                previous = json.loads(OUTPUT.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                previous = {}
            if previous.get("available"):
                logging.warning("Keeping the previous FedWatch snapshot")
                return
        data = {"available": False, "error": str(exc), "generated_at": datetime.now().astimezone().isoformat(timespec="minutes")}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
