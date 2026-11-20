// Pure calendar validation. An unknown year never falls back to invented weekdays.
export function verifiedSessions(start, end, market, calendars) {
  function day(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
        !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value) {
      throw new Error(`Invalid calendar date: ${value}`);
    }
    return value;
  }
  day(start); day(end);
  if (end < start) throw new Error('Calendar end precedes start');
  const closed = new Set(), opened = new Set();
  for (let year = Number(start.slice(0, 4)); year <= Number(end.slice(0, 4)); year++) {
    const calendar = calendars[year];
    if (!calendar || calendar.schema_version !== 1 || calendar.year !== year) throw new Error(`Verified ${year} calendar missing or mismatched`);
    const rows = calendar.markets.filter(row => row.market === market);
    if (rows.length !== 1 || !rows[0].source_urls?.length) throw new Error(`Calendar evidence missing or duplicated: ${market}/${year}`);
    for (const [target, dates] of [[closed, rows[0].dates], [opened, rows[0].additional_open_dates ?? {}]]) {
      for (const stamp of Object.keys(dates)) {
        day(stamp);
        if (Number(stamp.slice(0, 4)) !== year) throw new Error(`Calendar contains an out-of-year date: ${stamp}`);
        target.add(stamp);
      }
    }
  }
  if ([...closed].some(day => opened.has(day))) throw new Error('Calendar marks a date both closed and open');
  const result = [];
  for (let stamp = Date.parse(start); stamp <= Date.parse(end); stamp += 86400000) {
    const date = new Date(stamp), value = date.toISOString().slice(0, 10);
    if (!closed.has(value) && (![0, 6].includes(date.getUTCDay()) || opened.has(value))) result.push(value);
  }
  return result;
}
