const $ = (id) => document.getElementById(id);
const money = (value) => Number.isFinite(Number(value))
  ? `${new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 }).format(Number(value))}원`
  : "—";
const number = (value) => new Intl.NumberFormat("ko-KR").format(Number(value) || 0);
const safe = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
}[char]));

let funds = [];
let visibleFunds = [];
let sortState = { key: "recentYield", direction: "desc" };

function latestEvent(fund) {
  return [...(fund.events || [])].sort((a, b) => String(b.ex_date).localeCompare(String(a.ex_date)))[0];
}

function getTaxBase(event) {
  return event?.tax_base ?? event?.tax_base_amount ?? event?.taxable_amount ?? event?.taxable_base ?? null;
}

function getTiming(fund) {
  const day = Number(latestEvent(fund)?.ex_date?.slice(-2));
  if (!day) return "unknown";
  return day <= 20 ? "mid" : "end";
}

function getCategory(fund) {
  if (fund.category && ["커버드콜", "리츠", "채권"].includes(fund.category)) return fund.category;
  const name = fund.name || "";
  if (/커버드콜|타겟커버드콜|프리미엄/.test(name)) return "커버드콜";
  if (/리츠|부동산/.test(name)) return "리츠";
  if (/채권|국고채|회사채|단기채/.test(name)) return "채권";
  return "기타";
}

function getRegion(fund) {
  if (["국내", "해외", "혼합/미분류"].includes(fund.region)) return fund.region;
  const name = fund.name || "";
  if (["TIGER 배당커버드콜액티브", "KODEX 반도체타겟위클리커버드콜"].some((term) => name.includes(term))) return "국내";
  const domestic = ["국내", "코리아", "코스피", "코스닥", "코스", "KOSPI", "KOSDAQ", "KRX", " 200", "삼성전자", "SK하이닉스", "현대차", "고배당주", "주주환원", "국고채", "통안채", "금융", "증권", "K고배당"];
  const overseas = ["미국", "S&P", "NASDAQ", "나스닥", "다우", "글로벌", "월드", "차이나", "중국", "일본", "인도", "유럽", "독일", "베트남", "인도네시아", "브라질", "홍콩", "항셍", "니케이", "필라델피아", "해외", "선진국", "신흥국", "대만", "프랑스", "영국", "호주", "캐나다", "멕시코", "미국채"];
  const hasDomestic = domestic.some((term) => name.toUpperCase().includes(term.toUpperCase()));
  const hasOverseas = overseas.some((term) => name.toUpperCase().includes(term.toUpperCase()));
  if (hasDomestic && hasOverseas) return "혼합/미분류";
  if (hasDomestic) return "국내";
  if (hasOverseas) return "해외";
  return "혼합/미분류";
}

function renderStats() {
  const monthly = funds.filter((fund) => fund.is_monthly);
  $("totalCount").textContent = number(funds.length);
  $("monthlyCount").textContent = number(monthly.length);
}

const FEAR_RATINGS = {
  "extreme fear": "극단적 공포",
  fear: "공포",
  neutral: "중립",
  greed: "탐욕",
  "extreme greed": "극단적 탐욕",
};

function fearRating(rating) {
  const key = String(rating || "").trim().toLowerCase();
  return FEAR_RATINGS[key] || key;
}

function fearSegmentIndex(score) {
  return Math.min(4, Math.floor(Math.max(0, Math.min(100, Number(score))) / 20));
}

function fearDelta(current, previous, label) {
  if (!Number.isFinite(Number(previous))) return "";
  const tone = ["efear", "fear", "neutral", "greed", "egreed"][fearSegmentIndex(previous)];
  const text = `${Math.round(Number(previous))}`;
  return `<div><span>${label}</span><b class="${tone}">${text}</b></div>`;
}

