/**
 * Density and theme toggles for the top bar (this task's scope line). Persisted to `LocalStorage` on the
 * browser; not yet synced to the server-side `me.prefs` (that is `PATCH /api/v1/me`, a later task).
 */
import { defineStore } from 'pinia';
import { Dark, LocalStorage } from 'quasar';
import { computed, ref } from 'vue';

export type ThemeMode = 'auto' | 'light' | 'dark';
export type Density = 'COMFORT' | 'COMPACT';

const THEME_KEY = 'panic.theme';
const DENSITY_KEY = 'panic.density';
const THEME_ORDER: readonly ThemeMode[] = ['auto', 'light', 'dark'];
const THEME_ICONS: Record<ThemeMode, string> = {
  auto: 'brightness_auto',
  light: 'light_mode',
  dark: 'dark_mode',
};

function isThemeMode(v: unknown): v is ThemeMode {
  return typeof v === 'string' && (THEME_ORDER as readonly string[]).includes(v);
}

function isDensity(v: unknown): v is Density {
  return v === 'COMFORT' || v === 'COMPACT';
}

export const useUiStore = defineStore('ui', () => {
  const storedTheme: unknown = LocalStorage.getItem(THEME_KEY);
  const theme = ref<ThemeMode>(isThemeMode(storedTheme) ? storedTheme : 'auto');
  const storedDensity: unknown = LocalStorage.getItem(DENSITY_KEY);
  const density = ref<Density>(isDensity(storedDensity) ? storedDensity : 'COMFORT');

  const themeIcon = computed(() => THEME_ICONS[theme.value]);
  const themeLabel = computed(() => `Theme: ${theme.value} (click to change)`);
  const densityIcon = computed(() => (density.value === 'COMPACT' ? 'density_small' : 'density_medium'));
  const densityLabel = computed(() => `Density: ${density.value.toLowerCase()} (click to change)`);

  /** Apply the saved light/dark preference (default: follow the OS, Quasar `dark: 'auto'`). */
  function apply(): void {
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

  function setDensity(next: Density): void {
    density.value = next;
    LocalStorage.set(DENSITY_KEY, next);
  }

  function toggleDensity(): void {
    setDensity(density.value === 'COMFORT' ? 'COMPACT' : 'COMFORT');
  }

  return {
    theme,
    density,
    themeIcon,
    themeLabel,
    densityIcon,
    densityLabel,
    apply,
    setTheme,
    cycleTheme,
    setDensity,
    toggleDensity,
  };
});
