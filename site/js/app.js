
const $ = (id) => document.getElementById(id);

const money = (value) =>
  new Intl.NumberFormat("ko-KR", {
    maximumFractionDigits: 0
  }).format(Number(value) || 0) + "원";

const number = (value) =>
  new Intl.NumberFormat("ko-KR").format(value || 0);

let funds = [];
let filteredFunds = [];

async function loadData() {
  try {
    const response = await fetch("./data/etfs.json", {
      cache: "no-store"
    });

    if (!response.ok) throw new Error("데이터 파일을 읽지 못했습니다.");

    const data = await response.json();
    funds = data.funds || [];

    $("updatedAt").textContent =
      "갱신 " + (data.updated_at || "정보 없음");

    $("priceDate").textContent = data.price_date || "-";

    renderStats();
    renderSelect();
    renderTable();
    renderCalendar();
    calculate();

  } catch (error) {
    console.error(error);
    $("etfTable").innerHTML =
      `<tr><td colspan="6" class="empty">
        데이터 로딩 실패: ${error.message}
      </td></tr>`;
  }
}

function renderStats() {
  const monthly = funds.filter(f => f.is_monthly);

  $("totalCount").textContent = number(funds.length);
  $("monthlyCount").textContent = number(monthly.length);

  const valid = monthly.filter(f => f.annual_yield != null);

  const average = valid.length
    ? valid.reduce((sum, f) => sum + f.annual_yield, 0)
      / valid.length
    : 0;

  $("avgYield").textContent =
    valid.length ? average.toFixed(2) + "%" : "-";
}

function renderSelect() {
  const select = $("calcEtf");

  select.innerHTML = '<option value="">ETF 선택</option>';

  funds
    .filter(f => f.price > 0)
    .sort((a, b) => a.name.localeCompare(b.name, "ko"))
    .forEach(f => {
      const option = document.createElement("option");
      option.value = f.symbol;
      option.textContent = `${f.name} (${f.symbol})`;
      select.appendChild(option);
    });
}

function getCategory(fund) {
  if (fund.is_monthly) return "월배당";
  if (fund.category === "커버드콜") return "커버드콜";
  if (fund.category === "리츠") return "리츠";
  return "기타";
}

function renderTable() {
  const keyword = $("search").value.trim().toLowerCase();
  const category = $("category").value;
  const sort = $("sort").value;

  filteredFunds = funds.filter(f => {
    const match =
      f.name.toLowerCase().includes(keyword) ||
      f.symbol.includes(keyword);

    const matchCategory =
      category === "all" ||
      getCategory(f) === category ||
      (category === "커버드콜" &&
        f.category === "커버드콜");

    return match && matchCategory;
  });

  filteredFunds.sort((a, b) => {
    if (sort === "yield")
      return (b.annual_yield || 0) - (a.annual_yield || 0);

    if (sort === "price")
      return (b.price || 0) - (a.price || 0);

    if (sort === "name")
      return a.name.localeCompare(b.name, "ko");

    if (sort === "dividend")
      return (b.dividend_12m || 0) - (a.dividend_12m || 0);

    return 0;
  });

  $("resultCount").textContent =
    `${filteredFunds.length}개 종목`;

  const tbody = $("etfTable");

  if (!filteredFunds.length) {
    tbody.innerHTML =
      '<tr><td colspan="6" class="empty">검색 결과가 없습니다.</td></tr>';
    return;
  }

  tbody.innerHTML = filteredFunds.map(f => `
    <tr>
      <td class="fund-name">${escapeHTML(f.name)}</td>
      <td class="fund-code">${escapeHTML(f.symbol)}</td>
      <td>${money(f.price)}</td>
      <td>
        ${f.dividend_12m == null
          ? "데이터 없음"
          : money(f.dividend_12m)}
      </td>
      <td class="yield-value">
        ${f.annual_yield == null
          ? "-"
          : f.annual_yield.toFixed(2) + "%"}
      </td>
      <td><span class="type-badge">${getCategory(f)}</span></td>
    </tr>
  `).join("");
}

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[char]);
}

function calculate() {
  const symbol = $("calcEtf").value;

  const investment = Math.max(
    0,
    Number($("investment").value) || 0
  );

  const fund = funds.find(
    f => f.symbol === symbol
  );

  if (
    !fund ||
    !fund.price ||
    fund.dividend_status !== "available" ||
    fund.dividend_12m == null
  ) {
    $("shares").textContent = "-";
    $("monthlyIncome").textContent = "-";
    $("annualIncome").textContent = "-";
    $("calcYield").textContent = "-";
    return;
  }

  const shares = Math.floor(
    investment / fund.price
  );

  const annual =
    shares * fund.dividend_12m;

  const monthly = annual / 12;

  $("shares").textContent =
    number(shares) + "주";

  $("monthlyIncome").textContent =
    money(monthly);

  $("annualIncome").textContent =
    money(annual);

  $("calcYield").textContent =
    fund.annual_yield == null
      ? "-"
      : fund.annual_yield.toFixed(2) + "%";
}

function renderCalendar() {
  const events = funds.flatMap(f =>
    (f.events || []).map(e => ({
      ...e,
      name: f.name,
      symbol: f.symbol
    }))
  );

  events.sort((a, b) => b.ex_date.localeCompare(a.ex_date));

  const recent = events.slice(0, 40);

  $("calendarList").innerHTML = recent.length
    ? recent.map(e => `
      <div class="calendar-item">
        <div>
          <strong>${escapeHTML(e.name)}</strong>
          <small>${escapeHTML(e.symbol)} · 분배 기준일</small>
          <small>1주당 ${money(e.amount)}</small>
        </div>
        <span class="calendar-date">${escapeHTML(e.ex_date)}</span>
      </div>
    `).join("")
    : '<p class="empty">확인 가능한 분배금 이력이 없습니다.</p>';
}

function downloadCSV() {
  const headers = [
    "종목코드",
    "종목명",
    "가격",
    "최근12개월분배금",
    "연환산분배율",
    "월배당여부"
  ];

  const rows = filteredFunds.map(f => [
    f.symbol,
    f.name,
    f.price,
    f.dividend_12m ?? "",
    f.annual_yield ?? "",
    f.is_monthly ? "Y" : "N"
  ]);

  const csv = "\uFEFF" + [headers, ...rows]
    .map(row => row.map(v =>
      `"${String(v ?? "").replace(/"/g, '""')}"`
    ).join(","))
    .join("\n");

  const blob = new Blob([csv], {
    type: "text/csv;charset=utf-8;"
  });

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = "monthly-dividend-etf.csv";
  link.click();

  URL.revokeObjectURL(url);
}

$("search").addEventListener("input", renderTable);
$("category").addEventListener("change", renderTable);
$("sort").addEventListener("change", renderTable);
$("calcEtf").addEventListener("change", calculate);
$("investment").addEventListener("input", calculate);
$("downloadCsv").addEventListener("click", downloadCSV);

loadData();
