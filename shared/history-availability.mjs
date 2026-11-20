// Publication evidence is independent of the requested collection range.
export function validatePublication(value) {
  if (!value || value.schema_version !== 1 || typeof value.revision !== 'string' || !value.revision ||
      !/^[a-f0-9]{64}$/.test(value.evidence?.sha256 ?? '') || !value.evidence?.verified_at ||
      !Number.isFinite(Date.parse(value.evidence.verified_at)) || Date.parse(value.evidence.verified_at) > Date.now() + 60000 || !value.kinds || Array.isArray(value.kinds)) {
    throw new Error('Invalid verified publication manifest');
  }
  for (const kind of Object.values(value.kinds)) {
    if (!Number.isInteger(kind.selection_start_year) || !Number.isInteger(kind.selection_end_year) ||
        kind.selection_start_year < 1 || kind.selection_start_year > kind.selection_end_year ||
        kind.selection_end_year >= new Date(value.evidence.verified_at).getUTCFullYear() ||
        kind.scope !== 'observed_with_listing_exceptions' || !Number.isInteger(kind.published_items) || kind.published_items <= 0) {
      throw new Error('Invalid published history range');
    }
  }
  return value;
}

export function publishedStart(manifest, kind) {
  const range = validatePublication(manifest).kinds[kind];
  return range ? `${String(range.selection_start_year).padStart(4, '0')}-01-01` : undefined;
}

export function publishedYears(manifest, kind) {
  const range = validatePublication(manifest).kinds[kind];
  if (!range) return [];
  return Array.from({length: range.selection_end_year - range.selection_start_year + 1}, (_, index) => range.selection_end_year - index);
}

export function sinceStart(period) {
  const match = typeof period === 'string' && period.match(/^since(\d{4})(H2)?$/);
  if (!match || Number(match[1]) < 1) return undefined;
  return `${match[1]}-${match[2] ? '07' : '01'}-01`;
}

export function sinceLabel(period) {
  const start = sinceStart(period);
  return start ? `${start.slice(0, 4)}년${start.slice(5, 7) === '07' ? ' 하반기' : ''}~` : undefined;
}
