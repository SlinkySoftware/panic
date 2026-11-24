/** Catalog item modal: SSH / RDP exclude each other, and a copy saves as a new item only once changed. */
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { Dialog, Notify, Quasar } from 'quasar';
import type * as CatalogApi from '@/api/catalog';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CatalogItemDialog from '@/components/catalog/CatalogItemDialog.vue';

vi.mock('@/api/catalog', async (orig) => ({
  ...(await orig<typeof CatalogApi>()),
  getCatalogItem: vi.fn(),
  createCatalogItem: vi.fn().mockResolvedValue({}),
  updateCatalogItem: vi.fn().mockResolvedValue({}),
  previewCatalogItem: vi.fn().mockResolvedValue(null),
}));

const source: CatalogApi.CatalogItem = {
  id: 'i1',
  title: 'core-rtr-01',
  description: '',
  host: 'rtr.example.net',
  connections: [
    { protocol: 'SSH', port: null, path_or_args: '-A', custom_uri: '' },
    { protocol: 'URL', port: 8443, path_or_args: '/ui', custom_uri: '' },
  ],
  site: 'S1',
  account_override: '',
  tags: [],
  scope: 'PERSONAL',
  team_ids: [],
  owner_usernames: ['jdoe'],
  zone_ids: [],
  version: 3,
  can_edit: true,
};

async function open(props: { itemId: string | null; copy?: boolean }) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const wrapper = mount(CatalogItemDialog, {
    props: { modelValue: false, sites: ['S1'], teams: [], zones: [], ...props },
    global: { plugins: [pinia, [Quasar, { plugins: { Dialog, Notify } }]] },
    attachTo: document.body,
  });
  await wrapper.setProps({ modelValue: true });
  await flushPromises();
  return wrapper;
}

const checkbox = (p: string) => document.querySelector(`[data-testid="protocol-${p}"]`) as HTMLElement;
const isDisabled = (p: string) => checkbox(p).classList.contains('disabled');
const saveButton = () =>
  [...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'Save') as HTMLButtonElement;

describe('CatalogItemDialog', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.clearAllMocks();
  });

  it('SSH and RDP are mutually exclusive; URL combines with either', async () => {
    await open({ itemId: null });
    expect(isDisabled('RDP')).toBe(true); // SSH is checked by default
    expect(isDisabled('URL')).toBe(false);
    checkbox('SSH').click();
    await flushPromises();
    expect(isDisabled('RDP')).toBe(false);
    checkbox('RDP').click();
    await flushPromises();
    expect(isDisabled('SSH')).toBe(true);
  });

  it('a copy keeps every field, waits for a change, then creates a new item', async () => {
    const api = await import('@/api/catalog');
    vi.mocked(api.getCatalogItem).mockResolvedValue(source);
    await open({ itemId: 'i1', copy: true });
    expect(document.body.textContent).toContain('Copy item');
    expect(saveButton().disabled).toBe(true);

    const title = document.querySelector('input[aria-label="Title"]') as HTMLInputElement;
    title.value = 'core-rtr-02';
    title.dispatchEvent(new Event('input'));
    await flushPromises();
    expect(saveButton().disabled).toBe(false);

    const form = document.querySelector('[data-testid="catalog-item-form"]') as HTMLFormElement;
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await flushPromises();
    await new Promise((r) => setTimeout(r, 0));
    expect(api.updateCatalogItem).not.toHaveBeenCalled();
    expect(api.createCatalogItem).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'core-rtr-02',
        host: 'rtr.example.net',
        connections: [
          { protocol: 'SSH', port: null, path_or_args: '-A', custom_uri: '' },
          { protocol: 'URL', port: 8443, path_or_args: '/ui', custom_uri: '' },
        ],
      }),
    );
  });
});
