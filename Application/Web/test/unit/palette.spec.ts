/** T-S6-09: palette keyboard handling. */
import { describe, expect, it } from 'vitest';
import { isPaletteShortcut } from '@/components/palette/shortcut';

const key = (k: string, mods: Partial<KeyboardEvent> = {}, target: EventTarget | null = document.body) => ({
  key: k,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  target,
  ...mods,
});

describe('isPaletteShortcut', () => {
  it('opens on Ctrl+K and Cmd+K, even inside a field', () => {
    const input = document.createElement('input');
    expect(isPaletteShortcut(key('k', { ctrlKey: true }, input))).toBe(true);
    expect(isPaletteShortcut(key('K', { metaKey: true }))).toBe(true);
  });

  it('opens on "/" only outside text fields', () => {
    expect(isPaletteShortcut(key('/'))).toBe(true);
    expect(isPaletteShortcut(key('/', {}, document.createElement('input')))).toBe(false);
    expect(isPaletteShortcut(key('/', {}, document.createElement('textarea')))).toBe(false);
  });

  it('ignores other keys and modified slashes', () => {
    expect(isPaletteShortcut(key('k'))).toBe(false);
    expect(isPaletteShortcut(key('/', { altKey: true }))).toBe(false);
  });
});
