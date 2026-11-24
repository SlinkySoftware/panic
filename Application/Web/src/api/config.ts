/**
 * Config transfer (super admin): export sites, teams, zones, catalog items and lists as one JSON file, and
 * merge-import such a file. Import is two-step: a preview returns the plan and its `plan_digest`; the import
 * applies only if the data still produces that plan (409 otherwise: re-run the preview).
 */
import { requestJson } from './http';

export const CONFIG_EXPORT_PATH = '/api/v1/admin/config/export';

export const CONFIG_SECTIONS = ['sites', 'teams', 'zones', 'catalog', 'lists'] as const;
export type ConfigSection = (typeof CONFIG_SECTIONS)[number];

export const CONFIG_SECTION_LABELS: Record<ConfigSection, string> = {
  sites: 'Sites',
  teams: 'Teams',
  zones: 'Zones',
  catalog: 'Catalog items',
  lists: 'Lists',
};

export interface SectionSummary {
  added: number;
  changed: number;
  unchanged: number;
  conflicts: number;
}

export interface ConfigChange {
  section: ConfigSection;
  action: 'ADD' | 'UPDATE' | 'CONFLICT';
  id: string;
  label: string;
  fields?: string[]; // UPDATE only
  reason?: string; // CONFLICT only
}

export interface ImportPreview {
  plan_digest: string;
  summary: Record<ConfigSection, SectionSummary>;
  changes: ConfigChange[];
  warnings: string[];
}

export interface ImportResult {
  summary: Record<ConfigSection, SectionSummary>;
  warnings: string[];
}

export const previewConfigImport = (document: unknown) =>
  requestJson<ImportPreview>('POST', '/admin/config/import/preview', document);

export const applyConfigImport = (document: unknown, planDigest: string) =>
  requestJson<ImportResult>('POST', '/admin/config/import', { document, plan_digest: planDigest });
