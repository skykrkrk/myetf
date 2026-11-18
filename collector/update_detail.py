import json
import logging
import math
import re
import threading
import time
import xml.etree.ElementTree as ET

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from etf_common import (
    classify_category,
    classify_region,
    fetch_etf_listing,
)


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT = BASE_DIR / "site" / "data" / "etf-detail.json"
KST = ZoneInfo("Asia/Seoul")
NOW = datetime.now(KST)
TODAY = NOW.date()
MAX_WORKERS = 4
SOURCE_TIMEOUT = 20
NET_ASSET_UNIT_KRW = 100_000_000
SEIBRO_LOCAL = threading.local()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)


def convert_ticker_to_isin(ticker):
    ticker = str(ticker).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{6}", ticker):
        raise ValueError(f"유효하지 않은 ETF 종목코드: {ticker}")

    base = f"KR7{ticker}00"
    digits = "".join(
        str(int(char)) if char.isdigit() else str(ord(char) - 55)
        for char in base
    )
    total = 0
    for index, digit in enumerate(reversed(digits)):
        value = int(digit)
        if index % 2 == 0:
            value *= 2
        total += value // 10 + value % 10
    check_digit = (10 - total % 10) % 10
    return f"{base}{check_digit}"


def create_seibro_session():
    host = "seibro.or.kr"
    page_url = (
        f"https://{host}/websquare/control.jsp"
        "?w2xPath=/IPORTAL/user/fund/BIP_CNTS05011V.xml&menuNo=155"
    )
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": page_url,
        "Origin": f"https://{host}",
    })
    response = session.get(page_url, timeout=SOURCE_TIMEOUT)
    response.raise_for_status()
    return session


