
import json
import logging
import time
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import yfinance as yf
from pykrx import stock

# -------------------------
# 설정
# -------------------------

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT = BASE_DIR / "site" / "data" / "etfs.json"

KST = ZoneInfo("Asia/Seoul")
TODAY = datetime.now(KST).date()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

# -------------------------
# 날짜 및 데이터 처리
# -------------------------

def find_latest_trading_date():
    for offset in range(0, 11):
        day = TODAY - timedelta(days=offset)
        date_str = day.strftime("%Y%m%d")

        try:
            df = stock.get_etf_ohlcv_by_ticker(date_str)

            if df is not None and not df.empty:
                logging.info("가격 기준일: %s", date_str)
                return date_str, df

        except Exception as exc:
            logging.warning("가격 조회 실패 %s: %s", date_str, exc)

        time.sleep(0.3)

    raise RuntimeError("최근 ETF 가격 데이터를 찾지 못했습니다.")


def classify_category(name):
    if any(word in name for word in [
        "커버드콜", "위클리커버드콜"
    ]):
        return "커버드콜"

    if any(word in name for word in [
        "리츠", "부동산"
    ]):
        return "리츠"

    if any(word in name for word in [
        "채권", "국고채", "회사채", "통안채"
    ]):
        return "채권"

    return "기타"


# -------------------------
# ETF 분배금 수집
# -------------------------

def fetch_dividends(symbol):
    """
    Yahoo Finance의 국내 ETF 분배금 이력을 조회합니다.
    한국 ETF 티커는 일반적으로 6자리 코드 + .KS 형식입니다.

    분배금 날짜는 분배락일 기준으로 사용합니다.
    지급일과 동일하다고 가정하지 않습니다.
    """

    try:
        ticker = yf.Ticker(f"{symbol}.KS")

        history = ticker.history(
            period="5y",
            auto_adjust=False,
            actions=True
        )

        if history is None or history.empty:
            return []

        if "Dividends" not in history.columns:
            return []

        series = history["Dividends"]
        series = series[series > 0]

        events = []

        for date, amount in series.items():
            ex_date = date.strftime("%Y-%m-%d")

            events.append({
                "ex_date": ex_date,
                "amount": round(float(amount), 4)
            })

        return events

    except Exception as exc:
        logging.warning(
            "분배금 수집 실패 %s: %s",
            symbol, exc
        )
        return []


def process_fund(symbol, name, price):
    events = fetch_dividends(symbol)

    one_year_ago = TODAY - timedelta(days=365)

    recent_events = [
        e for e in events
        if datetime.strptime(
            e["ex_date"], "%Y-%m-%d"
        ).date() >= one_year_ago
    ]

    dividend_12m = sum(
        e["amount"] for e in recent_events
    )

    # 서로 다른 월의 분배 이력 수
    dividend_months = len({
        e["ex_date"][:7] for e in recent_events
    })

    is_monthly = dividend_months >= 8

    annual_yield = (
        dividend_12m / price * 100
        if price > 0 and dividend_12m > 0
        else None
    )

    return {
        "symbol": symbol,
        "name": name,
        "price": price,
        "dividend_12m": round(dividend_12m, 4),
        "annual_yield": (
            round(annual_yield, 4)
            if annual_yield is not None
            else None
        ),
        "monthly_dividend_avg": round(
            dividend_12m / 12, 4
        ),
        "is_monthly": is_monthly,
        "category": classify_category(name),
        "events": events,
        "event_count_12m": len(recent_events),
        "dividend_months_12m": dividend_months
    }


# -------------------------
# 메인 수집
# -------------------------

def main():
    logging.info("ETF 데이터 수집 시작")

    price_date, price_df = find_latest_trading_date()

    funds = []

    for symbol in stock.get_etf_ticker_list(price_date):
        try:
            name = stock.get_etf_ticker_name(symbol)

            if not name:
                continue

            if symbol not in price_df.index:
                continue

            price = int(price_df.loc[symbol, "종가"])

            if price <= 0:
                continue

            funds.append({
                "symbol": str(symbol),
                "name": str(name),
                "price": price
            })

        except Exception as exc:
            logging.warning(
                "ETF 기본정보 실패 %s: %s",
                symbol, exc
            )

    logging.info("수집 대상 ETF: %d개", len(funds))

    results = []

    # Yahoo Finance 요청은 동시 접속 수를 제한합니다.
    with ThreadPoolExecutor(max_workers=5) as executor:
        tasks = {
            executor.submit(
                process_fund,
                f["symbol"],
                f["name"],
                f["price"]
            ): f["symbol"]
            for f in funds
        }

        for future in as_completed(tasks):
            symbol = tasks[future]

            try:
                result = future.result()
                results.append(result)

            except Exception as exc:
                logging.error(
                    "처리 실패 %s: %s",
                    symbol, exc
                )

    results.sort(key=lambda x: x["name"])

    monthly_count = sum(
        1 for f in results if f["is_monthly"]
    )

    payload = {
        "updated_at": datetime.now(KST).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "price_date": datetime.strptime(
            price_date, "%Y%m%d"
        ).strftime("%Y-%m-%d"),
        "source": {
            "price": "KRX via pykrx",
            "dividend": "Yahoo Finance via yfinance"
        },
        "total_count": len(results),
        "monthly_count": monthly_count,
        "classification_rule": (
            "최근 12개월 중 분배 이력이 있는 월이 8개월 이상"
        ),
        "funds": results
    }

    OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temp_file = OUTPUT.with_suffix(".tmp")

    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(
            payload,
            file,
            ensure_ascii=False,
            indent=2
        )

    temp_file.replace(OUTPUT)

    logging.info("ETF 전체: %d", len(results))
    logging.info("월배당 ETF 후보: %d", monthly_count)
    logging.info("저장 완료: %s", OUTPUT)


if __name__ == "__main__":
    main()
