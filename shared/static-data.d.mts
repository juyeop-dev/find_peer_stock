import type { PublicationManifest } from './history-availability.mjs';
export function sha256(bytes: Uint8Array): Promise<string>;
export function validDataPath(path: string): boolean;
export function readTar(bytes: Uint8Array, requested: string): Uint8Array;
export function createStaticDataClient(options: {baseUrl: string; fetcher?: typeof fetch; manifestTtl?: number; maxCacheBytes?: number; onPublication?: (value: PublicationManifest) => void}): {
  get(path: string, options?: {signal?: AbortSignal | null}): Promise<Uint8Array<ArrayBuffer>>;
  manifest(force?: boolean): Promise<{revision: string; publication: PublicationManifest}>;
  clear(): void;
  stats(): {cacheBytes: number; cachedAssets: number; pending: number; revision?: string};
};
