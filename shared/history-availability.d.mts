export interface PublishedKind {
  selection_start_year: number; selection_end_year: number;
  scope: string; published_items: number;
}
export interface PublicationManifest {
  schema_version: number; revision: string;
  evidence: {path: string; sha256: string; commit: string; verified_at: string; basis: string};
  kinds: Record<string, PublishedKind>;
}
export function validatePublication(value: PublicationManifest): PublicationManifest;
export function publishedStart(value: PublicationManifest, kind: string): string | undefined;
export function publishedYears(value: PublicationManifest, kind: string): number[];
export function sinceStart(period: unknown): string | undefined;
export function sinceLabel(period: unknown): string | undefined;
