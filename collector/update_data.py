
import json
import logging
import re
import time

from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser

import pandas as pd
import FinanceDataReader as fdr
import requests
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
SOURCE_TIMEOUT = 20

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


def classify_region(name):
    """ETF 명칭의 시장 단서를 바탕으로 투자 지역을 분류합니다."""
    name = str(name).upper()
    domestic_terms = [
        "국내", "코스피", "코스닥", "코스", "KOSPI", "KOSDAQ", "KRX", " 200",
        "삼성전자", "SK하이닉스", "현대차", "고배당주", "주주환원", "국고채",
        "통안채", "금융", "증권", "K고배당"
    ]
    overseas_terms = [
        "미국", "S&P", "NASDAQ", "나스닥", "다우", "글로벌", "월드", "차이나",
        "중국", "일본", "인도", "유럽", "독일", "베트남", "인도네시아", "브라질",
        "홍콩", "항셍", "니케이", "필라델피아", "해외", "선진국", "신흥국",
        "대만", "프랑스", "영국", "호주", "캐나다", "멕시코", "미국채"
    ]
    is_domestic = any(term in name for term in domestic_terms)
    is_overseas = any(term in name for term in overseas_terms)
    if is_domestic and is_overseas:
        return "혼합/미분류"
    if is_domestic:
        return "국내"
    if is_overseas:
        return "해외"
    return "혼합/미분류"


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

class SamsungProductLinkParser(HTMLParser):
    """공식 KODEX 검색 결과에서 종목코드가 일치하는 상품 ID를 찾습니다."""

    def __init__(self, symbol):
        super().__init__()
        self.symbol = symbol
        self.current_product_id = None
        self.current_text = []
        self.product_id = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href", "")
        match = re.search(r"/etf/product/view\.do\?id=([A-Za-z0-9]+)", href)
        if match:
            self.current_product_id = match.group(1)
            self.current_text = []

    def handle_data(self, data):
        if self.current_product_id:
            self.current_text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or not self.current_product_id:
            return
        text = "".join(self.current_text)
        if self.symbol in text:
            self.product_id = self.current_product_id
        self.current_product_id = None
        self.current_text = []


