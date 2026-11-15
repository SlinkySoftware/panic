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
