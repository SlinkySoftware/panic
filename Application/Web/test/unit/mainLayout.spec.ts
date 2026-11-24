/** The version label sits above the menu pin and shows only while the menu is pinned open. */
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { Dialog, LocalStorage, Notify, Quasar } from 'quasar';
import { beforeEach, describe, expect, it } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';
import MainLayout from '@/layouts/MainLayout.vue';
import { useSessionStore } from '@/stores/session';

// QLayout observes its size; jsdom has no ResizeObserver.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

async function mountLayout() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const session = useSessionStore();
  session.bootstrap = {
    instance: { name: 'PANIC', version: '9.8.7' },
    me: { id: 'u1', username: 'jdoe', display_name: 'J Doe' },
    permissions: { global_admin: false, can_add_global: false, can_add_team: false, can_view_as: false },
    client: { ip: '192.0.2.1', zone: null, zone_source: 'DEFAULT' },
    nav: { dashboards: [] },
  } as unknown as typeof session.bootstrap;
  const Empty = defineComponent({ render: () => h('div') });
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:any(.*)*', name: 'root', component: Empty }],
  });
  await router.push('/');
  const wrapper = mount(MainLayout, {
    global: {
      plugins: [pinia, router, [Quasar, { plugins: { Dialog, Notify } }]],
      stubs: { AddDashboardDialog: true, ViewAsDialog: true, CommandPalette: true },
    },
    attachTo: document.body,
  });
  await flushPromises();
  return wrapper;
}

describe('MainLayout version label', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    LocalStorage.clear();
  });

  it('shows the version only while the menu is pinned', async () => {
    const wrapper = await mountLayout();
    const version = () => document.querySelector('[data-testid="nav-version"]');
    expect(version()).toBeNull(); // unpinned by default

    (document.querySelector('[data-testid="nav-pin"]') as HTMLElement).click();
    await flushPromises();
    expect(version()?.textContent?.trim()).toBe('v9.8.7');

    (document.querySelector('[data-testid="nav-pin"]') as HTMLElement).click();
    await flushPromises();
    expect(version()).toBeNull();
    wrapper.unmount();
  });
});
