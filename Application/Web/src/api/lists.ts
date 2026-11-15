/** Endpoint lists (API.md §4.6). PUT and DELETE need `If-Match: "<version>"`. */
import { requestJson } from './http';
import type { CatalogGroup, ItemView, Page, Scope } from './catalog';

export interface ListSummary {
  id: string;
  title: string;
  description: string;
  scope: Scope;
  team_ids: string[];
  item_count: number;
  version: number;
  can_edit: boolean;
}

export interface EndpointList extends ListSummary {
  item_ids: string[];
  items: ItemView[];
}

export interface ListInput {
  title: string;
  description: string;
  scope: Scope;
  team_ids: string[];
  item_ids: string[];
}

const ifMatch = (version: number) => ({ 'If-Match': `"${version}"` });

export function listLists(query: {
  group: CatalogGroup;
  q?: string;
  page: number;
  page_size: number;
}): Promise<Page<ListSummary>> {
  const params = new URLSearchParams({
    group: query.group,
    page: String(query.page),
    page_size: String(query.page_size),
  });
  if (query.q) params.set('q', query.q);
  return requestJson('GET', `/lists?${params.toString()}`);
}

export const getList = (id: string) => requestJson<EndpointList>('GET', `/lists/${encodeURIComponent(id)}`);

export const createList = (body: ListInput) => requestJson<EndpointList>('POST', '/lists', body);

export const replaceList = (id: string, version: number, body: ListInput) =>
  requestJson<EndpointList>('PUT', `/lists/${encodeURIComponent(id)}`, body, ifMatch(version));

export const deleteList = (id: string, version: number) =>
  requestJson<void>('DELETE', `/lists/${encodeURIComponent(id)}`, undefined, ifMatch(version));
