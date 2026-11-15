import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const source=await readFile(new URL('../src/dataClient/priceArchive.ts',import.meta.url),'utf8');
const javascript=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
export const priceArchiveUrl=`data:text/javascript;base64,${Buffer.from(javascript).toString('base64')}`;
export const {expandPriceArchive}=await import(priceArchiveUrl);
