/** LIST / HOST widgets hide unavailable items until "Show Unavailable Items" is ticked. */
import { mount } from '@vue/test-utils';
import { Quasar } from 'quasar';
import { describe, expect, it } from 'vitest';
import type { ItemView } from '@/api/catalog';
import type { Widget, WidgetList } from '@/api/dashboards';
import DashboardWidget from '@/components/dashboard/DashboardWidget.vue';

const item = (id: string, reachable: boolean): ItemView => ({
  id,
  title: id,
  protocol: 'SSH',
  protocols: ['SSH'],
  target: `${id}.example.net:22`,
  site: 'S1',
  scope: 'GLOBAL',
  zone_names: [],
  tags: [],
  reachable,
  unreachable_reason: reachable ? null : 'restricted',
  launch: { kind: 'COPY', command: `ssh ${id}` },
});
const items = { a: { ...item('a', true), zone_names: ['Core', 'NOC'] }, b: item('b', false), c: item('c', false) };
const base = { id: 'w', title: '', grid_x: 1, grid_y: 1, grid_w: 4, grid_h: 2 };
const lists: Record<string, WidgetList> = {
  l: { id: 'l', title: 'L', scope: 'GLOBAL', item_count: 3, item_ids: ['a', 'b', 'c'], truncated: false },
};
const mountWidget = (widget: Widget) =>
  mount(DashboardWidget, { props: { widget, items, lists }, global: { plugins: [Quasar] } });

describe('DashboardWidget unavailable items', () => {
  it('LIST: hidden by default, checkbox with count reveals them', async () => {
    const w = mountWidget({ ...base, widget_type: 'LIST', list_id: 'l' });
    expect(w.text()).toContain('a');
    expect(w.findAll('[data-testid="item-unavailable"]')).toHaveLength(0);
    const box = w.find('[data-testid="show-unavailable"]');
    expect(box.text()).toContain('Show Unavailable Items (2)');
    await box.trigger('click');
    expect(w.findAll('[data-testid="item-unavailable"]')).toHaveLength(2);
  });

  it('LIST rows show zone badges; unrestricted items say All zones; HOST rows have none', async () => {
    const w = mountWidget({ ...base, widget_type: 'LIST', list_id: 'l' });
    await w.find('[data-testid="show-unavailable"]').trigger('click');
    const zones = w.findAll('[data-testid="item-zones"]').map((z) => z.text());
    expect(zones).toHaveLength(3);
    expect(zones[0]).toContain('Core');
    expect(zones[0]).toContain('NOC');
    expect(zones.slice(1)).toEqual(['All zones', 'All zones']);
    const host = mountWidget({ ...base, widget_type: 'HOST', catalog_item_id: 'a' });
    expect(host.find('[data-testid="item-zones"]').exists()).toBe(false);
  });

  it('no checkbox when everything is reachable', () => {
    const w = mount(DashboardWidget, {
      props: { widget: { ...base, widget_type: 'HOST', catalog_item_id: 'a' }, items, lists },
      global: { plugins: [Quasar] },
    });
    expect(w.find('[data-testid="show-unavailable"]').exists()).toBe(false);
  });

  it('HOST: an unavailable item is hidden behind the checkbox', async () => {
    const w = mountWidget({ ...base, widget_type: 'HOST', catalog_item_id: 'b' });
    expect(w.find('[data-testid="host-unavailable-hidden"]').exists()).toBe(true);
    await w.find('[data-testid="show-unavailable"]').trigger('click');
    expect(w.find('[data-testid="item-unavailable"]').exists()).toBe(true);
  });
});