def fetch_seibro_records(session, isin, start_date, end_date):
    host = "seibro.or.kr"
    api_url = f"https://{host}/websquare/engine/proworks/callServletService.jsp"
    xml_payload = f"""<?xml version="1.0" encoding="UTF-8"?>
<reqParam action="fundCompstInfoStdprcDtramtPList" task="ksd.safe.bip.cnts.Fund.process.FundCompstInfoPTask">
    <MENU_NO value="155"/>
    <CMM_BTN_ABBR_NM value="total_search,openall,print,hwp,word,pdf,searchIcon,seach,favorites float_left,more2,more2,search02,search03,"/>
    <W2XPATH value="/IPORTAL/user/fund/BIP_CNTS05011V.xml"/>
    <ISIN value="{isin}"/>
    <IC_START value="{start_date}"/>
    <IC_END value="{end_date}"/>
    <FUND_ISIN value="{isin}"/>
    <PAGE_ON_CNT value="300"/>
    <PAGE_NUM value="1"/>
</reqParam>"""
    response = session.post(
        api_url,
        data=xml_payload.encode("utf-8"),
        headers={
            "Content-Type": "application/xml; charset=UTF-8",
            "Accept": "application/xml",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=SOURCE_TIMEOUT,
    )
    response.raise_for_status()

    root = ET.fromstring(response.content)
    rows = []
    for result in root.findall(".//data/result"):
        row = {
            child.tag: child.attrib.get("value", "")
            for child in result
        }
        if row:
            rows.append(row)
    return rows


def parse_number(value):
    if value is None:
        return None
    try:
        parsed = float(str(value).replace(",", "").strip())
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def build_distribution_events(records):
    dated_records = []
    for record in records:
        try:
            record_date = datetime.strptime(
                record.get("ANYTM_REPTG_DT", ""),
                "%Y%m%d"
            ).date()
        except (TypeError, ValueError):
            continue
        dated_records.append((record_date, record))

    dated_records.sort(key=lambda item: item[0])
    events = []
    previous_tax_standard = None

    for record_date, record in dated_records:
        current_tax_standard = parse_number(record.get("TAXSTD"))
        total_distribution = parse_number(record.get("TOT_DIV_PAY_AMT"))
        nav = parse_number(record.get("NAV_AMT"))
        net_assets = parse_number(record.get("FUND_NETASST_TOTAMT"))

        if total_distribution is not None and total_distribution > 0:
            amount = None
            if nav is not None and nav > 0 and net_assets is not None and net_assets > 0:
                units = net_assets * NET_ASSET_UNIT_KRW / nav
                if units > 0:
                    amount = total_distribution / units

            tax_base = None
            tax_rate = None
            if (
                previous_tax_standard is not None
                and previous_tax_standard > 0
                and current_tax_standard is not None
                and amount is not None
            ):
                taxable_difference = max(
                    0,
                    previous_tax_standard - current_tax_standard
                )
                tax_base = round(min(taxable_difference, amount), 4)
                tax_rate = round(tax_base / previous_tax_standard * 100, 4)

            events.append({
                "ex_date": record_date.strftime("%Y-%m-%d"),
                "amount": round(amount, 4) if amount is not None else None,
                "tax_base": tax_base,
                "tax_rate": tax_rate,
                "distribution_yield": (
                    round(amount / nav * 100, 4)
                    if amount is not None and nav is not None and nav > 0
                    else None
                ),
            })

        if current_tax_standard is not None:
            previous_tax_standard = current_tax_standard

    return events


def has_new_monthly_distribution_pattern(events):
    event_days = []
    for event in events:
        event_day = datetime.strptime(event["ex_date"], "%Y-%m-%d").date()
        if event_day <= TODAY:
            event_days.append(event_day)
    if not event_days or (TODAY - min(event_days)).days >= 365:
        return False

    month_dates = {}
    for event_day in sorted(event_days):
        month_dates[event_day.strftime("%Y-%m")] = event_day
    recent_months = sorted(month_dates.values())[-3:]
    if len(recent_months) < 3:
        return False

    gaps = [
        (recent_months[index] - recent_months[index - 1]).days
        for index in range(1, 3)
    ]
    return all(24 <= gap <= 40 for gap in gaps)


def build_fund(row, records):
    symbol = str(row["Symbol"]).zfill(6)
    name = str(row["Name"])
    events = build_distribution_events(records)
    one_year_ago = TODAY - timedelta(days=365)
    recent_events = [
        event for event in events
        if one_year_ago <= datetime.strptime(
            event["ex_date"], "%Y-%m-%d"
        ).date() <= TODAY
    ]
    recent_amounts = [
        event["amount"] for event in recent_events
        if event["amount"] is not None
    ]
    recent_yields = [
        event["distribution_yield"] for event in recent_events
        if event["distribution_yield"] is not None
    ]
    complete_amounts = bool(recent_events) and len(recent_amounts) == len(recent_events)
    complete_yields = bool(recent_events) and len(recent_yields) == len(recent_events)
    dividend_months = len({event["ex_date"][:7] for event in recent_events})
    is_monthly = (
        dividend_months >= 8
        or has_new_monthly_distribution_pattern(events)
    )

    return {
        "symbol": symbol,
        "name": name,
        "dividend_12m": round(sum(recent_amounts), 4) if complete_amounts else None,
        "annual_yield": round(sum(recent_yields), 4) if complete_yields else None,
        "distribution_yield_12m": round(sum(recent_yields), 4) if complete_yields else None,
        "yield_event_count_12m": len(recent_yields),
        "yield_event_count_attempted_12m": len(recent_events),
        "monthly_dividend_avg": (
            round(sum(recent_amounts) / 12, 4) if complete_amounts else None
        ),
        "is_monthly": is_monthly,
        "category": classify_category(name),
        "region": classify_region(name),
        "dividend_status": (
            "available" if any(event["amount"] is not None for event in events)
            else "unavailable"
        ),
        "event_count_12m": len(recent_events),
        "dividend_months_12m": dividend_months,
        "tax_base_event_count": sum(
            event["tax_base"] is not None for event in events
        ),
        "events": events,
    }


def fetch_fund_detail(row, start_date, end_date):
    session = getattr(SEIBRO_LOCAL, "session", None)
    if session is None:
        session = create_seibro_session()
        SEIBRO_LOCAL.session = session
    symbol = str(row["Symbol"]).zfill(6)
    try:
        records = fetch_seibro_records(
            session,
            convert_ticker_to_isin(symbol),
            start_date,
            end_date,
        )
    finally:
        time.sleep(0.25)
    return build_fund(row, records)


def main():
    logging.info("Seibro ETF 상세 데이터 수집 시작")
    listing = fetch_etf_listing()
    end_date = TODAY.strftime("%Y%m%d")
    start_date = (TODAY - timedelta(days=365)).strftime("%Y%m%d")
    rows = listing.to_dict("records")
    results = []
    failures = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        tasks = {
            executor.submit(fetch_fund_detail, row, start_date, end_date): row
            for row in rows
        }
        for future in as_completed(tasks):
            row = tasks[future]
            symbol = str(row["Symbol"]).zfill(6)
            try:
                result = future.result()
                results.append(result)
                logging.info("Seibro 수집 완료: %s %s", symbol, result["name"])
            except Exception as exc:
                failures += 1
                logging.warning("Seibro 수집 실패 %s: %s", symbol, exc)

    if not results or len(results) / len(rows) < 0.8:
        raise RuntimeError(
            f"Seibro 수집 성공률이 너무 낮습니다: "
            f"{len(results)}/{len(rows)}. 기존 상세 파일을 보존합니다."
        )

    results.sort(key=lambda item: item["name"])
    monthly_count = sum(item["is_monthly"] for item in results)
    available_count = sum(
        item["dividend_status"] == "available" for item in results
    )
    payload = {
        "updated_at": NOW.strftime("%Y-%m-%d %H:%M:%S"),
        "source": {
            "distribution_details": (
                "SEIBro fund standard price and distribution trend "
                "(per-unit distribution estimated from total payout / "
                "net assets and NAV)"
            ),
        },
        "total_count": len(results),
        "monthly_count": monthly_count,
        "dividend_available_count": available_count,
        "classification_rule": (
            "최근 12개월 분배월이 8개월 이상이거나, 상장 1년 미만이며 "
            "최근 3개 분배월 간격이 월 단위인 ETF"
        ),
        "funds": results,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp_file = OUTPUT.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    temp_file.replace(OUTPUT)

    logging.info(
        "Seibro 상세 데이터 저장 완료: %d개 종목, %d개 분배 이력 (%d건 실패)",
        len(results),
        sum(len(item["events"]) for item in results),
        failures,
    )


if __name__ == "__main__":
    main()
