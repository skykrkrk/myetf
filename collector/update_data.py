
import json
import logging
import time

from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import FinanceDataReader as fdr
import yfinance as yf


# =====================================
# 기본 설정
# =====================================

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT = BASE_DIR / "site" / "data" / "etfs.json"

KST = ZoneInfo("Asia/Seoul")
NOW = datetime.now(KST)
TODAY = NOW.date()

MAX_WORKERS = 4
RETRY_COUNT = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)


# =====================================
# 공통 함수
# =====================================

def safe_number(value):
    try:
        if pd.isna(value):
            return 0
        return float(value)
    except (ValueError, TypeError):
        return 0


def classify_category(name):
    name = str(name)

    if any(x in name for x in [
        "커버드콜",
        "위클리커버드콜",
        "타겟커버드콜"
    ]):
        return "커버드콜"

    if any(x in name for x in [
        "리츠",
        "부동산"
    ]):
        return "리츠"

    if any(x in name for x in [
        "채권",
        "국고채",
        "회사채",
        "통안채"
    ]):
        return "채권"

    return "기타"


def fetch_etf_listing():
    """
    FinanceDataReader를 통해
    국내 ETF 전체 목록을 가져옵니다.

    내부적으로 네이버 금융 ETF 목록 사용.
    KRX 로그인 불필요.
    """

    for attempt in range(1, RETRY_COUNT + 1):
        try:
            logging.info(
                "ETF 목록 조회 (%d/%d)",
                attempt,
                RETRY_COUNT
            )

            df = fdr.StockListing("ETF/KR")

            if df is None or df.empty:
                raise RuntimeError("ETF 목록이 비어 있습니다.")

            required = ["Symbol", "Name", "Price"]

            missing = [
                col for col in required
                if col not in df.columns
            ]

            if missing:
                raise RuntimeError(
                    f"필수 컬럼 누락: {missing}"
                )

            df = df.copy()

            df["Symbol"] = (
                df["Symbol"]
                .astype(str)
                .str.zfill(6)
            )

            df["Price"] = pd.to_numeric(
                df["Price"],
                errors="coerce"
            )

            df = df.dropna(subset=["Price"])
            df = df[df["Price"] > 0]

            df = df.drop_duplicates(
                subset=["Symbol"]
            )

            logging.info(
                "ETF 목록 조회 성공: %d개",
                len(df)
            )

            return df

        except Exception as exc:
            logging.warning(
                "ETF 목록 조회 실패: %s",
                exc
            )

            if attempt < RETRY_COUNT:
                time.sleep(attempt * 5)

    raise RuntimeError(
        "국내 ETF 목록을 가져오지 못했습니다."
    )


# =====================================
# 분배금 수집
# =====================================

def fetch_dividends(symbol):
    """
    Yahoo Finance의 국내 ETF 분배금 이력 조회.

    데이터가 없으면 빈 목록 반환.
    빈 목록은 분배금 0원이라는 의미가 아닙니다.
    """

    for attempt in range(1, RETRY_COUNT + 1):

        try:
            ticker = yf.Ticker(f"{symbol}.KS")

            dividends = ticker.dividends

            if dividends is None or dividends.empty:
                return {
                    "events": [],
                    "status": "unavailable"
                }

            events = []

            for date, amount in dividends.items():

                amount = safe_number(amount)

                if amount <= 0:
                    continue

                event_date = pd.Timestamp(date)

                if event_date.tzinfo is not None:
                    event_date = event_date.tz_localize(None)

                events.append({
                    "ex_date": event_date.strftime("%Y-%m-%d"),
                    "amount": round(amount, 4)
                })

            events.sort(
                key=lambda x: x["ex_date"]
            )

            return {
                "events": events,
                "status": (
                    "available" if events
                    else "unavailable"
                )
            }

        except Exception as exc:

            logging.warning(
                "%s 분배금 조회 실패 (%d/%d): %s",
                symbol,
                attempt,
                RETRY_COUNT,
                exc
            )

            if attempt < RETRY_COUNT:
                time.sleep(attempt * 3)

    return {
        "events": [],
        "status": "unavailable"
    }


# =====================================
# ETF 데이터 계산
# =====================================

