/** Zone-restricted items: red "Unavailable" badge, no launch icon, and clicking never copies or opens. */
import { flushPromises, mount } from '@vue/test-utils';
import { Notify, Quasar } from 'quasar';
import type * as Quasarlib from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ItemView } from '@/api/catalog';
import ItemLauncher from '@/components/dashboard/ItemLauncher.vue';

const copy = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
vi.mock('quasar', async (orig) => ({ ...(await orig<typeof Quasarlib>()), copyToClipboard: copy }));

const item = (reachable: boolean): ItemView => ({
  id: 'i1',
  title: 'core-rtr-01',
  protocol: 'SSH',
  target: 'rtr.example.net:22',
  site: 'S1',
  scope: 'GLOBAL',
  zone_names: [],
  tags: [],
  reachable,
  unreachable_reason: reachable ? null : 'Not reachable from zone Default',
  launch: { kind: 'COPY', command: 'ssh jdoe@rtr.example.net -p 22', uri: 'panic-ssh://jdoe@rtr.example.net:22' },
});

const mountItem = (reachable: boolean) =>
  mount(ItemLauncher, {
    props: { item: item(reachable) },
    global: { plugins: [[Quasar, { plugins: { Notify } }]] },
  });

describe('ItemLauncher', () => {
  beforeEach(() => copy.mockClear());

  it('unreachable: Unavailable badge, no launch icon, click copies nothing', async () => {
    const w = mountItem(false);
    expect(w.text()).toContain('Unavailable');
    expect(w.find('[aria-label="Open in SSH client"]').exists()).toBe(false);
    await w.find('[data-testid="item-unavailable"]').trigger('click');
    await flushPromises();
    expect(copy).not.toHaveBeenCalled();
  });

  it('reachable: launch icon shown and click copies the command', async () => {
    const w = mountItem(true);
    expect(w.text()).not.toContain('Unavailable');
    expect(w.find('[aria-label="Open in SSH client"]').exists()).toBe(true);
    await w.find('[data-testid="item-launch"]').trigger('click');
    await flushPromises();
    expect(copy).toHaveBeenCalledWith('ssh jdoe@rtr.example.net -p 22');
  });
});
