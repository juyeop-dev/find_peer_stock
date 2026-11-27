const fields = ["price", "turnover", "market_cap", "date", "market_cap_date"];

export function packSectorDay(snapshot, profileId) {
  const { stocks, ...header } = snapshot;
  const rows = stocks.map(stock => {
    const profile = { ...stock };
    let mask = 0;
    const values = fields.map((key, i) => {
      if (!Object.hasOwn(profile, key)) return null;
      mask |= 1 << i;
      delete profile[key];
      return i >= 3 && stock[key] === header.date ? null : stock[key] ?? false;
    });
    return [profileId([profile, mask]), ...values];
  });
  return { encoding: "sector-day-v1", header, rows };
}

export function expandSectorDay(value, dictionary) {
  if (value?.encoding !== "sector-day-v1" || dictionary?.encoding !== "sector-profiles-v1"
    || !Array.isArray(dictionary.keys) || !dictionary.keys.includes(value.key) || !Array.isArray(dictionary.profiles)
    || !value.header || !Array.isArray(value.rows)) throw new Error("날짜별 섹터 기록 형식이 올바르지 않습니다.");
  const {header, rows} = value;
  const stocks = rows.map(row => {
    const entry = Array.isArray(row) && row.length === fields.length + 1 && Number.isInteger(row[0]) && dictionary.profiles[row[0]];
    if (!entry || !Number.isInteger(entry[1])) throw new Error("섹터 종목 정보가 올바르지 않습니다.");
    const [profile, mask] = entry;
    const stock = { ...profile };
    fields.forEach((key, i) => {
      if (mask & (1 << i)) {
        const cell = row[i + 1];
        stock[key] = i >= 3 && cell === null ? header.date : cell === false ? null : cell;
      }
    });
    return stock;
  });
  return { ...header, stocks };
}
