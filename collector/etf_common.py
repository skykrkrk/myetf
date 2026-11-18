import logging
import time

import pandas as pd
import FinanceDataReader as fdr


RETRY_COUNT = 3


def safe_number(value):
    try:
        if pd.isna(value):
            return 0
        return float(value)
    except (ValueError, TypeError):
        return 0


def classify_category(name):
    name = str(name)
    if any(term in name for term in [
        "커버드콜",
        "위클리커버드콜",
        "타겟커버드콜",
    ]):
        return "커버드콜"
    if any(term in name for term in ["리츠", "부동산"]):
        return "리츠"
    if any(term in name for term in [
        "채권",
        "국고채",
        "회사채",
        "통안채",
    ]):
        return "채권"
    return "기타"


def classify_region(name):
    """Classify an ETF's investment region using clues in its name."""
    name = str(name).upper()
    domestic_overrides = [
        "TIGER 배당커버드콜액티브",
        "KODEX 반도체타겟위클리커버드콜",
    ]
    if any(term in name for term in domestic_overrides):
        return "국내"
    domestic_terms = [
        "국내", "코리아", "코스피", "코스닥", "코스", "KOSPI", "KOSDAQ", "KRX", " 200",
        "삼성전자", "SK하이닉스", "현대차", "고배당주", "주주환원", "국고채",
        "통안채", "금융", "증권", "K고배당",
    ]
    overseas_terms = [
        "미국", "S&P", "NASDAQ", "나스닥", "다우", "글로벌", "월드", "차이나",
        "중국", "일본", "인도", "유럽", "독일", "베트남", "인도네시아", "브라질",
        "홍콩", "항셍", "니케이", "필라델피아", "해외", "선진국", "신흥국",
        "대만", "프랑스", "영국", "호주", "캐나다", "멕시코", "미국채",
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
    """Fetch the domestic ETF listing from FinanceDataReader."""
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            logging.info("ETF 목록 조회 (%d/%d)", attempt, RETRY_COUNT)
            frame = fdr.StockListing("ETF/KR")
            if frame is None or frame.empty:
                raise RuntimeError("ETF 목록이 비어 있습니다.")

            required = ["Symbol", "Name", "Price"]
            missing = [column for column in required if column not in frame.columns]
            if missing:
                raise RuntimeError(f"필수 컬럼 누락: {missing}")

            frame = frame.copy()
            frame["Symbol"] = frame["Symbol"].astype(str).str.zfill(6)
            frame["Price"] = pd.to_numeric(frame["Price"], errors="coerce")
            frame = frame.dropna(subset=["Price"])
            frame = frame[frame["Price"] > 0]
            frame = frame.drop_duplicates(subset=["Symbol"])

            logging.info("ETF 목록 조회 성공: %d개", len(frame))
            return frame
        except Exception as exc:
            logging.warning("ETF 목록 조회 실패: %s", exc)
            if attempt < RETRY_COUNT:
                time.sleep(attempt * 5)

    raise RuntimeError("국내 ETF 목록을 가져오지 못했습니다.")
