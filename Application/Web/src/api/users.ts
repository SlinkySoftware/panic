/** Users management (API.md §4.7, Global Admin): the only place permissions and team membership change. */
import { requestJson } from './http';
import type { Page } from './catalog';

/** SUPER_ADMIN is only shown to super admins (the server strips it for everyone else). */
export const PERMISSION_FLAGS = ['SUPER_ADMIN', 'GLOBAL_ADMIN', 'CAN_ADD_GLOBAL', 'CAN_ADD_TEAM'] as const;
export type PermissionFlag = (typeof PERMISSION_FLAGS)[number];

/** The flags a caller may see and set: SUPER_ADMIN only for super admins. */
export const permissionFlagsFor = (superAdmin: boolean): PermissionFlag[] =>
  PERMISSION_FLAGS.filter((p) => superAdmin || p !== 'SUPER_ADMIN');

export const PERMISSION_LABELS: Record<PermissionFlag, string> = {
  SUPER_ADMIN: 'Super admin',
  GLOBAL_ADMIN: 'Global Admin',
  CAN_ADD_GLOBAL: 'Can add Global items',
  CAN_ADD_TEAM: 'Can add Team items',
};

export interface UserSummary {
  id: string;
  username: string;
  display_name: string;
  auth_source: string;
  permissions: PermissionFlag[];
  team_ids: string[];
  disabled: boolean;
  last_login_at: string | null;
  version: number;
  bootstrap_admin?: boolean;
  can_edit?: boolean; // false: a regular admin looking at the bootstrap admin
}

export interface UserDetail extends UserSummary {
  owned_counts: { catalog: number; lists: number; dashboards: number };
}

export interface UserQuery {
  q?: string;
  permission?: string;
  team_id?: string;
  disabled?: string;
  page: number;
  page_size: number;
}

const qs = (o: object) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== null && v !== '') p.set(k, String(v));
  return p.toString();
};

export const listUsers = (query: UserQuery) => requestJson<Page<UserSummary>>('GET', `/users?${qs(query)}`);
export const getUser = (id: string) => requestJson<UserDetail>('GET', `/users/${encodeURIComponent(id)}`);
export const createUser = (body: {
  username: string;
  display_name?: string;
  permissions: string[];
  team_ids: string[];
}) => requestJson<UserSummary>('POST', '/users', body);
export const updateUser = (
  id: string,
  version: number,
  body: Partial<Pick<UserSummary, 'display_name' | 'permissions' | 'team_ids' | 'disabled'>>,
) => requestJson<UserSummary>('PATCH', `/users/${encodeURIComponent(id)}`, body, { 'If-Match': `"${version}"` });
export const listTeamMembers = (teamId: string, page = 1) =>
  requestJson<Page<UserSummary>>('GET', `/teams/${encodeURIComponent(teamId)}/members?${qs({ page, page_size: 100 })}`);
