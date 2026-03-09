const KAKAO_API_KEY = "ee3375b0678c5293ac9d180f13e2bbbe";
const KAKAO_BASE = "https://dapi.kakao.com/v2/local";

exports.handler = async (event) => {
  const params = Object.assign({}, event.queryStringParameters || {});
  const type = params.type || "api";
  delete params.type;

  const headers = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
  };

  try {
    if (type === "place") {
      const placeId = params.id;
      if (!placeId) {
        return { statusCode: 400, headers, body: JSON.stringify({ error: "id required" }) };
      }
      const resp = await fetch(`https://place.map.kakao.com/${placeId}`, {
        headers: {
          "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        },
      });
      const html = await resp.text();
      const match = html.match(/<meta\s+property="og:description"\s+content="([^"]+)"/);
      return {
        statusCode: 200,
        headers,
        body: JSON.stringify({ description: match ? match[1] : "" }),
      };
    }

    // API proxy
    const endpoint = params.endpoint;
    delete params.endpoint;

    if (!endpoint) {
      return { statusCode: 400, headers, body: JSON.stringify({ error: "endpoint required" }) };
    }

    const url = new URL(`${KAKAO_BASE}/${endpoint}`);
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));

    const resp = await fetch(url.toString(), {
      headers: { Authorization: `KakaoAK ${KAKAO_API_KEY}` },
    });
    const data = await resp.json();

    return { statusCode: 200, headers, body: JSON.stringify(data) };
  } catch (err) {
    return {
      statusCode: 500,
      headers,
      body: JSON.stringify({ error: err.message }),
    };
  }
};
