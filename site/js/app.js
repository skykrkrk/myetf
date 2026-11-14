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
  const domestic = ["국내", "코스피", "코스닥", "코스", "KOSPI", "KOSDAQ", "KRX", " 200", "삼성전자", "SK하이닉스", "현대차", "고배당주", "주주환원", "국고채", "통안채", "금융", "증권", "K고배당"];
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

function renderSelect() {
  const select = $("calcEtf");
  select.innerHTML = '<option value="">ETF를 선택하세요</option>';
  funds.filter((fund) => fund.price > 0 && fund.dividend_12m != null)
    .sort((a, b) => (a.name || "").localeCompare(b.name || "", "ko"))
    .forEach((fund) => {
      const option = document.createElement("option");
      option.value = fund.symbol;
      option.textContent = `${fund.name} (${fund.symbol})`;
      select.appendChild(option);
    });
}

function renderTable() {
  const keyword = $("search").value.trim().toLocaleLowerCase("ko");
  const timing = $("timing").value;
  const category = $("category").value;
  const region = $("region").value;
  const sort = $("sort").value;
  visibleFunds = funds.filter((fund) => {
    const matchesText = `${fund.name || ""} ${fund.symbol || ""}`.toLocaleLowerCase("ko").includes(keyword);
    return fund.is_monthly && matchesText &&
      (timing === "all" || getTiming(fund) === timing) &&
      (category === "all" || getCategory(fund) === category) &&
      (region === "all" || getRegion(fund) === region);
  });
  visibleFunds.sort((a, b) => {
    if (sort === "name") return (a.name || "").localeCompare(b.name || "", "ko");
    if (sort === "price") return (b.price || 0) - (a.price || 0);
    if (sort === "dividend") return (b.dividend_12m || 0) - (a.dividend_12m || 0);
    return (b.annual_yield || 0) - (a.annual_yield || 0);
  });
  $("resultCount").textContent = `${number(visibleFunds.length)}개 종목`;
  const emptyData = $("emptyData");
  if (emptyData) emptyData.hidden = funds.length > 0;
  const tbody = getTableBody();
  if (!tbody) throw new Error("ETF 목록 표를 찾을 수 없습니다. 페이지를 새로고침해 주세요.");
  if (!visibleFunds.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty">${funds.length ? "검색 조건에 맞는 월배당 ETF가 없습니다." : "아직 ETF 데이터가 없습니다."}</td></tr>`;
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
      <td>${taxableRate == null ? "—" : `${taxableRate}%`}</td>
      <td>${fund.dividend_12m == null ? "—" : money(fund.dividend_12m)}</td>
      <td class="yield-value">${fund.annual_yield == null ? "—" : `${Number(fund.annual_yield).toFixed(2)}%`}</td>
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
  $("fundDetails").innerHTML = `
    <h2>${safe(fund.name)}</h2><p class="dialog-meta">${safe(fund.symbol)} · ${safe(getCategory(fund))}</p>
    <a class="tradingview-link" href="${tradingViewUrl}" target="_blank" rel="noopener noreferrer">Trading View에서 보기 <span aria-hidden="true">↗</span></a>
    <div class="detail-grid">
      <div class="detail-metric"><span>현재 가격</span><strong>${money(fund.price)}</strong></div>
      <div class="detail-metric"><span>12개월 분배금</span><strong>${fund.dividend_12m == null ? "—" : money(fund.dividend_12m)}</strong></div>
      <div class="detail-metric"><span>연 분배율</span><strong>${fund.annual_yield == null ? "—" : `${Number(fund.annual_yield).toFixed(2)}%`}</strong></div>
      <div class="detail-metric"><span>분배 월 수</span><strong>${number(fund.dividend_months_12m || 0)}개월</strong></div>
    </div>
    <h3 class="history-title">최근 분배 내역</h3>
    <div class="history-list">${events.length ? events.slice(0, 18).map((event) => {
      const taxBase = getTaxBase(event);
      const taxRate = taxBase != null && Number(event.amount) > 0 ? `${(Number(taxBase) / Number(event.amount) * 100).toFixed(1)}%` : "자료 없음";
      return `<div class="history-item"><span>${safe(event.ex_date)}<small>배당락일</small></span><span>${money(event.amount)}<small>분배금</small></span><span>${taxBase == null ? "자료 없음" : money(taxBase)}<small>과표</small></span><span>${taxRate}<small>과표율</small></span></div>`;
    }).join("") : '<p class="history-empty">확인할 수 있는 분배 이력이 없습니다.</p>'}</div>`;
  $("fundDialog").showModal();
}

function calculate() {
  const fund = funds.find((item) => item.symbol === $("calcEtf").value);
  const investment = Math.max(0, Number($("investment").value) || 0);
  if (!fund || !fund.price || fund.dividend_12m == null) {
    ["shares", "monthlyIncome", "annualIncome", "calcYield"].forEach((id) => { $(id).textContent = "—"; });
    return;
  }
  const shares = Math.floor(investment / fund.price);
  const annualIncome = shares * Number(fund.dividend_12m);
  $("shares").textContent = `${number(shares)}주`;
  $("monthlyIncome").textContent = money(annualIncome / 12);
  $("annualIncome").textContent = money(annualIncome);
  $("calcYield").textContent = fund.annual_yield == null ? "—" : `${Number(fund.annual_yield).toFixed(2)}%`;
}

function downloadCSV() {
  const headers = ["종목코드", "종목명", "가격(원)", "최근 분배금(원)", "과표(원)", "과표율(%)", "최근 12개월 분배금(원)", "연 분배율(%)", "배당락일", "유형"];
  const rows = visibleFunds.map((fund) => {
    const event = latestEvent(fund);
    const taxBase = getTaxBase(event) ?? "";
    const taxRate = taxBase !== "" && Number(event?.amount) > 0 ? (Number(taxBase) / Number(event.amount) * 100).toFixed(1) : "";
    const timing = getTiming(fund);
    return [fund.symbol, fund.name, fund.price, event?.amount ?? "", taxBase, taxRate, fund.dividend_12m ?? "", fund.annual_yield ?? "", event?.ex_date ?? "", `${timing === "mid" ? "월중" : timing === "end" ? "월말" : "미확인"} · ${getCategory(fund)}`];
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
    $("updatedAt").textContent = data.updated_at ? `마지막 업데이트 ${data.updated_at}` : "데이터 업데이트 대기 중";
    $("priceDate").textContent = data.price_date || "—";
    if (data.source?.listing || data.source?.dividend || data.source?.distribution_details) {
      $("dataSource").textContent = `자료: ${[data.source.listing, data.source.dividend, data.source.distribution_details].filter(Boolean).join(" · ")}`;
    }
    renderStats();
    renderSelect();
    renderTable();
    calculate();
  } catch (error) {
    console.error(error);
    const updatedAt = $("updatedAt");
    if (updatedAt) updatedAt.textContent = "데이터를 불러오지 못했습니다";
    const tbody = getTableBody();
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="8" class="empty">데이터를 표시하지 못했습니다: ${safe(error.message)}. 페이지를 새로고침해 주세요.</td></tr>`;
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
$("sort").addEventListener("change", renderTable);
$("calcEtf").addEventListener("change", calculate);
$("investment").addEventListener("input", calculate);
$("downloadCsv").addEventListener("click", downloadCSV);
document.querySelectorAll(".accordion").forEach((button) => button.addEventListener("click", () => {
  const expanded = button.getAttribute("aria-expanded") === "true";
  button.setAttribute("aria-expanded", String(!expanded));
  $(button.getAttribute("aria-controls")).hidden = expanded;
  button.querySelector("em").textContent = expanded ? "＋" : "−";
}));

loadData();
