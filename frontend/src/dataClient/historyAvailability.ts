import publication from "../../../shared/published-history.json";
import { publishedStart, publishedYears, sinceStart, sinceLabel, validatePublication } from "../../../shared/history-availability.mjs";

export const PUBLISHED_HISTORY = validatePublication(publication);
let current = PUBLISHED_HISTORY;
const listeners = new Set<() => void>();
export function setPublishedHistory(value: typeof PUBLISHED_HISTORY) {
  validatePublication(value);
  if (current.revision === value.revision) return;
  // An older cached data deployment cannot roll back a newer verified range.
  if (Date.parse(value.evidence.verified_at) < Date.parse(current.evidence.verified_at)) return;
  current = value; listeners.forEach(listener => listener());
}
export const historyPublicationSnapshot = () => current;
export const subscribeHistoryPublication = (listener: () => void) => {listeners.add(listener); return () => {listeners.delete(listener);};};
export const publishedHistoryStart = (kind: string) => publishedStart(current, kind);
export const publishedHistoryYears = (kind: string) => publishedYears(current, kind);
export { sinceStart, sinceLabel };
