import { defineBoot } from '@quasar/app-vite';
import { useUiStore } from '@/stores/theme';

/** Apply the saved light/dark preference (default: follow the OS, Quasar `dark: 'auto'`). */
export default defineBoot(({ store }) => {
  useUiStore(store).apply();
});
