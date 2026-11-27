const fields = ["price", "turnover", "market_cap", "date", "market_cap_date"];

export function sectorWeekStart(value) {
  const date = new Date(value);
  date.setUTCDate(date.getUTCDate() - (date.getUTCDay() + 6) % 7);
  return date.toISOString().slice(0, 10);
}

export function packSectorWeek(snapshots) {
  const profiles = new Map();
  const days = snapshots.map(({ stocks, ...header }, day) => {
    const order = stocks.map(stock => stock.ticker);
    if (new Set(order).size !== order.length) throw new Error(`Duplicate symbols on ${header.date}`);
    for (const stock of stocks) {
      const profile = { ...stock };
      let mask = 0;
      const changes = fields.map((key, index) => {
        if (!Object.hasOwn(stock, key)) return null;
        mask |= 1 << index;
        delete profile[key];
        return index >= 3 && stock[key] === header.date ? 1 : stock[key];
      });
      const id = JSON.stringify([profile, mask]);
      if (!profiles.has(id)) profiles.set(id, [profile, mask, []]);
      profiles.get(id)[2].push([day, ...changes]);
    }
    return order.some((ticker, index) => index > 0 && ticker < order[index - 1]) ? [header, order] : [header];
  });
  return { encoding: "sector-week-v1", days, profiles: [...profiles.values()] };
}

export function expandSectorWeek(value, date) {
  if (value?.encoding !== "sector-week-v1" || !Array.isArray(value.days) || !Array.isArray(value.profiles)) {
    throw new Error("주간 섹터 기록 형식이 올바르지 않습니다.");
  }
  const index = value.days.findIndex(day => Array.isArray(day) && day[0]?.date === date);
  if (index < 0) throw new Error("선택한 날짜의 섹터 기록이 없습니다.");
  const [header, order] = value.days[index];
  const members = new Map();
  for (const entry of value.profiles) {
    if (!Array.isArray(entry) || entry.length !== 3) throw new Error("주간 섹터 종목 형식이 올바르지 않습니다.");
    const [profile, mask, observations] = entry;
    if (typeof profile?.ticker !== "string" || !Number.isInteger(mask) || mask < 0 || mask >= 1 << fields.length || !Array.isArray(observations)) {
      throw new Error("주간 섹터 종목 형식이 올바르지 않습니다.");
    }
    const row = observations.find(item => Array.isArray(item) && item[0] === index);
    if (!row) continue;
    if (row.length !== fields.length + 1 || members.has(profile.ticker)) throw new Error("주간 섹터 가격 기록이 올바르지 않습니다.");
    const stock = { ...profile };
    for (const [position, key] of fields.entries()) {
      if (mask & (1 << position)) stock[key] = position >= 3 && row[position + 1] === 1 ? date : row[position + 1];
    }
    members.set(stock.ticker, stock);
  }
  const tickers = order ?? [...members.keys()].sort();
  if (!Array.isArray(tickers) || tickers.length !== members.size || new Set(tickers).size !== tickers.length || tickers.some(ticker => !members.has(ticker))) {
    throw new Error("주간 섹터 종목 순서가 올바르지 않습니다.");
  }
  return { ...header, stocks: tickers.map(ticker => members.get(ticker)) };
}
