import {readFile} from 'node:fs/promises';
import ts from 'typescript';

const encode = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const publication = JSON.parse(await readFile(new URL('../../shared/published-history.json', import.meta.url), 'utf8'));
const shared = encode(await readFile(new URL('../../shared/history-availability.mjs', import.meta.url), 'utf8'));
const source = (await readFile(new URL('../src/dataClient/historyAvailability.ts', import.meta.url), 'utf8'))
  .replace('import publication from "../../../shared/published-history.json";', `const publication = ${JSON.stringify(publication)};`)
  .replace('from "../../../shared/history-availability.mjs"', `from "${shared}"`);
export const historyAvailabilityUrl = encode(ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022}}).outputText);
