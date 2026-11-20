// Compatibility entry point for verified 2018 investor/index pairs.
import {main} from './backfill_investors.mjs';
await main(process.argv.slice(2), 2018);
