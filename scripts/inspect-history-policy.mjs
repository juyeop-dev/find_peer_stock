// Read-only counterpart of python scripts/history_policy.py.
import {readFile} from 'node:fs/promises';
import {parseArgs} from 'node:util';
import {resolveHistoryPolicy} from '../shared/history-policy.mjs';

try {
  const {values} = parseArgs({options: {config: {type: 'string'}, 'as-of': {type: 'string'}}});
  const path = values.config ?? new URL('../config/history-policy.json', import.meta.url);
  const source = (await readFile(path, 'utf8')).replace(/^\uFEFF/, '');
  const result = resolveHistoryPolicy(JSON.parse(source),
    values['as-of'] === undefined ? {} : {asOf: values['as-of']});
  console.log(JSON.stringify(result));
} catch (error) {
  console.error(`history policy: ${error.message}`);
  process.exitCode = 2;
}
