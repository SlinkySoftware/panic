import type { RouteLocationRaw, RouteRecordRaw } from 'vue-router';
import { useSessionStore } from '@/stores/session';

declare module 'vue-router' {
  interface RouteMeta {
    /** Reachable without a session (login page, 404). Every other route requires one. */
    public?: boolean;
    title?: string;
    /** `GLOBAL_ADMIN` only (AR-2.5); a standard user is sent to `/`. */
    admin?: boolean;
  }
}

const PlaceholderPage = () => import('@/pages/PlaceholderPage.vue');
const CodeNamedTable = () => import('@/components/admin/CodeNamedTable.vue');

/**
 * Resolve `/` and `/dashboard` to the caller's effective default dashboard, canonicalising the address bar to
 * `/dashboard/<uuid>` (UI_DESIGN.md §2). Runs after the global `authGuard`, so the session is already loaded and
 * the user already known to be signed in by the time this executes.
 */
async function toDefaultDashboard(): Promise<RouteLocationRaw> {
  const session = useSessionStore();
  await session.ensureLoaded();
  const id = session.defaultDashboard?.id;
  // No dashboard at all is visible to this user (should not happen once catalog/dashboards exist) -> Catalog.
  return id ? { name: 'dashboard-view', params: { id } } : { name: 'catalog' };
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/pages/LoginPage.vue'),
    meta: { public: true, title: 'Sign in' },
  },
  {
    // AR-1.4 legacy route: /rbac is a redirect only, never a real destination.
    path: '/rbac',
    redirect: { path: '/settings/users' },
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    children: [
      {
        path: '',
        name: 'root',
        component: PlaceholderPage,
        props: { title: 'Dashboard', caption: 'Resolving your default dashboard…' },
        beforeEnter: toDefaultDashboard,
      },
      {
        path: 'dashboard',
        name: 'dashboard',
        component: PlaceholderPage,
        props: { title: 'Dashboard', caption: 'Resolving your default dashboard…' },
        beforeEnter: toDefaultDashboard,
      },
      {
        path: 'dashboard/:id',
        name: 'dashboard-view',
        component: () => import('@/pages/DashboardPage.vue'),
        props: (route) => ({ id: String(route.params.id) }),
        meta: { title: 'Dashboard' },
      },
      {
        path: 'dashboard/:id/edit',
        name: 'dashboard-edit',
        component: () => import('@/pages/DashboardEditPage.vue'),
        props: (route) => ({ id: String(route.params.id) }),
        meta: { title: 'Edit dashboard' },
      },
      {
        path: 'catalog',
        name: 'catalog',
        component: () => import('@/pages/CatalogPage.vue'),
        meta: { title: 'Catalog' },
      },
      {
        path: 'lists',
        name: 'lists',
        component: () => import('@/pages/ListsPage.vue'),
        meta: { title: 'Lists' },
      },
      {
        path: 'sites',
        name: 'sites',
        component: CodeNamedTable,
        props: { kind: 'sites', title: 'Sites', noun: 'site' },
        meta: { title: 'Sites' },
      },
      {
        path: 'teams',
        name: 'teams',
        component: CodeNamedTable,
        props: { kind: 'teams', title: 'Teams', noun: 'team' },
        meta: { title: 'Teams' },
      },
      {
        path: 'zones',
        name: 'zones',
        component: () => import('@/pages/ZonesPage.vue'),
        meta: { title: 'Zones' },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/pages/SettingsPage.vue'),
        meta: { title: 'Application Settings' },
      },
      {
        path: 'settings/users',
        name: 'settings-users',
        component: () => import('@/pages/UsersPage.vue'),
        meta: { title: 'Users', admin: true },
      },
      {
        path: 'settings/users/:id',
        name: 'settings-user-detail',
        component: () => import('@/pages/UserEditPage.vue'),
        props: (route) => ({ id: String(route.params.id) }),
        meta: { title: 'User', admin: true },
      },
      {
        path: 'settings/orphans',
        name: 'settings-orphans',
        component: () => import('@/pages/OrphansPage.vue'),
        meta: { title: 'Orphans', admin: true },
      },
      {
        path: 'settings/client-ip',
        name: 'settings-client-ip',
        component: () => import('@/pages/ClientIpPage.vue'),
        meta: { title: 'Client-IP diagnostics', admin: true },
      },
      {
        path: 'profile',
        name: 'profile',
        component: () => import('@/pages/ProfilePage.vue'),
        meta: { title: 'User Settings' },
      },
      {
        path: 'audit',
        name: 'audit',
        component: () => import('@/pages/AuditPage.vue'),
        meta: { title: 'Audit', admin: true },
      },
    ],
  },
  {
    path: '/:catchAll(.*)*',
    name: 'not-found',
    component: () => import('@/pages/NotFoundPage.vue'),
    meta: { public: true, title: 'Not found' },
  },
];

export default routes;