function renderFearGauge(data, gaugeId = "fearGauge", indexName = "CNN") {
  const gauge = $(gaugeId);
  const value = Math.max(0, Math.min(100, Number(data.score)));
  const centerX = 150;
  const centerY = 150;
  const radius = 112;
  const point = (angle, distance) => {
    const radians = angle * Math.PI / 180;
    return { x: centerX + Math.cos(radians) * distance, y: centerY - Math.sin(radians) * distance };
  };
  const arc = (start, end, distance = radius) => {
    const from = point(start, distance);
    const to = point(end, distance);
    return `M ${from.x.toFixed(1)} ${from.y.toFixed(1)} A ${distance} ${distance} 0 0 1 ${to.x.toFixed(1)} ${to.y.toFixed(1)}`;
  };
  const colors = ["#f27962", "#ed9c69", "#b8a27b", "#8eb98b", "#68b88e"];
  const activeIndex = fearSegmentIndex(value);
  const angle = 180 - value * 1.8;
  const needle = point(angle, 82);
  const ticks = Array.from({ length: 21 }, (_, index) => {
    const tickAngle = 180 - index * 9;
    const outer = point(tickAngle, 94);
    const inner = point(tickAngle, index % 5 === 0 ? 86 : 89);
    return `<line x1="${inner.x.toFixed(1)}" y1="${inner.y.toFixed(1)}" x2="${outer.x.toFixed(1)}" y2="${outer.y.toFixed(1)}" class="gauge-tick"/>`;
  }).join("");
  const arcs = colors.map((color, index) => {
    const start = 180 - index * 36 - 2;
    const end = 180 - (index + 1) * 36 + 2;
    return `<path d="${arc(start, end)}" class="gauge-segment${index === activeIndex ? " is-active" : ""}" style="--segment-color:${color}"/>`;
  }).join("");
  const ratingText = fearRating(data.rating);
  const displayScore = Math.round(value);
  const deltas = [
    fearDelta(value, data.previous_close, "전일"),
    fearDelta(value, data.previous_1_week, "1주"),
    fearDelta(value, data.previous_1_month, "1개월"),
  ].join("");
  gauge.innerHTML = `<svg viewBox="0 0 300 174" role="img" aria-label="${safe(indexName)} 공포와 탐욕 지수 ${displayScore}/100, ${safe(ratingText)}">
    ${arcs}${ticks}<line x1="150" y1="150" x2="${needle.x.toFixed(1)}" y2="${needle.y.toFixed(1)}" class="gauge-needle"/><circle cx="150" cy="150" r="6" class="gauge-hub"/>
    <text x="38" y="166" class="gauge-end-label" text-anchor="middle">0</text><text x="262" y="166" class="gauge-end-label" text-anchor="middle">100</text>
  </svg><div class="fear-value" style="--sentiment-color:${colors[activeIndex]}"><strong>${displayScore}</strong><span>${safe(ratingText || "최신 지수")}</span></div>${deltas ? `<div class="fear-deltas">${deltas}</div>` : ""}`;
}

async function loadFearAndGreed() {
  try {
    const response = await fetch("./data/feargreed.json", { cache: "no-store" });
    if (!response.ok) throw new Error("CNN 지수 자료를 불러오지 못했습니다.");
    const data = await response.json();
    if (!data.available || !Number.isFinite(Number(data.score))) throw new Error(data.error || "현재 표시할 CNN 지수가 없습니다.");
    renderFearGauge(data);
    const updated = data.timestamp ? new Date(data.timestamp) : null;
    $("fearUpdated").textContent = updated && !Number.isNaN(updated.valueOf())
      ? `업데이트 ${new Intl.DateTimeFormat("ko-KR", { timeZone: "America/New_York", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(updated)} ET`
      : "CNN 일간 지수";
  } catch (error) {
    console.warn("CNN Fear & Greed 지수를 불러오지 못했습니다.", error);
    $("fearGauge").innerHTML = '<span class="metric-unavailable">지수를 불러오지 못했습니다.<br><a href="https://edition.cnn.com/markets/fear-and-greed" target="_blank" rel="noopener noreferrer">CNN 사이트에서 확인 ↗</a></span>';
    $("fearUpdated").textContent = "자료 대기 중";
  }
}

async function loadKospiFearAndGreed() {
  try {
    const response = await fetch("./data/kfeargreed.json", { cache: "no-store" });
    if (!response.ok) throw new Error("KOSPI 지수 자료를 불러오지 못했습니다.");
    const data = await response.json();
    if (!data.available || !Number.isFinite(Number(data.score))) throw new Error(data.error || "현재 표시할 KOSPI 지수가 없습니다.");
    renderFearGauge(data, "kospiFearGauge", "KOSPI");
    const updated = data.updated ? new Date(`${data.updated}T00:00:00+09:00`) : null;
    $("kospiFearUpdated").textContent = updated && !Number.isNaN(updated.valueOf())
      ? `업데이트 ${new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "numeric", day: "numeric" }).format(updated)}`
      : "국내 시장 심리 지표";
  } catch (error) {
    console.warn("KOSPI Fear & Greed 지수를 불러오지 못했습니다.", error);
    $("kospiFearGauge").innerHTML = '<span class="metric-unavailable">지수를 불러오지 못했습니다.<br><a href="https://kospi.feargreedchart.com/api/?action=kospi" target="_blank" rel="noopener noreferrer">데이터 출처에서 확인 ↗</a></span>';
    $("kospiFearUpdated").textContent = "자료 대기 중";
  }
}

