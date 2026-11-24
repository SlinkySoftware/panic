/** Application Settings: settings are super-admin only, and config import previews, confirms, then applies. */
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { Dialog, Notify, Quasar } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type * as ConfigApi from '@/api/config';
import { defineComponent, h } from 'vue';
import SettingsPage from '@/pages/SettingsPage.vue';
import { useSessionStore } from '@/stores/session';

vi.mock('@/api/settings', () => ({
  getSettings: vi.fn().mockResolvedValue({
    default_global_dashboard: null,
    ssh_uri_enabled: true,
    ssh_uri_scheme: 'panic-ssh',
    version: 1,
  }),
  updateSettings: vi.fn(),
}));
vi.mock('@/api/dashboards', () => ({ listDashboards: vi.fn().mockResolvedValue({ results: [] }) }));
vi.mock('@/api/config', async (orig) => ({
  ...(await orig<typeof ConfigApi>()),
  previewConfigImport: vi.fn(),
  applyConfigImport: vi.fn(),
}));

const empty = { added: 0, changed: 0, unchanged: 0, conflicts: 0 };
const preview = {
  plan_digest: 'abc123',
  summary: {
    sites: { ...empty, added: 1 },
    teams: empty,
    zones: empty,
    catalog: { ...empty, changed: 1, conflicts: 1 },
    lists: empty,
  },
  changes: [
    { section: 'sites', action: 'ADD', id: 's1', label: 'SYD' },
    { section: 'catalog', action: 'UPDATE', id: 'c1', label: 'core-rtr-01', fields: ['host', 'tags'] },
    { section: 'catalog', action: 'CONFLICT', id: 'c2', label: 'lab 1', reason: 'matches 2 existing items' },
  ],
  warnings: ['List "Core" references 1 unknown item; it is dropped.'],
};

async function mountAs(superAdmin: boolean) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const session = useSessionStore();
  session.bootstrap = {
    me: { id: 'u1', username: 'admin' },
    permissions: { global_admin: true, super_admin: superAdmin },
    nav: { dashboards: [] },
  } as unknown as typeof session.bootstrap;
  vi.spyOn(session, 'fetchBootstrap').mockResolvedValue(null);
  const wrapper = mount(SettingsPage, {
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

function disabled(testid: string): boolean {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  expect(el).not.toBeNull();
  return !!el!.closest('.q-field--disabled, .q-toggle.disabled, .disabled');
}

describe('SettingsPage', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.clearAllMocks();
  });

  it('a regular admin sees settings read-only and no config card', async () => {
    const w = await mountAs(false);
    expect(document.querySelector('[data-testid="settings-read-only"]')).not.toBeNull();
    expect(disabled('ssh-uri-enabled')).toBe(true);
    expect(disabled('default-dashboard')).toBe(true);
    expect(document.querySelector('[data-testid="config-card"]')).toBeNull();
    expect(w.text()).not.toContain('Download everything as portable JSON'); // the old export link is gone
    w.unmount();
  });

  it('a super admin can edit settings and export config', async () => {
    const w = await mountAs(true);
    expect(document.querySelector('[data-testid="settings-read-only"]')).toBeNull();
    expect(disabled('ssh-uri-enabled')).toBe(false);
    expect(disabled('default-dashboard')).toBe(false);
    const exp = document.querySelector('[data-testid="config-export"]') as HTMLAnchorElement;
    expect(exp.getAttribute('href')).toBe('/api/v1/admin/config/export');
    w.unmount();
  });

  it('import: preview lists changes, confirm, then applies with the plan digest', async () => {
    const api = await import('@/api/config');
    vi.mocked(api.previewConfigImport).mockResolvedValue(
      preview as Awaited<ReturnType<typeof api.previewConfigImport>>,
    );
    vi.mocked(api.applyConfigImport).mockResolvedValue({ summary: preview.summary, warnings: [] });
    const w = await mountAs(true);

    const doc = { format: 'panic-config', sites: [] };
    const input = document.querySelector('[data-testid="config-file"]') as HTMLInputElement;
    const file = new File([JSON.stringify(doc)], 'panic-config.json', { type: 'application/json' });
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    input.dispatchEvent(new Event('change'));
    await flushPromises();
    await new Promise((r) => setTimeout(r, 0));
    await flushPromises();

    expect(api.previewConfigImport).toHaveBeenCalledWith(doc);
    expect(document.querySelectorAll('[data-testid="config-change"]').length).toBe(3);
    expect(document.body.textContent).toContain('Changes: host, tags');
    expect(document.body.textContent).toContain('Skipped: matches 2 existing items');
    expect(document.body.textContent).toContain('references 1 unknown item');
    const apply = document.querySelector('[data-testid="config-apply"]') as HTMLButtonElement;
    expect(apply.textContent).toContain('Import 2 changes'); // conflicts are not applied
    expect(api.applyConfigImport).not.toHaveBeenCalled();

    apply.click();
    await flushPromises();
    expect(document.body.textContent).toContain('Apply 2 changes? Nothing is deleted.');
    const ok = [...document.querySelectorAll('.q-dialog button')].find((b) => b.textContent?.trim() === 'Import');
    (ok as HTMLButtonElement).click();
    await flushPromises();
    expect(api.applyConfigImport).toHaveBeenCalledWith(doc, 'abc123');
    w.unmount();
  });

  it('import: an invalid JSON file shows an error and calls nothing', async () => {
    const api = await import('@/api/config');
    const w = await mountAs(true);
    const input = document.querySelector('[data-testid="config-file"]') as HTMLInputElement;
    Object.defineProperty(input, 'files', { value: [new File(['{nope'], 'bad.json')], configurable: true });
    input.dispatchEvent(new Event('change'));
    await flushPromises();
    await new Promise((r) => setTimeout(r, 0));
    await flushPromises();
    expect(document.body.textContent).toContain('bad.json is not valid JSON.');
    expect(api.previewConfigImport).not.toHaveBeenCalled();
    w.unmount();
  });
});
