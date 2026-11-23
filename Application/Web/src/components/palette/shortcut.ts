/** Palette shortcut: Ctrl/Cmd+K anywhere; `/` only when the user is not typing in a field. */
export function isPaletteShortcut(
  e: Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'altKey' | 'target'>,
): boolean {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') return true;
  if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return false;
  const t = e.target as HTMLElement | null;
  return !(t && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName)));
}
