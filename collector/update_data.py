import json
import logging

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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


def main():
    logging.info("ETF 가격 데이터 수집 시작")
    listing = fetch_etf_listing()
    if "MarCap" not in listing.columns:
        raise RuntimeError("ETF 목록에 시가총액 컬럼 MarCap이 없습니다.")

    results = []
    for row in listing.to_dict("records"):
        symbol = str(row["Symbol"]).zfill(6)
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
            "market_cap": "FinanceDataReader / Naver Finance ETF listing (KRW 100M)",
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
