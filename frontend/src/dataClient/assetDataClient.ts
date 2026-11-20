import { createStaticDataClient } from "../../../shared/static-data.mjs";
import { setPublishedHistory } from "./historyAvailability";

const configuredBase = import.meta.env.VITE_DATA_BASE_URL?.trim();
const dataset = configuredBase ? createStaticDataClient({baseUrl: configuredBase, onPublication: setPublishedHistory}) : undefined;

// Only public data GETs use the separate host. Refresh API calls retain their
// existing fetch path. With no configured host this preserves flat deployments.
export async function fetchDataAsset(input: string, init?: RequestInit): Promise<Response> {
  if (!dataset || (init?.method && init.method !== "GET")) return fetch(input, init);
  const url = new URL(input, window.location.href);
  const localData = new URL(`${import.meta.env.BASE_URL}data/`, window.location.origin);
  if (url.origin !== localData.origin || !url.pathname.startsWith(localData.pathname)) return fetch(input, init);
  let logical: string;
  try {logical = decodeURIComponent(url.pathname.slice(localData.pathname.length));}
  catch {throw new Error("Invalid public data URL");}
  try {
    const bytes = await dataset.get(logical, {signal: init?.signal});
    return new Response(bytes, {headers: {"Content-Type": logical.endsWith(".gz") ? "application/gzip" : "application/json"}});
  } catch (error) {
    if (init?.signal?.aborted) throw error;
    // A migration can retain flat assets on Pages. Their original timestamps
    // remain intact; if they also fail, existing polling retains its last data.
    const fallback = await fetch(input, init).catch(() => undefined);
    if (fallback?.ok && !fallback.headers.get("Content-Type")?.includes("text/html")) return fallback;
    // Readers intentionally try delta -> gzip -> JSON. Preserve a true missing
    // path as 404 so the next stored encoding can be tried.
    if (error && typeof error === "object" && "status" in error && error.status === 404) return new Response(null, {status: 404});
    throw error;
  }
}
