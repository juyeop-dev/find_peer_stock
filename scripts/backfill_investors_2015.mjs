// Compatibility entry point for verified 2015 investor/index pairs.
import {main} from './backfill_investors.mjs';
await main(process.argv.slice(2), 2015);