def parse_official_date(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")

    text = str(value).strip()
    match = re.search(r"(\d{2,4})[.年/-]\s*(\d{1,2})[.월/-]\s*(\d{1,2})", text)
    if not match:
        return None
    year, month, day = map(int, match.groups())
    if year < 100:
        year += 2000
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return None


def parse_official_amount(value):
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().replace(",", "").replace("원", "")
    if text in {"", "-", "–", "—"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fetch_kodex_distribution_records(symbol):
    """KODEX 공식 상품 이력 파일에서 기준일·실지급일·과세표준을 읽습니다."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; MonthlyDividendTracker/1.0)",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"
    })

    search_url = "https://www.samsungfund.com/etf/search.do"
    response = session.get(
        search_url,
        params={"searchText": symbol},
        timeout=SOURCE_TIMEOUT
    )
    response.raise_for_status()

    parser = SamsungProductLinkParser(symbol)
    parser.feed(response.text)
    if not parser.product_id:
        logging.info("KODEX 공식 상품 검색 결과 없음: %s", symbol)
        return []

    file_response = session.get(
        "https://www.samsungfund.com/excel-divid-list.do",
        params={"id": parser.product_id},
        timeout=SOURCE_TIMEOUT
    )
    file_response.raise_for_status()

    raw = pd.read_excel(BytesIO(file_response.content), header=None, engine="openpyxl")
    header_row = None
    for row_index in range(min(len(raw), 12)):
        labels = [str(value).replace(" ", "") for value in raw.iloc[row_index].tolist() if not pd.isna(value)]
        if any("지급기준일" in label for label in labels) and any("분배금액" in label for label in labels):
            header_row = row_index
            break
    if header_row is None:
        raise ValueError(f"KODEX 분배 이력 파일의 표 머리글을 찾지 못했습니다: {symbol}")

    headers = ["" if pd.isna(value) else str(value).replace(" ", "") for value in raw.iloc[header_row].tolist()]

    def find_column(*needles):
        for index, label in enumerate(headers):
            if any(needle in label for needle in needles):
                return index
        return None

    record_col = find_column("지급기준일")
    payment_col = find_column("실지급일", "지급일")
    amount_col = find_column("분배금액")
    tax_col = find_column("과세표준액", "과세표준")
    if record_col is None or amount_col is None:
        raise ValueError(f"KODEX 분배 이력 파일에 필수 열이 없습니다: {symbol}")

    records = []
    for values in raw.iloc[header_row + 1:].itertuples(index=False, name=None):
        record_date = parse_official_date(values[record_col] if record_col < len(values) else None)
        amount = parse_official_amount(values[amount_col] if amount_col < len(values) else None)
        if not record_date or amount is None:
            continue
        records.append({
            "record_date": record_date,
            "payment_date": parse_official_date(values[payment_col]) if payment_col is not None and payment_col < len(values) else None,
            "amount": amount,
            "tax_base": parse_official_amount(values[tax_col]) if tax_col is not None and tax_col < len(values) else None,
            "source": "삼성자산운용 KODEX 공식 분배금 현황"
        })
    return records


def enrich_kodex_events(symbol, events):
    try:
        records = fetch_kodex_distribution_records(symbol)
    except Exception as exc:
        logging.warning("KODEX 공식 분배 자료 조회 실패 %s: %s", symbol, exc)
        return 0

    unused_events = set(range(len(events)))
    enriched = 0
    for record in records:
        record_day = datetime.strptime(record["record_date"], "%Y-%m-%d").date()
        candidates = []
        for index in unused_events:
            event = events[index]
            try:
                ex_day = datetime.strptime(event["ex_date"], "%Y-%m-%d").date()
            except (KeyError, TypeError, ValueError):
                continue
            distance = abs((record_day - ex_day).days)
            if distance <= 7:
                amount_distance = abs(float(event.get("amount", 0)) - record["amount"])
                candidates.append((amount_distance, distance, index))

        if not candidates:
            continue

        _, _, index = min(candidates)
        events[index].update({
            "record_date": record["record_date"],
            "payment_date": record["payment_date"],
            "tax_base": record["tax_base"],
            "official_source": record["source"]
        })
        unused_events.remove(index)
        enriched += 1

    return enriched


ETF_CHECK_TAX_URLS = (
    "https://raw.githubusercontent.com/ttokjaeTV/montly-div/main/data/tax-base.json",
    "https://raw.githubusercontent.com/ttokjaeTV/montly-div/main/data/tax-base-extra.json",
)


def normalize_tax_month(value):
    """ETF CHECK 날짜(예: 2026/04/30)를 이벤트 월 키(2026-04)로 바꿉니다."""
    match = re.search(r"(20\d{2})\D?(\d{1,2})", str(value))
    if not match:
        return ""
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"


def normalize_tax_symbol(value):
    code = str(value or "").strip().upper()
    if len(code) == 6 and re.fullmatch(r"[A-Z0-9]{6}", code):
        return code
    if re.fullmatch(r"\d{1,5}", code):
        return code.zfill(6)
    return ""


def has_new_monthly_distribution_pattern(events, today):
    """1년 미만 이력에서도 최근 3개 분배월이 월 간격이면 월분배로 판정합니다."""
    dated_events = []
    for event in events:
        try:
            event_day = datetime.strptime(event["ex_date"], "%Y-%m-%d").date()
        except (KeyError, TypeError, ValueError):
            continue
        if event_day <= today:
            dated_events.append(event_day)

    if not dated_events:
        return False
    first_event = min(dated_events)
    if (today - first_event).days >= 365:
        return False

    month_dates = {}
    for event_day in sorted(dated_events):
        month_dates[event_day.strftime("%Y-%m")] = event_day
    recent_months = sorted(month_dates.values())[-3:]
    if len(recent_months) < 3:
        return False

    gaps = [(recent_months[index] - recent_months[index - 1]).days for index in range(1, 3)]
    return all(24 <= gap <= 40 for gap in gaps)


def fetch_etfcheck_tax_records():
    """ETF CHECK 과표 JSON에서 종목별 월 분배금·과표 자료를 가져옵니다."""
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; MonthlyDividendTracker/1.0)"})
    records = {}

    def walk(node, symbol=None):
        if isinstance(node, dict):
            code = normalize_tax_symbol(node.get("code", node.get("symbol", symbol or ""))) or symbol
            # ETF CHECK의 월별 레코드는 [연월, 분배금, 과표] 형태입니다.
            month = node.get("month", node.get("ym", node.get("date")))
            amount = node.get("amount", node.get("distribution"))
            tax = node.get("tax_base", node.get("tax", node.get("taxable_amount")))
            if code and month is not None and amount is not None and tax is not None:
                records.setdefault(code, []).append((normalize_tax_month(month), amount, tax))
            for key, value in node.items():
                child_symbol = normalize_tax_symbol(key) or code
                walk(value, child_symbol)
        elif isinstance(node, list):
            if symbol and len(node) >= 3 and not isinstance(node[0], (list, dict)):
                month = normalize_tax_month(node[0])
                records.setdefault(symbol, []).append((month, node[1], node[2]))
            else:
                for item in node:
                    walk(item, symbol)

    for url in ETF_CHECK_TAX_URLS:
        try:
            response = session.get(url, timeout=SOURCE_TIMEOUT)
            response.raise_for_status()
            walk(response.json())
        except Exception as exc:
            logging.warning("ETF CHECK 과표 자료 조회 실패 %s: %s", url, exc)
    logging.info("ETF CHECK 과표 레코드 파싱 완료: %d개 종목, %d건", len(records), sum(map(len, records.values())))
    return records


def enrich_etfcheck_events(symbol, events, tax_records):
    """월별 과표를 이벤트에 매칭하고 분배금 차이는 비례 보정합니다."""
    enriched = 0
    for event in events:
        month = event.get("ex_date", "")[:7]
        candidates = tax_records.get(normalize_tax_symbol(symbol), [])
        match = next((row for row in candidates if row[0] == month), None)
        if not match:
            continue
        source_amount = parse_official_amount(match[1])
        tax_base = parse_official_amount(match[2])
        if source_amount is None or tax_base is None:
            continue
        amount = float(event.get("amount", 0))
        if source_amount > 0 and abs(source_amount - amount) > 0.01:
            tax_base = round(tax_base * amount / source_amount)
        event.update({"tax_base": max(0, tax_base), "tax_base_source": "ETF CHECK"})
        enriched += 1
    return enriched

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

def process_fund(row, tax_records):

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
        and (
            dividend_months >= 8
            or has_new_monthly_distribution_pattern(events, TODAY)
        )
    )

    tax_event_count = enrich_etfcheck_events(symbol, events, tax_records)
    official_event_count = 0
    if is_monthly and name.upper().startswith("KODEX "):
        missing_tax_events = [event for event in events if event.get("tax_base") is None]
        official_event_count = enrich_kodex_events(symbol, missing_tax_events)
        tax_event_count += official_event_count

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

        "region": classify_region(name),

        "dividend_status": dividend_status,

        "event_count_12m": len(recent_events),

        "dividend_months_12m": dividend_months,

        "official_distribution_event_count": official_event_count,

        "tax_base_event_count": tax_event_count,

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

    tax_records = fetch_etfcheck_tax_records()
    logging.info("ETF CHECK 월별 과표 자료: %d개 종목", len(tax_records))

    rows = listing.to_dict("records")

    results = []

    # 2. 분배금 및 ETF 정보 조회
    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        tasks = {
            executor.submit(
                process_fund,
                row,
                tax_records
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
            "dividend": "Yahoo Finance",
            "distribution_details": "ETF CHECK monthly taxable base; KODEX official distribution history as fallback"
        },

        "total_count": len(results),

        "monthly_count": monthly_count,

        "dividend_available_count": available_count,

        "classification_rule": (
            "최근 12개월 분배월이 8개월 이상이거나, 상장 1년 미만이며 "
            "최근 3개 분배월 간격이 월 단위인 ETF"
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
