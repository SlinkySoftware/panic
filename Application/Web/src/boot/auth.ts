import { defineBoot } from '@quasar/app-vite';
import { Notify } from 'quasar';
import { setUnauthorizedHandler } from '@/api/http';
import { loginLocation } from '@/router/guard';
import { useSessionStore } from '@/stores/session';

/**
 * Session expiry ("401 -> /login?next=..."): when any non-auth API call returns 401, re-check the session. If
 * it is gone, clear it locally and go to /login with `next` back to the current page. Guarded on
 * `session.isAuthenticated` so an anonymous page's own bootstrap 401 (expected, not an expiry) is a no-op here
 * -- the router guard is what sends anonymous visitors to /login.
 */
export default defineBoot(({ router, store }) => {
  const session = useSessionStore(store);
  let checking = false;
  setUnauthorizedHandler(() => {
    if (checking || !session.isAuthenticated) return;
    checking = true;
    void session
      .fetchBootstrap()
      .then(async (bootstrap) => {
        if (bootstrap) return;
        session.clear();
        Notify.create({ type: 'warning', message: 'Your session has ended. Please sign in again.' });
        await router.push(loginLocation(router.currentRoute.value.fullPath));
      })
      .catch(() => undefined)
      .finally(() => {
        checking = false;
      });
  });
});
