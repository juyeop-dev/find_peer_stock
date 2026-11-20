**Historical collection policy — contract and price adapter**

`config/history-policy.json` is the shared source for collection date policy.
`scripts/history_policy.py` and `shared/history-policy.mjs` resolve the same
validated input. The JavaScript resolver is pure and can be used by Node,
Workers, or browser build adapters; file I/O lives in a separate inspection CLI.
Neither resolver imports a collector, writes data, contacts a provider, or
asserts that the requested dates have been published.

Stage 1 supplied the policy and inspection tools. Stage 2A's price portion now
connects `refresh_stock_information_history.py` and the 2014–2023 cached-price
entry points to it. Financial collection, other market collectors, Worker and
UI adapters remain pending. Changing the policy changes price requests, never
the verified publication range or UI year choices.

| Setting | Meaning |
|---|---|
| `schema_version: 1` | Version of the policy input contract. Other versions fail validation. |
| `collection.start_year: 2014` | Requested collection begins on January 1. Not a promise of coverage. |
| `collection.end_year: null` | Resolve through the execution date in UTC. A specified completed year ends December 31. |
| `collection.price_reference_days: 12` | Calendar days before January 1 to request for preceding-session references. Actual exchange sessions are verified separately. |
| `publication.manifest_version: 1` | Reserved contract version for the future verified publication manifest; not the data encoding version or a publication status. |

Unknown keys, unsupported versions, invalid dates, noninteger years, booleans
used as years, reversed/future year ranges, negative reference days, and date
arithmetic outside years 0001..9999 fail before any collection work. An explicit
current year is capped at the inspection date. Numeric validation is consistent
across Python and JavaScript, including JSON integer values written as `2013.0`.

UTC is used for the execution-date default, matching existing collectors.
Callers can supply a date explicitly for deterministic runs and tests. Market
trading dates and user-facing timezones remain separate responsibilities.

The current defaults resolve on 2026-11-17 to collection dates
`2014-01-01..2026-11-17` and price reference start `2013-12-20`.
For a completed 2013-only request they resolve to
`2013-01-01..2013-12-31` and reference start `2012-12-20`. This calculation says
nothing about actual 2013 provider availability.

Read-only inspection, from the repository root:

```powershell
python scripts/history_policy.py --as-of 2026-11-17
node scripts/inspect-history-policy.mjs --as-of 2026-11-17
python -m unittest discover -s tests -p test_history_policy.py -v
```

Both inspection CLIs accept `--config PATH` to inspect an independent file.
Invalid input exits with status 2 and emits no successful request JSON. The
inspection date is not a new permission to request future provider data.

**Verified publication manifest contract for later stages**

The manifest is produced from audited publication artifacts, not hand-written
in this collection config. Stage 1 defines its responsibilities, but does not
emit an operational manifest or claim deployment coverage.

- Identify the manifest schema version, immutable publication revision,
  artifact/content hashes, and the audit evidence supporting that revision.
- Describe observed/published coverage by data kind and market, and retain
  per-symbol exceptions. The earliest observation is not proof that every
  symbol or session in a market is available.
- Describe encoded file formats separately from this manifest version. Existing
  `stock-history-delta-v1`, sector encodings, original gzip archives and their
  compatibility rules remain unchanged.
- Keep the requested collection range separate from observed dates and audit
  outcomes. A failed provider request is not evidence of nonexistent data.
- Publication controls which earlier-year choices may appear in the UI; editing
  the collection start year alone cannot expand displayed verified coverage.
- A new publication revision is eligible only after original-data preservation,
  encoding round-trip and file-limit checks pass. Failed publication keeps the
  previous revision available.

**Existing date decisions to migrate**

This is an inventory of responsibilities, not a request to replace every
matching year literal. Historical fixtures, exchange calendars, durable audit
keys and archive filenames must retain their original meaning.

