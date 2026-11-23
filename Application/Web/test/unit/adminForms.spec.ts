/** Admin form validation is displayed, and a server field error lands on the right field. */
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { Quasar, Dialog, Notify } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import CodeNamedTable from '@/components/admin/CodeNamedTable.vue';
import { useSessionStore } from '@/stores/session';

vi.mock('@/api/admin', () => ({
  listCodeNamed: vi.fn().mockResolvedValue([]),
  createCodeNamed: vi.fn(),
  updateCodeNamed: vi.fn(),
  deleteCodeNamed: vi.fn(),
}));

async function mountAsAdmin() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const session = useSessionStore();
  // Only permissions.global_admin matters to this component.
  session.bootstrap = { permissions: { global_admin: true } } as unknown as typeof session.bootstrap;
  const wrapper = mount(CodeNamedTable, {
    props: { kind: 'sites', title: 'Sites', noun: 'site' },
    global: {
      plugins: [pinia, [Quasar, { plugins: { Dialog, Notify } }]],
      // QPage only renders inside a QLayout; the form is what is under test.
      stubs: {
        QPage: defineComponent({
          setup:
            (_p, { slots }) =>
            () =>
              h('div', slots.default?.()),
        }),
      },
    },
    attachTo: document.body,
  });
  await flushPromises();
  return wrapper;
}

describe('CodeNamedTable form', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('shows Required on an empty submit and does not call the API', async () => {
    const api = await import('@/api/admin');
    const wrapper = await mountAsAdmin();
    const add = wrapper.findAll('button').find((b) => b.text().includes('Add site'));
    expect(add).toBeDefined();
    await add!.trigger('click');
    await flushPromises();
    const form = document.querySelector('[data-testid="code-named-form"]') as HTMLFormElement;
    expect(form).not.toBeNull();
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await flushPromises();
    await new Promise((r) => setTimeout(r, 0));
    expect(document.body.textContent).toContain('Required');
    expect(api.createCodeNamed).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('puts a server field error on the matching field', async () => {
    const api = await import('@/api/admin');
    const { ApiError } = await import('@/api/http');
    vi.mocked(api.createCodeNamed).mockRejectedValueOnce(
      new ApiError(400, { error_code: 'VALIDATION_ERROR', fields: { code: ['Code already exists.'] } }, null),
    );
    const wrapper = await mountAsAdmin();
    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('Add site'))!
      .trigger('click');
    await flushPromises();
    const inputs = document.querySelectorAll<HTMLInputElement>('[data-testid="code-named-form"] input');
    for (const [i, v] of ['2SYA', 'Sydney'].entries()) {
      inputs[i]!.value = v;
      inputs[i]!.dispatchEvent(new Event('input'));
    }
    await flushPromises();
    document
      .querySelector('[data-testid="code-named-form"]')!
      .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await flushPromises();
    await new Promise((r) => setTimeout(r, 0));
    expect(api.createCodeNamed).toHaveBeenCalledWith('sites', { code: '2SYA', name: 'Sydney', description: '' });
    expect(document.body.textContent).toContain('Code already exists.');
    wrapper.unmount();
  });
});
