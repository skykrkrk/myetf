// Cloudflare Worker: CORS 프록시 (API 키 불필요, 무료 플랜으로 충분)
// 사용법: Cloudflare 대시보드 → Workers & Pages → Create Worker → 이 코드 붙여넣고 Deploy
// 배포된 주소를 market-ticker.html 의 CONFIG.free.proxy 에 넣으세요.

const ALLOW_HOSTS = [
  "query1.finance.yahoo.com",
  "query2.finance.yahoo.com",
  "polling.finance.naver.com"
];

// 내 사이트에서만 쓰게 하려면 "*" 대신 "https://내도메인.com" 으로 바꾸세요.
const ALLOW_ORIGIN = "*";

export default {
  async fetch(request) {
    const target = new URL(request.url).searchParams.get("url");
    let u;
    try { u = new URL(target); } catch { return new Response("bad url", { status: 400 }); }
    if (u.protocol !== "https:" || !ALLOW_HOSTS.includes(u.hostname)) {
      return new Response("forbidden host", { status: 403 });
    }

    const upstream = await fetch(u.toString(), {
      headers: { "User-Agent": "Mozilla/5.0 (compatible; ticker-proxy)" },
      cf: { cacheTtl: 30, cacheEverything: true }   // 30초 캐시: 상대 서버에 부담을 줄임
    });

    const headers = new Headers(upstream.headers);
    headers.set("Access-Control-Allow-Origin", ALLOW_ORIGIN);
    headers.delete("set-cookie");
    return new Response(upstream.body, { status: upstream.status, headers });
  }
};
