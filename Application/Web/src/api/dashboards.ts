/** Dashboards (API.md §4.2 view, §4.3 resource, §4.4 menu/default). */
import { apiFetch, apiUrl, newRequestId, REQUEST_ID_HEADER, requestJson, toApiError } from './http';
import type { ItemView, Page, Scope } from './catalog';

export interface Widget {
  id: string;
  widget_type: 'HOST' | 'LIST';
  title: string;
  grid_x: number;
  grid_y: number;
  grid_w: number;
  grid_h: number;
  catalog_item_id?: string;
  list_id?: string;
}

export interface WidgetList {
  id: string;
  title: string;
  scope: Scope;
  item_count: number;
  item_ids: string[];
  truncated: boolean;
}

export interface DashboardView {
  dashboard: {
    id: string;
    title: string;
    description: string;
    scope: Scope;
    team_ids: string[];
    always_display: boolean;
    version: number;
    can_edit: boolean;
    is_user_default: boolean;
    is_global_default: boolean;
  };
  widgets: Widget[];
  items: Record<string, ItemView>;
  lists: Record<string, WidgetList>;
  unavailable: { items: string[]; lists: string[] };
}

export interface DashboardInput {
  title: string;
  description: string;
  scope: Scope;
  team_ids: string[];
  always_display?: boolean;
  set_as_user_default?: boolean;
}

// ETag cache: a revisit sends If-None-Match and reuses the cached body on 304 (T-S6-09).
const viewCache = new Map<string, { etag: string; body: DashboardView }>();

export async function getDashboardView(id: string): Promise<DashboardView> {
  const cached = viewCache.get(id);
  const requestId = newRequestId();
  const headers: Record<string, string> = { Accept: 'application/json', [REQUEST_ID_HEADER]: requestId };
  if (cached) headers['If-None-Match'] = cached.etag;
  const res = await apiFetch(new Request(apiUrl(`/ui/dashboards/${encodeURIComponent(id)}`), { headers }));
  if (res.status === 304 && cached) return cached.body;
  if (!res.ok) throw await toApiError(res, requestId);
  const body = (await res.json()) as DashboardView;
  const etag = res.headers.get('ETag');
  if (etag) viewCache.set(id, { etag, body });
  return body;
}

export const createDashboard = (body: DashboardInput) => requestJson<{ id: string }>('POST', '/dashboards', body);

export const setMyDefaultDashboard = (dashboardId: string | null) =>
  requestJson<void>('PUT', '/me/default-dashboard', { dashboard_id: dashboardId });

export const pinDashboard = (id: string) => requestJson<void>('PUT', `/me/menu/${encodeURIComponent(id)}`);

export const unpinDashboard = (id: string) => requestJson<void>('DELETE', `/me/menu/${encodeURIComponent(id)}`);

export interface DashboardSummary {
  id: string;
  title: string;
  scope: Scope;
  team_ids: string[];
  always_display: boolean;
  sort_order: number;
  in_menu: boolean;
}

export function listDashboards(query: {
  q?: string;
  scope?: Scope | undefined;
  page?: number;
}): Promise<Page<DashboardSummary>> {
  const params = new URLSearchParams({ page: String(query.page ?? 1), page_size: '100' });
  if (query.q) params.set('q', query.q);
  if (query.scope) params.set('scope', query.scope);
  return requestJson('GET', `/dashboards?${params.toString()}`);
}
