const DAY = 86400000;
const MIN_DAY = Date.parse("0001-01-01T00:00:00Z") / DAY;
const MAX_DAY = Date.parse("9999-12-31T00:00:00Z") / DAY;

/** Restore stored observations exactly; gaps remain gaps, never interpolated. */
export function expandPriceArchive(value: unknown): unknown {
  const root = value as Record<string, unknown> | null;
  if (!root || typeof root !== "object" || root.encoding === undefined) return value;
  if (root.encoding !== "stock-history-delta-v1") throw new Error("지원하지 않는 가격 기록 형식입니다.");
  const curve = (input: unknown): Record<string, unknown> => {
    if (!input || typeof input !== "object") throw new Error("가격 기록 형식이 올바르지 않습니다.");
    const {price_start, prices, prior_snapshots, ...metadata} = input as Record<string, unknown>;
    if (!Array.isArray(prices)) throw new Error("가격 기록이 올바르지 않습니다.");
    let day = 0;
    if (prices.length) {
      if (typeof price_start !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(price_start)) throw new Error("가격 기록의 시작일이 올바르지 않습니다.");
      day = Date.parse(`${price_start}T00:00:00Z`) / DAY;
      if (!Number.isSafeInteger(day) || day < MIN_DAY || day > MAX_DAY || new Date(day * DAY).toISOString().slice(0, 10) !== price_start) throw new Error("가격 기록의 시작일이 올바르지 않습니다.");
    } else if (price_start !== null) throw new Error("빈 가격 기록의 시작일이 올바르지 않습니다.");
    const restored = prices.map((row: unknown, index: number) => {
      if (!Array.isArray(row) || ![2, 3].includes(row.length) || !Number.isSafeInteger(row[0]) || (index === 0 ? row[0] !== 0 : row[0] <= 0)) throw new Error("가격 기록의 날짜 간격이 올바르지 않습니다.");
      day += row[0];
      if (!Number.isSafeInteger(day) || day < MIN_DAY || day > MAX_DAY) throw new Error("가격 기록의 날짜가 올바르지 않습니다.");
      const close = row[1], adjusted = row.length === 3 ? row[2] : close;
      if (typeof close !== "number" || typeof adjusted !== "number" || !Number.isFinite(close) || !Number.isFinite(adjusted) || close <= 0 || adjusted <= 0) throw new Error("가격 기록의 값이 올바르지 않습니다.");
      return [new Date(day * DAY).toISOString().slice(0, 10), close, adjusted];
    });
    if (prior_snapshots !== undefined && !Array.isArray(prior_snapshots)) throw new Error("보존 가격 기록이 올바르지 않습니다.");
    return {...metadata, prices: restored, ...(prior_snapshots === undefined ? {} : {prior_snapshots: prior_snapshots.map(curve)})};
  };
  const {encoding, ...body} = root;
  return curve(body);
}
