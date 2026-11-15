/**
 * Theme toggle for the top bar, persisted to `LocalStorage` per browser. (The old density toggle was
 * removed: it never changed the layout, which is always compact.)
 */
import { defineStore } from 'pinia';
import { Dark, LocalStorage } from 'quasar';
import { computed, ref } from 'vue';

export type ThemeMode = 'auto' | 'light' | 'dark';

const THEME_KEY = 'panic.theme';
const THEME_ORDER: readonly ThemeMode[] = ['auto', 'light', 'dark'];
const THEME_ICONS: Record<ThemeMode, string> = {
  auto: 'brightness_auto',
  light: 'light_mode',
  dark: 'dark_mode',
};

function isThemeMode(v: unknown): v is ThemeMode {
  return typeof v === 'string' && (THEME_ORDER as readonly string[]).includes(v);
}

export const useUiStore = defineStore('ui', () => {
  const storedTheme: unknown = LocalStorage.getItem(THEME_KEY);
  const theme = ref<ThemeMode>(isThemeMode(storedTheme) ? storedTheme : 'auto');

  const themeIcon = computed(() => THEME_ICONS[theme.value]);
  const themeLabel = computed(() => `Theme: ${theme.value} (click to change)`);

  /** Apply the saved light/dark preference (default: follow the OS, Quasar `dark: 'auto'`). */
  function apply(): void {
    LocalStorage.remove('panic.density'); // leftover from the removed density toggle
    Dark.set(theme.value === 'auto' ? 'auto' : theme.value === 'dark');
  }

  function setTheme(next: ThemeMode): void {
    theme.value = next;
    LocalStorage.set(THEME_KEY, next);
    apply();
  }

  function cycleTheme(): void {
    setTheme(THEME_ORDER[(THEME_ORDER.indexOf(theme.value) + 1) % THEME_ORDER.length] ?? 'auto');
  }

  return {
    theme,
    themeIcon,
    themeLabel,
    apply,
    setTheme,
    cycleTheme,
  };
});
