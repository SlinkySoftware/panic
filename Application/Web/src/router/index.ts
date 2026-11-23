import { defineRouter } from '@quasar/app-vite';
import { createRouter, createWebHistory } from 'vue-router';
import { BASE_PATH } from '@/api/basePath';
import { useSessionStore } from '@/stores/session';
import { authGuard } from './guard';
import routes from './routes';

export default defineRouter(({ store }) => {
  const router = createRouter({
    scrollBehavior: () => ({ left: 0, top: 0 }),
    routes,
    // The prefix comes from <base href> at run time (one build for every prefix; api/basePath.ts).
    history: createWebHistory(`${BASE_PATH}/`),
  });
  const session = useSessionStore(store);
  router.beforeEach((to) => authGuard(to, session));
  router.afterEach((to) => {
    document.title = to.meta.title ? `${to.meta.title} · PANIC` : 'PANIC';
  });
  return router;
});