def process_fund(row):

    symbol = str(row["Symbol"]).zfill(6)
    name = str(row["Name"])

    price = safe_number(row["Price"])

    market_cap = safe_number(
        row.get("MarCap", 0)
    )

    dividend_data = fetch_dividends(symbol)

    events = dividend_data["events"]

    one_year_ago = TODAY - timedelta(days=365)

    recent_events = [
        event for event in events
        if datetime.strptime(
            event["ex_date"],
            "%Y-%m-%d"
        ).date() >= one_year_ago
        and datetime.strptime(
            event["ex_date"],
            "%Y-%m-%d"
        ).date() <= TODAY
    ]

    # 실제로 조회된 분배금 이력만 합산
    dividend_12m = sum(
        event["amount"]
        for event in recent_events
    )

    dividend_months = len({
        event["ex_date"][:7]
        for event in recent_events
    })

    dividend_status = dividend_data["status"]

    is_monthly = (
        dividend_status == "available"
        and dividend_months >= 8
    )

    annual_yield = None

    if price > 0 and dividend_status == "available":
        annual_yield = round(
            dividend_12m / price * 100,
            4
        )

    return {
        "symbol": symbol,
        "name": name,
        "price": int(price),

        "market_cap": int(market_cap),

        "dividend_12m": (
            round(dividend_12m, 4)
            if dividend_status == "available"
            else None
        ),

        "annual_yield": annual_yield,

        "monthly_dividend_avg": (
            round(dividend_12m / 12, 4)
            if dividend_status == "available"
            else None
        ),

        "is_monthly": is_monthly,

        "category": classify_category(name),

        "dividend_status": dividend_status,

        "event_count_12m": len(recent_events),

        "dividend_months_12m": dividend_months,

        "events": events
    }


# =====================================
# 메인 실행
# =====================================

def main():

    logging.info("=" * 50)
    logging.info("ETF 데이터 수집 시작")
    logging.info("=" * 50)

    # 1. ETF 목록 조회
    listing = fetch_etf_listing()

    rows = listing.to_dict("records")

    results = []

    # 2. 분배금 및 ETF 정보 조회
    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        tasks = {
            executor.submit(
                process_fund,
                row
            ): row["Symbol"]
            for row in rows
        }

        for future in as_completed(tasks):

            symbol = tasks[future]

            try:
                result = future.result()
                results.append(result)

                logging.info(
                    "수집 완료: %s %s",
                    symbol,
                    result["name"]
                )

            except Exception as exc:

                logging.error(
                    "ETF 처리 실패 %s: %s",
                    symbol,
                    exc
                )

    # 가격 데이터가 유효한 ETF만 보존
    results = [
        item for item in results
        if item["price"] > 0
    ]

    if not results:
        raise RuntimeError(
            "수집된 ETF 데이터가 없습니다."
        )

    # 목록 수집 대비 처리 성공률 확인
    success_ratio = len(results) / len(rows)

    if success_ratio < 0.8:
        raise RuntimeError(
            f"ETF 처리 성공률이 너무 낮습니다: "
            f"{success_ratio:.1%}. "
            "기존 데이터를 보존합니다."
        )

    results.sort(
        key=lambda x: x["name"]
    )

    monthly_count = sum(
        1 for item in results
        if item["is_monthly"]
    )

    available_count = sum(
        1 for item in results
        if item["dividend_status"] == "available"
    )

    # 3. JSON 생성
    payload = {
        "updated_at": NOW.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),

        "price_date": TODAY.strftime(
            "%Y-%m-%d"
        ),

        "price_date_note": (
            "가격 조회일 기준. "
            "실제 마지막 거래일과 차이가 있을 수 있음."
        ),

        "source": {
            "listing": "FinanceDataReader / Naver Finance",
            "price": "Naver Finance ETF listing",
            "dividend": "Yahoo Finance"
        },

        "total_count": len(results),

        "monthly_count": monthly_count,

        "dividend_available_count": available_count,

        "classification_rule": (
            "최근 12개월 동안 분배 이력이 있는 "
            "월이 8개월 이상인 ETF"
        ),

        "funds": results
    }

    # 4. 파일 안전 저장
    OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temp_file = OUTPUT.with_suffix(".tmp")

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            payload,
            file,
            ensure_ascii=False,
            indent=2
        )

    temp_file.replace(OUTPUT)

    logging.info("=" * 50)
    logging.info("전체 ETF: %d", len(results))
    logging.info("월배당 ETF 후보: %d", monthly_count)
    logging.info("분배금 조회 성공: %d", available_count)
    logging.info("분배금 조회 미확인: %d",
                 len(results) - available_count)
    logging.info("저장 완료: %s", OUTPUT)
    logging.info("=" * 50)


if __name__ == "__main__":
    main()
