/**
 * Launch an item from its server-built `launch` (API.md §4.2): OPEN a URL, COPY a command (SSH / local app),
 * or DOWNLOAD an .rdp file. Quasar's copyToClipboard also works outside secure contexts (plain-HTTP dev access).
 */
import { copyToClipboard, useQuasar } from 'quasar';
import type { ItemView, Launch } from '@/api/catalog';

export function useLaunch() {
  const $q = useQuasar();

  /** Launch the item's primary connection, or `l` (one of its `alt_launches`). */
  async function launch(item: ItemView, l: Launch | undefined = item.launch): Promise<void> {
    // Zone-restricted items never launch, whatever the entry point (widget, list, palette).
    if (!item.reachable) {
      $q.notify({
        type: 'warning',
        message: `${item.title} is unavailable from your zone`,
        ...(item.unreachable_reason ? { caption: item.unreachable_reason } : {}),
      });
      return;
    }
    if (!l) return;
    if (l.kind === 'OPEN' && l.url) {
      window.open(l.url, '_blank', 'noopener');
    } else if (l.kind === 'DOWNLOAD' && l.href) {
      const a = document.createElement('a');
      a.href = l.href;
      a.download = '';
      a.click();
    } else if (l.kind === 'COPY' && l.command) {
      try {
        await copyToClipboard(l.command);
        $q.notify({ type: 'positive', message: 'Command copied', caption: l.command, timeout: 2500 });
      } catch {
        $q.notify({ type: 'negative', message: 'Could not copy to the clipboard', caption: l.command });
      }
    }
  }

  /** Secondary action for COPY launches that also expose a URI (e.g. ssh://), opened by the OS handler. */
  function openUri(item: ItemView, l: Launch | undefined = item.launch): void {
    if (item.reachable && l?.uri) window.location.href = l.uri;
  }

  return { launch, openUri };
}
