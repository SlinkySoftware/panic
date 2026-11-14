/**
 * The nav rail's static groups (UI_DESIGN.md §2): Resources, Scope & Admin, System. The Dashboards group is
 * built separately, straight from `session.navDashboards` (MainLayout.vue), since it is per-user and dynamic.
 *
 * `/rbac` is deliberately not listed here: it is a redirect-only legacy route (AR-1.4); "Users" below links to
 * its real destination, `/settings/users`.
 */
export interface NavLink {
  name: string;
  to: { name: string };
  title: string;
  icon: string;
  /** `GLOBAL_ADMIN` only; hidden from a standard user's rail (the route itself also guards this). */
  admin?: boolean;
}

export interface NavGroup {
  title: string;
  links: readonly NavLink[];
}

export const NAV_GROUPS: readonly NavGroup[] = [
  {
    title: 'Resources',
    links: [
      { name: 'catalog', to: { name: 'catalog' }, title: 'Catalog', icon: 'apps' },
      { name: 'lists', to: { name: 'lists' }, title: 'Endpoint lists', icon: 'list_alt' },
    ],
  },
  {
    title: 'Scope',
    links: [
      { name: 'sites', to: { name: 'sites' }, title: 'Sites', icon: 'place' },
      { name: 'teams', to: { name: 'teams' }, title: 'Teams', icon: 'groups' },
      { name: 'zones', to: { name: 'zones' }, title: 'Zones', icon: 'security' },
      { name: 'settings-users', to: { name: 'settings-users' }, title: 'Users', icon: 'manage_accounts', admin: true },
    ],
  },
  {
    title: 'System',
    links: [
      { name: 'settings', to: { name: 'settings' }, title: 'Settings', icon: 'settings' },
      { name: 'profile', to: { name: 'profile' }, title: 'Profile', icon: 'account_circle' },
      { name: 'audit', to: { name: 'audit' }, title: 'Audit log', icon: 'history', admin: true },
    ],
  },
];

/** Groups with admin-only links dropped for a standard user; a group left with no links is dropped entirely. */
export function navGroupsFor(isAdmin: boolean): NavGroup[] {
  return NAV_GROUPS.map((g) => ({ ...g, links: g.links.filter((l) => !l.admin || isAdmin) })).filter(
    (g) => g.links.length > 0,
  );
}
