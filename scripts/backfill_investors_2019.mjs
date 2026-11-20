// Compatibility entry point for verified 2019 investor/index pairs.
import {main} from './backfill_investors.mjs';
await main(process.argv.slice(2), 2019);