async function loadFedWatch() {
  const chart = $("fedwatchChart");
  if (!chart) return;
  try {
    const response = await fetch("./data/fedwatch.json", { cache: "no-store" });
    if (!response.ok) throw new Error("CME 확률 자료를 불러오지 못했습니다.");
    const data = await response.json();
    if (!data.available || !Array.isArray(data.probabilities) || !data.probabilities.length) {
      throw new Error(data.error || "현재 표시할 회의별 확률이 없습니다.");
    }
    const maximum = Math.max(...data.probabilities.map((item) => Number(item.probability)));
    const bars = data.probabilities.map((item) => `
      <div class="fedwatch-outcome ${safe(item.type)}">
        <div class="fedwatch-bar-label"><strong>${safe(item.range)}</strong><b>${Number(item.probability).toFixed(1)}%</b></div>
        <div class="fedwatch-bar-track"><span style="width:${Math.max(0, Math.min(100, Number(item.probability)))}%;${Number(item.probability) === maximum ? "" : "opacity:.72"}"></span></div>
      </div>`).join("");
    const currentRange = data.current_range.map((rate) => Number(rate).toFixed(2)).join("–");
    const asOf = new Intl.DateTimeFormat("ko-KR", { timeZone: "America/Chicago", month: "numeric", day: "numeric" }).format(new Date(`${data.trade_date}T12:00:00Z`));
    const staleRateNote = data.current_range_stale
      ? ` 기준금리 구간은 FRED 연결 문제로 이전 조회값${data.current_range_fetched_at ? ` (${safe(data.current_range_fetched_at)} 조회)` : ""}을 표시합니다.`
      : "";
    chart.innerHTML = `<div class="fedwatch-summary"><div><span>다음 FOMC 회의</span><strong>${safe(data.meeting_date)}</strong></div><div><span>현재 기준금리</span><strong>${currentRange}%</strong></div><div><span>선물 가격 기준일</span><strong>${safe(asOf)}</strong></div></div><div class="fedwatch-bars">${bars}</div><p class="fedwatch-note">Yahoo Finance의 30일 연방기금금리 선물 종가로 추정한 확률입니다. 공식 CME 결제값이나 CME FedWatch 실시간 수치와 다를 수 있습니다.${staleRateNote}</p>`;
  } catch (error) {
    console.warn("CME FedWatch 자료를 불러오지 못했습니다.", error);
    chart.innerHTML = `<span class="metric-unavailable">${safe(error.message)}<br><a href="https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool" target="_blank" rel="noopener noreferrer">CME FedWatch에서 확인 ↗</a></span>`;
  }
}

