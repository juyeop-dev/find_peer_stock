import policy from '../../../config/history-policy.json' with {type: 'json'};
import publication from '../../../shared/published-history.json' with {type: 'json'};
import {resolveHistoryPolicy} from '../../../shared/history-policy.mjs';
import {publishedStart, validatePublication} from '../../../shared/history-availability.mjs';

export const publishedHistory = validatePublication(publication);
export const publishedHistoryStart = kind => publishedStart(publishedHistory, kind);
export function collectionHistory(asOf = new Date().toISOString().slice(0, 10), value = policy) {
  return resolveHistoryPolicy(value, {asOf}).collection;
}
export function historyWindow(range = collectionHistory(), now = Date.now()) {
  const recent = new Date(Math.min(now, Date.parse(`${range.end_date}T00:00:00Z`)));
  const month = recent.getUTCMonth();
  recent.setUTCFullYear(recent.getUTCFullYear() - 2);
  if (recent.getUTCFullYear() < 1) recent.setUTCFullYear(1, 0, 1);
  if (recent.getUTCMonth() !== month) recent.setUTCDate(0);
  const start = Math.min(recent.getTime(), Date.parse(`${range.price_reference_start}T00:00:00Z`));
  return {start, end: Math.min(now + 60000, Date.parse(`${range.end_date}T00:00:00Z`) + 86400000),
    startDate: new Date(start).toISOString().slice(0, 10), endDate: range.end_date};
}