| Layer / file | Current decision | Planned stage |
|---|---|---|
| `scripts/stock_information.py` | `START`, financial filters and generated metadata; checkpoint accepts an explicit price context | 2A financial pending; price checkpoint done |
| `scripts/refresh_stock_information_history.py` | Reference boundary, scope-specific state, minimum two-year fallback | 2A price done |
| `scripts/extend_stock_history_2014.py` through `extend_stock_history_2023.py` | Explicit year, reference start and cache years, without global mutations | 2A price done |
| `scripts/backfill_stock_information_2014.py` and `backfill_stock_information_2024_h2.py` | Date range, state/audit paths, table and historical coverage keys | 2A |
| `scripts/run_2014.py` | Date arguments, job dependencies, progress paths and locks | 2B |
| `scripts/configure_calendar_2014.py`, `deployment_history_2014.py` | Verified official holidays, special open days, closed-session exclusions | 2B; preserve year-specific evidence |
| `scripts/backfill_credit_2014.py`, `backfill_investors_2014.mjs` | Reporting months, paired market observations and durable cache paths | 2B |
| `scripts/backfill_sector_history_2014.py`, semiconductor/replay backfills | Data-specific collection range and snapshot preservation | 2B |
| `automation/live-api/src/providers.js`, `history.js` | Reference start and at-least-two-year history | 3 |
| `automation/live-api/src/information.js` | Start filter and year-specific Yahoo statement requests | 3; provider limits remain distinct |
| `automation/live-api/src/investors.js`, `sectors.js` | Supported dates and same-session source comparisons | 3 |
| `frontend/src/dataClient/stockHistoryClient.ts` | Chart period choices, `since2014` compatibility, original refresh start | 3 |
| `frontend/src/dataClient/stockInformationClient.ts` | Historical coverage field retention and actual statement boundaries | 3 |
| `frontend/src/dataClient/investorDataClient.ts`, `frontend/src/pages/CreditBalancePage.tsx` | User-selectable history boundaries | 3 |
| `.github/workflows/build-site.yml`, `deploy-prepared-snapshots.yml`, `refresh-stock-information.yml` | Build/collection commands, preservation gates and publication consistency | 2–5 as the corresponding adapter is migrated |

Official calendars and provider observations still require per-year evidence.
There is deliberately no generated list of fictional future/earlier data here.

**Stage 2A price adapter — 2026-11-18**

`scripts/price_history_range.py` resolves a frozen request before roster,
database or provider access. The refresher accepts `--history-config PATH`;
the default policy preserves the original 2014 start and 2013-12-20 reference.
Its internal provider functions accept that request explicitly. The historical
refresh no longer changes `stock_chart_history.DATABASE`; `database(path)`
selects a connection without changing the default used by other callers.

The existing annual cached-price commands select their named year explicitly.
`--year YEAR` overrides that compatibility year. They validate the whole policy
and use its reference-day setting; the named/explicit year overrides the
policy's start/end years. They remain cache-only and retain the old cache URL
hashes (370 preceding days, two following days). The 2014 entry point still
consults only the 2014 Yahoo cache by default; the other existing entry points
consult their year through 2023. A later explicit year consults that year only.
`join_prices` retains its legacy 2023 default for callers without `start`, while
the annual jobs always pass an explicit reference start.

No collection/import is performed by these review commands:

```powershell
python scripts/refresh_stock_information_history.py --dry-run
python scripts/extend_stock_history_2014.py --dry-run
python scripts/extend_stock_history_2023.py --dry-run
```

The refresher retains at least 732 days before the requested endpoint, or the
earlier configured reference boundary. Provider outputs are bounded to that
window and the requested end. Yahoo dated queries use an exclusive endpoint;
Spark and TradingView still request provider-supported ranges/latest bar
counts, then filter observed dates locally. TradingView retains its 5000-bar
cap. A requested range is not a claim that the provider supplies it. No prices
are interpolated. The existing candidate/snapshot preservation rules remain
in place: different currencies or adjustment conventions are never spliced.
An older bounded request may leave the newer original in `prior_snapshots`;
it does not erase that original or assert current-price coverage.

Ongoing refreshes with the original 12 reference days keep
`history_YEAR_updates`. Bounded refreshes or changed reference days use
`history_YEAR_<range hash>_updates`. The identity uses start year, requested end
year (including the ongoing/null distinction), and reference days, so resuming
on another day keeps the same table while different ranges cannot reuse its
completion receipts. Annual imports keep their legacy table for the default
window. The refresher ignores `cache_status` receipts in a shared legacy table:
an imported older prefix is not evidence of a completed current-price refresh.

The default refresher retains `history-progress.json` and the existing common
audit outputs. Other scopes write `history-<scope>-progress.json` and common
checkpoint output under `price-ranges/<scope>/`. Checkpoint receives the price
start/end, state table and resume command explicitly. Financial checkpoint
stage selection remains unchanged until the financial portion of 2A.

Validation and the exact financial restart location are recorded in
`../hosting_review/2026-11-17/STAGE2A_PRICE_RESULT.md` in the workspace. No
network collection, source regeneration, hosting changes or deployment was
performed in this unit.
