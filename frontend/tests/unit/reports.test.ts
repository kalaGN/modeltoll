import { flushPromises, mount } from '@vue/test-utils';
import { expect, it, vi } from 'vitest';
import { createRouter, createMemoryHistory } from 'vue-router';
import ReportsPage from '../../src/pages/console/ReportsPage.vue';
import * as client from '../../src/api/client';
import type { Summary } from '../../src/api/types';

it('aborts obsolete report requests and never lets older filter results overwrite newer data', async () => {
  const old: { resolve: (value: unknown) => void }[] = [];
  const signals: AbortSignal[] = [];
  const summary = (count: number): Summary => ({ range: { from: '2026-10-17T00:00:00Z', to: '2026-10-20T00:00:00Z' }, totals: { calls_total: count, billing_pending_count: 0 }, series: [] });
  const api = vi.spyOn(client, 'api').mockImplementation(async (path, options) => {
    if (path === '/v1/api-keys') return { items: [] } as never;
    signals.push(options!.signal!);
    if (!path.includes('from=')) return await new Promise<unknown>(resolve => old.push({ resolve })) as never;
    return (path.includes('/summary') ? summary(20) : { items: [], has_more: false }) as never;
  });
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/usage', component: ReportsPage }] });
  await router.push('/usage'); await router.isReady();
  const wrapper = mount(ReportsPage, { global: { plugins: [router] } }); await flushPromises();
  await wrapper.get('#date-from').setValue('2026-10-17'); await wrapper.get('form').trigger('submit'); await flushPromises();
  expect(signals[0]!.aborted).toBe(true); expect(wrapper.get('#stat-calls').text()).toBe('20');
  old[0]!.resolve(summary(1)); old[1]!.resolve({ items: [], has_more: false }); await flushPromises();
  expect(wrapper.get('#stat-calls').text()).toBe('20');
  wrapper.unmount(); api.mockRestore();
});
