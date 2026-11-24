/** User edit: Super admin is offered only to super admins; the bootstrap admin is read-only for regular admins. */
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { Dialog, Notify, Quasar } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type * as UsersApi from '@/api/users';
import { defineComponent, h } from 'vue';
import type { UserDetail } from '@/api/users';
import UserEditPage from '@/pages/UserEditPage.vue';
import { useSessionStore } from '@/stores/session';

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/api/admin', () => ({ listCodeNamed: vi.fn().mockResolvedValue([]) }));
vi.mock('@/api/users', async (orig) => ({
  ...(await orig<typeof UsersApi>()),
  getUser: vi.fn(),
  updateUser: vi.fn().mockResolvedValue({}),
}));

const user = (over: Partial<UserDetail> = {}): UserDetail => ({
  id: 'u2',
  username: 'riley',
  display_name: 'Riley',
  auth_source: 'LDAP',
  permissions: ['GLOBAL_ADMIN'],
  team_ids: [],
  disabled: false,
  last_login_at: null,
  version: 4,
  bootstrap_admin: false,
  can_edit: true,
  owned_counts: { catalog: 0, lists: 0, dashboards: 0 },
  ...over,
});

async function mountAs(superAdmin: boolean, target: UserDetail) {
  const api = await import('@/api/users');
  vi.mocked(api.getUser).mockResolvedValue(target);
  const pinia = createPinia();
  setActivePinia(pinia);
  const session = useSessionStore();
  session.bootstrap = {
    me: { id: 'u1', username: 'admin' },
    permissions: { global_admin: true, super_admin: superAdmin, can_view_as: false },
    nav: { dashboards: [] },
  } as unknown as typeof session.bootstrap;
  const wrapper = mount(UserEditPage, {
    props: { id: target.id },
    global: {
      plugins: [pinia, [Quasar, { plugins: { Dialog, Notify } }]],
      stubs: {
        QPage: defineComponent({
          setup:
            (_p, { slots }) =>
            () =>
              h('div', slots.default?.()),
        }),
        RouterLink: true,
      },
    },
    attachTo: document.body,
  });
  await flushPromises();
  return wrapper;
}

const permissionLabels = () =>
  [...document.querySelectorAll('[data-testid="user-permissions"] .q-checkbox__label')].map((e) => e.textContent);

describe('UserEditPage', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.clearAllMocks();
  });

  it('a regular admin is not offered Super admin', async () => {
    const w = await mountAs(false, user());
    expect(permissionLabels()).not.toContain('Super admin');
    expect(permissionLabels()).toContain('Global Admin');
    w.unmount();
  });

  it('a super admin is offered Super admin', async () => {
    const w = await mountAs(true, user());
    expect(permissionLabels()).toContain('Super admin');
    w.unmount();
  });

  it('can_edit=false: the bootstrap admin is read-only with an explanation', async () => {
    const w = await mountAs(false, user({ username: 'admin', bootstrap_admin: true, can_edit: false }));
    expect(document.querySelector('[data-testid="user-read-only"]')?.textContent).toContain(
      'Only super admins can edit the bootstrap admin.',
    );
    expect(document.body.textContent).toContain('Bootstrap admin');
    const checkboxes = document.querySelectorAll('[data-testid="user-permissions"] .q-checkbox');
    expect(checkboxes.length).toBeGreaterThan(0);
    for (const c of checkboxes) expect(c.classList.contains('disabled')).toBe(true);
    const save = [...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'Save');
    expect((save as HTMLButtonElement).disabled).toBe(true);
    w.unmount();
  });
});
