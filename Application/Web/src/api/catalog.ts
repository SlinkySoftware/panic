/**
 * Catalog (API.md §4.5). List rows are `ItemView` + `{can_edit, version}`; the editable resource comes from
 * `GET /catalog/{id}`. Bodies are untyped in the OpenAPI document (OBJECT), so the shapes live here.
 */
import { requestJson } from './http';

export const PROTOCOLS = ['SSH', 'RDP', 'WEB', 'LOCAL_APP'] as const;
export type Protocol = (typeof PROTOCOLS)[number];
export type Scope = 'GLOBAL' | 'TEAM' | 'PERSONAL';
export type CatalogGroup = 'shared' | 'personal';

export interface ItemView {
  id: string;
  title: string;
  protocol: Protocol;
  target: string;
  site: string;
  scope: Scope;
  zone_names: string[];
  tags: string[];
  reachable: boolean;
  unreachable_reason: string | null;
  can_edit: boolean;
  version: number;
  team_ids: string[];
}

export interface CatalogItem {
  id: string;
  title: string;
  description: string;
  protocol: Protocol;
  host: string;
  port: number | null;
  site: string;
  path_or_args: string;
  custom_uri: string;
  account_override: string;
  tags: string[];
  scope: Scope;
  team_ids: string[];
  owner_usernames: string[];
  zone_ids: string[];
  version: number;
  can_edit: boolean;
}

export type CatalogInput = Omit<CatalogItem, 'id' | 'version' | 'can_edit' | 'owner_usernames'> & {
  force_allow_duplicate?: boolean;
};

export interface Page<T> {
  results: T[];
  page: number;
  page_size: number;
  total: number;
  has_next: boolean;
}

export interface CatalogQuery {
  group: CatalogGroup;
  q?: string;
  protocol?: string;
  site?: string;
  sort?: string;
  page: number;
  page_size: number;
}

export interface Preview {
  normalized_key: string;
  resolved_host: string;
  resolved_port: number | null;
  hygiene_passed: boolean;
  hygiene_errors: string[];
  duplicate?: { id: string; title: string } | null;
}

export interface Zone {
  id: string;
  name: string;
  builtin: boolean;
}

export function listCatalog(query: CatalogQuery): Promise<Page<ItemView>> {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== '' && v !== null) params.set(k, String(v));
  return requestJson('GET', `/catalog?${params.toString()}`);
}

export const getCatalogItem = (id: string) => requestJson<CatalogItem>('GET', `/catalog/${encodeURIComponent(id)}`);

export const createCatalogItem = (body: CatalogInput) => requestJson<CatalogItem>('POST', '/catalog', body);

export const updateCatalogItem = (id: string, body: CatalogInput) =>
  requestJson<CatalogItem>('PATCH', `/catalog/${encodeURIComponent(id)}`, body);

export const deleteCatalogItem = (id: string) => requestJson<void>('DELETE', `/catalog/${encodeURIComponent(id)}`);

export const previewCatalogItem = (
  body: Pick<CatalogInput, 'protocol' | 'host' | 'port' | 'path_or_args' | 'account_override' | 'custom_uri' | 'scope'>,
) => requestJson<Preview>('POST', '/catalog/preview', body);

export const listZones = () => requestJson<Zone[]>('GET', '/zones');
