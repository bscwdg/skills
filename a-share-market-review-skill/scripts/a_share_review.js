const https = require('https');

const args = process.argv.slice(2);
const sessionIndex = args.indexOf('--session');
const requestedSession = sessionIndex >= 0 && args[sessionIndex + 1] ? args[sessionIndex + 1] : 'close';
const session = ['midday', 'close'].includes(requestedSession) ? requestedSession : null;

const INDEX_MAP = {
  '1.000001': { name: '上证指数', category: '大盘' },
  '0.399001': { name: '深证成指', category: '大盘' },
  '0.399006': { name: '创业板指', category: '大盘' },
  '1.000688': { name: '科创50', category: '大盘' },
  '1.000300': { name: '沪深300', category: '大盘' }
};

function requestJson(url) {
  return new Promise((resolve, reject) => {
    const req = https.get(
      url,
      {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
          Accept: 'application/json,text/plain,*/*'
        }
      },
      (res) => {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          res.resume();
          reject(new Error(`HTTP ${res.statusCode}`));
          return;
        }

        let body = '';
        res.on('data', (chunk) => {
          body += chunk;
        });
        res.on('end', () => {
          try {
            resolve(JSON.parse(body));
          } catch (error) {
            reject(error);
          }
        });
      }
    );

    req.setTimeout(10000, () => {
      req.destroy(new Error('request timeout'));
    });
    req.on('error', reject);
  });
}

function toNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

async function fetchIndices() {
  const secids = Object.keys(INDEX_MAP).join(',');
  const url = `https://push2.eastmoney.com/api/qt/ulist/get?fltt=2&fields=f12,f14,f2,f3,f4&secids=${secids}`;
  const json = await requestJson(url);
  const rows = json && json.data && Array.isArray(json.data.diff) ? json.data.diff : [];

  return rows
    .map((item) => {
      const key = Object.keys(INDEX_MAP).find((secid) => secid.endsWith(item.f12));
      const meta = key ? INDEX_MAP[key] : null;
      if (!meta) return null;
      return {
        ticker: item.f12,
        name: meta.name,
        category: meta.category,
        close: toNumber(item.f2),
        change_pct: toNumber(item.f3)
      };
    })
    .filter(Boolean);
}

async function fetchSectors() {
  const url = 'https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=40&po=1&np=1&fltt=2&fid=f3&fs=m:90+t:2&fields=f12,f14,f2,f3,f4';
  const json = await requestJson(url);
  const rows = json && json.data && Array.isArray(json.data.diff) ? json.data.diff : [];
  return rows
    .map((item) => ({
      ticker: item.f12,
      name: item.f14,
      category: '行业板块',
      close: toNumber(item.f2),
      change_pct: toNumber(item.f3)
    }))
    .filter((item) => item.name && Math.abs(item.change_pct) < 50)
    .sort((a, b) => b.change_pct - a.change_pct);
}

async function fetchBreadth() {
  const url = 'https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f104,f105,f106&secids=1.000001';
  const json = await requestJson(url);
  const row = json && json.data && Array.isArray(json.data.diff) ? json.data.diff[0] : null;

  return {
    advancing: row ? toNumber(row.f104) : 0,
    declining: row ? toNumber(row.f105) : 0,
    unchanged: row ? toNumber(row.f106) : 0,
    limit_up: null,
    limit_down: null
  };
}

function fail(message, error) {
  const detail = error && error.message ? `: ${error.message}` : '';
  console.error(`[a_share_review] ${message}${detail}`);
  process.exitCode = 1;
}

async function main() {
  if (!session) {
    fail(`无效 session：${requestedSession}，仅支持 midday 或 close`);
    return;
  }

  try {
    const [marketIndices, sectors, marketBreadth] = await Promise.all([
      fetchIndices(),
      fetchSectors(),
      fetchBreadth()
    ]);

    if (!marketIndices.length) {
      fail('实时指数数据为空，停止生成复盘');
      return;
    }

    if (!sectors.length) {
      fail('实时板块数据为空，停止生成复盘');
      return;
    }

    const result = {
      status: 'success',
      source: 'EastMoney A-share Market API',
      session,
      data_time: new Date().toISOString(),
      market_indices: marketIndices,
      strong_sectors: sectors.slice(0, 5),
      weak_sectors: sectors.slice(-5).reverse(),
      market_breadth: marketBreadth
    };

    console.log(JSON.stringify(result, null, 2));
  } catch (error) {
    fail('实时行情接口请求失败，停止生成复盘', error);
  }
}

main();
