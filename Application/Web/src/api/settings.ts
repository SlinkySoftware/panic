/** Remaining T-S6-11 endpoints: orphans, app settings, my profile, audit, client-IP diagnostics (API.md §4.4, §4.7). */
import { requestJson } from './http';
import type { Page, Scope } from './catalog';

const qs = (o: object) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== null && v !== '') p.set(k, String(v));
  return p.toString();
};

// ---- orphans
export type OrphanKind = 'catalog' | 'list' | 'dashboard';
export interface Orphan {
  kind: OrphanKind;
  id: string;
  title: string;
  scope: Scope;
  former_team_ids?: string[];
  former_owners?: string[];
  updated_at: string;
}
export const listOrphans = (query: { kind?: string; q?: string; page: number; page_size: number }) =>
  requestJson<Page<Orphan>>('GET', `/admin/orphans?${qs(query)}`);
export const assignOrphan = (kind: OrphanKind, id: string, username: string) =>
  requestJson<{ dropped_item_ids?: string[] }>('POST', `/admin/orphans/${kind}/${encodeURIComponent(id)}/assign`, {
    username,
  });
/** Orphans are deleted through the normal endpoint (admins may delete orphans only). */
export const deleteOrphan = (kind: OrphanKind, id: string) =>
  requestJson<void>(
    'DELETE',
    `/${kind === 'list' ? 'lists' : kind === 'dashboard' ? 'dashboards' : 'catalog'}/${encodeURIComponent(id)}`,
  );

// ---- app settings
export interface AppSettings {
  default_global_dashboard: { id: string; title: string | null } | null;
  ssh_uri_enabled: boolean;
  ssh_uri_scheme: string;
  version: number;
}
export type SettingsPatch = Partial<{
  default_global_dashboard_id: string;
  ssh_uri_enabled: boolean;
  ssh_uri_scheme: string;
}>;
export const getSettings = () => requestJson<AppSettings>('GET', '/settings');
export const updateSettings = (version: number, body: SettingsPatch) =>
  requestJson<AppSettings>('PATCH', '/settings', body, { 'If-Match': `"${version}"` });

// ---- my profile
export interface MyProfile {
  id: string;
  username: string;
  display_name: string;
  default_remote_user: string;
  ssh_template: string;
  prefs: { density: 'COMFORT' | 'COMPACT'; theme: 'LIGHT' | 'DARK'; unreachable_policy: 'DIM' | 'HIDE' };
  default_dashboard_id: string | null;
  pinned_dashboard_ids: string[];
  version: number;
}
export const getMe = () => requestJson<MyProfile>('GET', '/me');
export const updateMe = (
  version: number,
  body: Partial<Pick<MyProfile, 'display_name' | 'default_remote_user' | 'ssh_template'> & MyProfile['prefs']>,
) => requestJson<MyProfile>('PATCH', '/me', body, { 'If-Match': `"${version}"` });

// ---- audit (keyset paged, newest first)
export interface AuditEntry {
  id: string;
  created_at: string;
  actor_username: string;
  view_as_username: string | null;
  action: string;
  target_type: string;
  target_id: string;
  summary: string;
  details: Record<string, unknown> | null;
  client_ip: string | null;
  zone_id: string | null;
  request_id: string | null;
}
export interface AuditFilters {
  actor?: string;
  action?: string;
  target_type?: string;
  target_id?: string;
  q?: string;
  since?: string;
  until?: string;
}
export const listAudit = (filters: AuditFilters, cursor?: string | null, limit = 100) =>
  requestJson<{ results: AuditEntry[]; next_cursor: string | null }>(
    'GET',
    `/audit?${qs({ ...filters, cursor: cursor ?? '', limit })}`,
  );

// ---- client-IP diagnostics
export interface ClientIpDiagnostics {
  remote_addr: string;
  peer_trusted: boolean;
  policy: Record<string, unknown>;
  raw: Record<string, string | null>;
  hops: Record<string, unknown>[];
  ignored_left_hops: number;
  truncated: boolean;
  decision: string;
  client_ip: string | null;
  zone: { id: string; name: string; matched_cidr: string | null } | null;
  zone_source: string;
  candidates: Record<string, unknown>[];
}
export const getClientIp = () => requestJson<ClientIpDiagnostics>('GET', '/admin/client-ip');