function renderTable() {
  const keyword = $("search").value.trim().toLocaleLowerCase("ko");
  const timing = $("timing").value;
  const category = $("category").value;
  const region = $("region").value;
  visibleFunds = funds.filter((fund) => {
    const matchesText = `${fund.name || ""} ${fund.symbol || ""}`.toLocaleLowerCase("ko").includes(keyword);
    return fund.is_monthly && matchesText &&
      (timing === "all" || getTiming(fund) === timing) &&
      (category === "all" || getCategory(fund) === category) &&
      (region === "all" || getRegion(fund) === region);
  });
  const getSortValue = (fund) => {
    const latest = latestEvent(fund);
    switch (sortState.key) {
      case "name": return fund.name || "";
      case "amount": return latest?.amount;
      case "taxBase": return getTaxBase(latest);
      case "taxRate": return getTaxBase(latest) != null && Number(latest?.amount) > 0
        ? Number(getTaxBase(latest)) / Number(latest.amount) * 100 : null;
      case "recentYield": return latest?.distribution_yield;
      case "annualYield": return fund.distribution_yield_12m;
      case "marketCap": return fund.market_cap;
      case "exDate": return latest?.ex_date;
      case "type": return `${getTiming(fund)} ${getCategory(fund)} ${getRegion(fund)}`;
      default: return null;
    }
  };
  visibleFunds.sort((a, b) => {
    const left = getSortValue(a);
    const right = getSortValue(b);
    if (left == null) return right == null ? 0 : 1;
    if (right == null) return -1;
    const comparison = typeof left === "string" || typeof right === "string"
      ? String(left).localeCompare(String(right), "ko", { numeric: true })
      : Number(left) - Number(right);
    return sortState.direction === "asc" ? comparison : -comparison;
  });
  updateSortIndicators();
  $("resultCount").textContent = `${number(visibleFunds.length)}개 종목`;
  const emptyData = $("emptyData");
  if (emptyData) emptyData.hidden = funds.length > 0;
  const tbody = getTableBody();
  if (!tbody) throw new Error("ETF 목록 표를 찾을 수 없습니다. 페이지를 새로고침해 주세요.");
  if (!visibleFunds.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="empty">${funds.length ? "검색 조건에 맞는 월배당 ETF가 없습니다." : "아직 ETF 데이터가 없습니다."}</td></tr>`;
    return;
  }
  tbody.innerHTML = visibleFunds.map((fund) => {
    const latest = latestEvent(fund);
    const timing = getTiming(fund);
    const taxable = getTaxBase(latest);
    const taxableRate = taxable != null && Number(latest?.amount) > 0
      ? (Number(taxable) / Number(latest.amount) * 100).toFixed(1)
      : null;
    return `<tr class="fund-row" data-symbol="${safe(fund.symbol)}" tabindex="0" aria-label="${safe(fund.name)} 상세 보기">
      <td><span class="fund-name">${safe(fund.name)}</span><span class="fund-code">${safe(fund.symbol)}</span></td>
      <td>${latest ? money(latest.amount) : "—"}</td>
      <td>${taxable == null ? "자료 없음" : money(taxable)}</td>
      <td>${taxableRate == null ? "\u2014" : `${taxableRate}%`}</td>
      <td>${latest?.distribution_yield == null ? "\u2014" : `${Number(latest.distribution_yield).toFixed(2)}%`}</td>
      <td class="yield-value">${(fund.distribution_yield_12m) == null ? "\u2014" : `${Number(fund.distribution_yield_12m).toFixed(2)}%`}</td>
      <td>${fund.market_cap == null ? "\u2014" : `${number(fund.market_cap)}\uC5B5\uC6D0`}</td>
      <td>${safe(latest?.ex_date || "자료 없음")}</td>
      <td><span class="timing-badge ${timing}">${timing === "mid" ? "월중" : timing === "end" ? "월말" : "시점 미확인"}</span><span class="type-badge">${safe(getCategory(fund))}</span><span class="region-badge ${getRegion(fund) === "국내" ? "domestic" : getRegion(fund) === "해외" ? "overseas" : "mixed"}">${safe(getRegion(fund) === "혼합/미분류" ? "혼합·미분류" : getRegion(fund))}</span></td>
    </tr>`;
  }).join("");
  tbody.querySelectorAll(".fund-row").forEach((row) => {
    row.addEventListener("click", () => showDetails(row.dataset.symbol));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); showDetails(row.dataset.symbol); }
    });
  });
}

function updateSortIndicators() {
  document.querySelectorAll(".sort-button").forEach((button) => {
    const active = button.dataset.sort === sortState.key;
    const th = button.closest("th");
    if (th) th.setAttribute("aria-sort", active ? (sortState.direction === "asc" ? "ascending" : "descending") : "none");
    button.classList.toggle("is-active", active);
    const arrow = button.querySelector(".sort-arrow");
    if (arrow) arrow.textContent = active && sortState.direction === "desc" ? "▼" : "▲";
    button.setAttribute("aria-label", `${button.querySelector("span")?.textContent || "열"}, ${active ? (sortState.direction === "asc" ? "오름차순" : "내림차순") : "오름차순으로 정렬"}`);
  });
}

function getTableBody() {
  const byId = $("etfTable");
  if (byId) return byId;
  const table = document.querySelector("#tbl");
  if (!table) return document.querySelector("table tbody");
  if (table.tagName.toLowerCase() === "tbody") return table;
  return table.tBodies[0] || table.createTBody();
}

function showDetails(symbol) {
  const fund = funds.find((item) => item.symbol === symbol);
  if (!fund) return;
  const events = [...(fund.events || [])].sort((a, b) => String(b.ex_date).localeCompare(String(a.ex_date)));
  const tradingViewUrl = `https://kr.tradingview.com/symbols/KRX-${encodeURIComponent(fund.symbol)}/`;
  const estimate = estimateDistribution(fund, 100000000);
  $("fundDetails").innerHTML = `
    <h2>${safe(fund.name)}</h2><p class="dialog-meta">${safe(fund.symbol)} · ${safe(getCategory(fund))}</p>
    <a class="tradingview-link" href="${tradingViewUrl}" target="_blank" rel="noopener noreferrer">Trading View에서 보기 <span aria-hidden="true">↗</span></a>
    <div class="detail-grid">
      <div class="detail-metric"><span>\uD604\uC7AC \uAC00\uACA9</span><strong>${money(fund.price)}</strong></div>
      <div class="detail-metric"><span>\uC2DC\uAC00\uCD1D\uC561</span><strong>${fund.market_cap == null ? "\u2014" : `${number(fund.market_cap)}\uC5B5\uC6D0`}</strong></div>
      <section class="detail-summary-card" aria-label="분배 정보">
        <h3>분배 정보</h3>
        <div><span>12\uAC1C\uC6D4 \uBD84\uBC30\uAE08</span><strong>${fund.dividend_12m == null ? "\u2014" : money(fund.dividend_12m)}</strong></div>
        <div><span>\uBD84\uBC30\uC728(\uCD5C\uADFC 1\uB144)</span><strong>${fund.distribution_yield_12m == null ? "\u2014" : `${Number(fund.distribution_yield_12m).toFixed(2)}%`}</strong></div>
        <div><span>\uBD84\uBC30 \uC6D4 \uC218</span><strong>${number(fund.dividend_months_12m || 0)}\uAC1C\uC6D4</strong></div>
      </section>
      <section class="detail-summary-card" aria-label="1억원 투자 예상 분배금">
        <h3>1억원 투자 시</h3>
        <div><span>매수 가능 수량</span><strong>${estimate ? `${number(estimate.shares)}주` : "—"}</strong></div>
        <div><span>월 예상 분배금</span><strong>${estimate ? money(estimate.annualIncome / 12) : "—"}</strong></div>
        <div><span>연 예상 분배금</span><strong>${estimate ? money(estimate.annualIncome) : "—"}</strong></div>
      </section>
    </div>
    <h3 class="history-title">최근 분배 내역</h3>
    <div class="history-list">${events.length ? events.slice(0, 18).map((event) => {
      const taxBase = getTaxBase(event);
      const taxRate = taxBase != null && Number(event.amount) > 0 ? `${(Number(taxBase) / Number(event.amount) * 100).toFixed(1)}%` : "\uC790\uB8CC \uC5C6\uC74C";
      const yieldText = event.distribution_yield == null ? "\uC790\uB8CC \uC5C6\uC74C" : `${Number(event.distribution_yield).toFixed(2)}%`;
      return `<div class="history-item"><span>${safe(event.ex_date)}<small>\uBC30\uB2F9\uB77D\uC77C</small></span><span>${money(event.amount)}<small>\uBD84\uBC30\uAE08</small></span><span>${taxBase == null ? "\uC790\uB8CC \uC5C6\uC74C" : money(taxBase)}<small>\uACFC\uD45C</small></span><span>${taxRate}<small>\uACFC\uD45C\uC728</small></span><span>${yieldText}<small>\uBD84\uBC30\uC728</small></span></div>`;
    }).join("") : '<p class="history-empty">확인할 수 있는 분배 이력이 없습니다.</p>'}</div>`;
  $("fundDialog").showModal();
}

function estimateDistribution(fund, investment) {
  if (!fund || !Number.isFinite(Number(fund.price)) || Number(fund.price) <= 0 ||
      fund.dividend_12m == null || !Number.isFinite(Number(fund.dividend_12m))) return null;
  const shares = Math.floor(investment / Number(fund.price));
  return { shares, annualIncome: shares * Number(fund.dividend_12m) };
}

function downloadCSV() {
  const headers = ["\uC885\uBAA9\uCF54\uB4DC", "\uC885\uBAA9\uBA85", "\uAC00\uACA9(\uC6D0)", "\uCD5C\uADFC \uBD84\uBC30\uAE08(\uC6D0)", "\uACFC\uD45C(\uC6D0)", "\uACFC\uD45C\uC728(%)", "\uCD5C\uADFC \uBD84\uBC30\uC728(%)", "\uBD84\uBC30\uC728(\uCD5C\uADFC 1\uB144)(%)", "\uC2DC\uAC00\uCD1D\uC561(\uC5B5\uC6D0)", "\uBC30\uB2F9\uB77D\uC77C", "\uC720\uD615"];
  const rows = visibleFunds.map((fund) => {
    const event = latestEvent(fund);
    const taxBase = getTaxBase(event) ?? "";
    const taxRate = taxBase !== "" && Number(event?.amount) > 0 ? (Number(taxBase) / Number(event.amount) * 100).toFixed(1) : "";
    const timing = getTiming(fund);
    return [fund.symbol, fund.name, fund.price, event?.amount ?? "", taxBase, taxRate, event?.distribution_yield ?? "", fund.distribution_yield_12m ?? "", fund.market_cap ?? "", event?.ex_date ?? "", `${timing === "mid" ? "\uC6D4\uC911" : timing === "end" ? "\uC6D4\uB9D0" : "\uBBF8\uD655\uC778"} \u00B7 ${getCategory(fund)} \u00B7 ${getRegion(fund)}`];
  });
  const csv = "\uFEFF" + [headers, ...rows].map((row) => row.map((value) => `"${String(value ?? "").replace(/"/g, '""')}"`).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "monthly-dividend-etf.csv";
  link.click();
  URL.revokeObjectURL(url);
}

async function loadData() {
  try {
    const response = await fetch("./data/etfs.json", { cache: "no-store" });
    if (!response.ok) throw new Error("ETF 데이터 파일을 불러오지 못했습니다.");
    const data = await response.json();
    funds = Array.isArray(data.funds) ? data.funds : [];
    $("updatedAt").textContent = data.updated_at ? `업데이트 ${data.updated_at}` : "데이터 업데이트 대기 중";
    if (data.source?.listing || data.source?.dividend || data.source?.distribution_details || data.source?.market_cap || data.source?.distribution_yield) {
      $("dataSource").textContent = `\uC790\uB8CC: ${[data.source.listing, data.source.dividend, data.source.distribution_details, data.source.market_cap, data.source.distribution_yield].filter(Boolean).join(" \u00B7 ")}`;
    }
    renderStats();
    renderTable();
  } catch (error) {
    console.error(error);
    const updatedAt = $("updatedAt");
    if (updatedAt) updatedAt.textContent = "데이터를 불러오지 못했습니다";
    const tbody = getTableBody();
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="9" class="empty">데이터를 표시하지 못했습니다: ${safe(error.message)}. 페이지를 새로고침해 주세요.</td></tr>`;
    } else {
      const main = document.querySelector("main") || document.body;
      const message = document.createElement("p");
      message.className = "empty";
      message.textContent = `데이터를 표시하지 못했습니다: ${error.message}`;
      main.prepend(message);
    }
  }
}

$("search").addEventListener("input", renderTable);
$("timing").addEventListener("change", renderTable);
$("category").addEventListener("change", renderTable);
$("region").addEventListener("change", renderTable);
document.querySelectorAll(".sort-button").forEach((button) => {
  button.addEventListener("click", () => {
    const key = button.dataset.sort;
    if (sortState.key === key) {
      sortState.direction = sortState.direction === "asc" ? "desc" : "asc";
    } else {
      sortState = { key, direction: "asc" };
    }
    renderTable();
  });
});
$("downloadCsv").addEventListener("click", downloadCSV);
$("fundDialog").addEventListener("click", (event) => {
  const dialog = $("fundDialog");
  const bounds = dialog.getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right ||
      event.clientY < bounds.top || event.clientY > bounds.bottom) {
    dialog.close();
  }
});
document.querySelectorAll(".accordion").forEach((button) => button.addEventListener("click", () => {
  const expanded = button.getAttribute("aria-expanded") === "true";
  button.setAttribute("aria-expanded", String(!expanded));
  $(button.getAttribute("aria-controls")).hidden = expanded;
  button.querySelector("em").textContent = expanded ? "＋" : "−";
}));

loadData();
loadFearAndGreed();
loadKospiFearAndGreed();
loadFedWatch();
