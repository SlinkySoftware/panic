/**
 * Sites and teams share one shape and one CRUD contract (API.md §4.6):
 *   GET  /api/v1/{sites|teams}         -> CodeNamed[]
 *   POST /api/v1/{sites|teams}         {code, name, description} -> 201 CodeNamed
 *   PATCH/DELETE /api/v1/{kind}/{id}   (Global Admin; delete of the last site is 409 PROTECTED_RESOURCE)
 */
import { requestJson } from './http';

export type CodeNamedKind = 'sites' | 'teams';

export interface CodeNamed {
  id: string;
  code: string;
  name: string;
  description: string;
}

export type CodeNamedInput = Omit<CodeNamed, 'id'>;

export const listCodeNamed = (kind: CodeNamedKind) => requestJson<CodeNamed[]>('GET', `/${kind}`);

export const createCodeNamed = (kind: CodeNamedKind, body: CodeNamedInput) =>
  requestJson<CodeNamed>('POST', `/${kind}`, body);

export const updateCodeNamed = (kind: CodeNamedKind, id: string, body: Partial<CodeNamedInput>) =>
  requestJson<CodeNamed>('PATCH', `/${kind}/${encodeURIComponent(id)}`, body);

export const deleteCodeNamed = (kind: CodeNamedKind, id: string) =>
  requestJson<void>('DELETE', `/${kind}/${encodeURIComponent(id)}`);

// ---- zones (API.md §4.7): admins get the full shape; `zone-default` is built in (description only).
export interface ZoneAdmin {
  id: string;
  name: string;
  builtin: boolean;
  description: string;
  priority: number;
  cidrs: string[];
  version: number;
}

export type ZoneInput = Pick<ZoneAdmin, 'name' | 'description' | 'priority' | 'cidrs'>;

export interface TestIpResult {
  resolution: {
    winning_zone: { id: string; name: string } | null;
    zone_source: 'CIDR' | 'DEFAULT';
    matched_cidr: string | null;
    candidates: Record<string, unknown>[];
  };
  reachable_count: number;
  blocked_count: number;
}

export const listZonesAdmin = () => requestJson<ZoneAdmin[]>('GET', '/zones');
export const createZone = (body: ZoneInput) => requestJson<ZoneAdmin>('POST', '/zones', body);
export const updateZone = (id: string, body: Partial<ZoneInput>) =>
  requestJson<ZoneAdmin>('PATCH', `/zones/${encodeURIComponent(id)}`, body);
export const deleteZone = (id: string) => requestJson<void>('DELETE', `/zones/${encodeURIComponent(id)}`);
export const testIp = (ip: string) => requestJson<TestIpResult>('POST', '/zones/test-ip', { ip });
