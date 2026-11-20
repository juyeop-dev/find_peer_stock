// Pure policy resolver for Node, Workers and the browser. No I/O or publication claims.
const SAFE_INTEGER = Number.MAX_SAFE_INTEGER;
export class HistoryPolicyError extends Error {}

function keys(value, expected, name) {
  if (!value || Array.isArray(value) || typeof value !== 'object' ||
      Object.keys(value).length !== expected.length ||
      expected.some(key => !Object.hasOwn(value, key))) {
    throw new HistoryPolicyError(`${name} must contain exactly: ${expected.join(', ')}`);
  }
}

function integer(value, name, minimum = 0, maximum = SAFE_INTEGER) {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new HistoryPolicyError(`${name} must be an integer between ${minimum} and ${maximum}`);
  }
  return value;
}

function isoDay(value) {
  const day = new Date(`${value}T00:00:00Z`);
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
      !Number.isFinite(day.getTime()) || day.toISOString().slice(0, 10) !== value ||
      day.getUTCFullYear() < 1) {
    throw new HistoryPolicyError('as_of must be a real calendar date in YYYY-MM-DD format');
  }
  return day;
}

export function resolveHistoryPolicy(value, {asOf = new Date().toISOString().slice(0, 10)} = {}) {
  keys(value, ['schema_version', 'collection', 'publication'], 'policy');
  if (integer(value.schema_version, 'schema_version', 1) !== 1) {
    throw new HistoryPolicyError('unsupported policy schema_version');
  }
  const collection = value.collection;
  keys(collection, ['start_year', 'end_year', 'price_reference_days'], 'collection');
  keys(value.publication, ['manifest_version'], 'publication');
  if (integer(value.publication.manifest_version, 'manifest_version', 1) !== 1) {
    throw new HistoryPolicyError('unsupported publication manifest_version');
  }
  const today = isoDay(asOf);
  const first = integer(collection.start_year, 'start_year', 1, 9999);
  const last = collection.end_year === null ? today.getUTCFullYear() :
    integer(collection.end_year, 'end_year', 1, 9999);
  const referenceDays = integer(collection.price_reference_days, 'price_reference_days');
  if (first > last || last > today.getUTCFullYear()) {
    throw new HistoryPolicyError('collection requires start_year <= end_year <= as_of year');
  }
  const startDate = `${String(first).padStart(4, '0')}-01-01`;
  const endDate = last === today.getUTCFullYear() ? asOf : `${String(last).padStart(4, '0')}-12-31`;
  const reference = new Date(`${startDate}T00:00:00Z`);
  reference.setUTCDate(reference.getUTCDate() - referenceDays);
  if (!Number.isFinite(reference.getTime()) || reference.getUTCFullYear() < 1 || reference.getUTCFullYear() > 9999) {
    throw new HistoryPolicyError('price reference date is outside years 0001..9999');
  }
  return {
    policy_schema_version: 1, publication_manifest_version: 1, as_of: asOf,
    collection: {
      start_year: first, end_year: last, start_date: startDate, end_date: endDate,
      price_reference_days: referenceDays, price_reference_start: reference.toISOString().slice(0, 10),
    },
  };
}
