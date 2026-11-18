import json
import logging

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pykrx import stock as krx_stock

from etf_common import fetch_etf_listing, safe_number


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT = BASE_DIR / "site" / "data" / "etf-price.json"
KST = ZoneInfo("Asia/Seoul")
NOW = datetime.now(KST)
TODAY = NOW.date()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)


def fetch_krx_etf_market_caps(date):
    """Fetch ETF market capitalization from the KRX all-items quote."""
    for offset in range(0, 8):
        query_date = date - timedelta(days=offset)
        try:
            frame = krx_stock.get_etf_ohlcv_by_ticker(query_date.strftime("%Y%m%d"))
            if frame is None or frame.empty or "시가총액" not in frame.columns:
                continue
            return {
                str(symbol).zfill(6): round(
                    safe_number(row["시가총액"]) / 100_000_000,
                    2
                )
                for symbol, row in frame.iterrows()
            }, query_date.strftime("%Y-%m-%d")
        except Exception as exc:
            logging.warning(
                "KRX ETF market-cap request failed (%s): %s",
                query_date,
                exc
            )
    return {}, None


def main():
    logging.info("ETF 가격 데이터 수집 시작")
    listing = fetch_etf_listing()
    krx_market_caps, krx_market_cap_date = fetch_krx_etf_market_caps(TODAY)
    logging.info(
        "KRX ETF market-cap snapshot: %d symbols (%s)",
        len(krx_market_caps),
        krx_market_cap_date or "fallback"
    )

    results = []
    for row in listing.to_dict("records"):
        symbol = str(row["Symbol"]).zfill(6)
        market_cap = krx_market_caps.get(symbol)
        if market_cap is None:
            market_cap = safe_number(row.get("MarCap", 0))
        price = safe_number(row["Price"])
        if price <= 0:
            continue
        results.append({
            "symbol": symbol,
            "name": str(row["Name"]),
            "price": int(price),
            "market_cap": round(market_cap, 2)
        })

    if not results:
        raise RuntimeError("수집된 ETF 가격 데이터가 없습니다.")

    results.sort(key=lambda item: item["name"])
    payload = {
        "updated_at": NOW.strftime("%Y-%m-%d %H:%M:%S"),
        "price_date": TODAY.strftime("%Y-%m-%d"),
        "price_date_note": "가격 조회일 기준. 실제 마지막 거래일과 차이가 있을 수 있음.",
        "source": {
            "listing": "FinanceDataReader / Naver Finance",
            "price": "FinanceDataReader / Naver Finance ETF listing",
            "market_cap": (
                "KRX ETF all-items quote (market cap in KRW 100M; date "
                + (krx_market_cap_date or "fallback")
                + ")"
            ),
        },
        "total_count": len(results),
        "funds": results,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp_file = OUTPUT.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    temp_file.replace(OUTPUT)
    logging.info("ETF 가격 데이터 저장 완료: %d개 (%s)", len(results), OUTPUT)


if __name__ == "__main__":
    main()
