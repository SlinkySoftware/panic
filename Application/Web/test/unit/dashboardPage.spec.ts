/** The dashboard reloads when View As changes the perspective, even on the same dashboard route. */
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { Notify, Quasar } from 'quasar';
import { describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import DashboardPage from '@/pages/DashboardPage.vue';
import { useSessionStore } from '@/stores/session';

vi.mock('@/api/dashboards', () => ({
  getDashboardView: vi.fn().mockResolvedValue(null),
  pinDashboard: vi.fn(),
  unpinDashboard: vi.fn(),
  setMyDefaultDashboard: vi.fn(),
}));

const bootstrapFor = (zoneId: string) =>
  ({
    me: { id: 'u-admin', username: 'admin' },
    client: { ip: '192.0.2.1', zone: { id: zoneId, name: zoneId }, zone_source: 'VIEW_AS' },
    nav: { dashboards: [] },
  }) as unknown as ReturnType<typeof useSessionStore>['bootstrap'];

describe('DashboardPage', () => {
  it('reloads the same dashboard when the View As zone changes', async () => {
    const api = await import('@/api/dashboards');
    const pinia = createPinia();
    setActivePinia(pinia);
    const session = useSessionStore();
    session.bootstrap = bootstrapFor('zone-default');
    mount(DashboardPage, {
      props: { id: 'd1' },
      global: {
        plugins: [pinia, [Quasar, { plugins: { Notify } }]],
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
    });
    await flushPromises();
    expect(api.getDashboardView).toHaveBeenCalledTimes(1);

    session.bootstrap = bootstrapFor('zone-dmz'); // View As a zone, still on /dashboard/d1
    await flushPromises();
    expect(api.getDashboardView).toHaveBeenCalledTimes(2);
    expect(api.getDashboardView).toHaveBeenLastCalledWith('d1');
  });
});
