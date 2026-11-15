/**
 * SSH client presets for the Profile page. Templates use the server's placeholders ({user} {host} {port}
 * {flags}, panic_common.launchers.interpolate_ssh_template). PuTTY and Plink take the port as capital -P and
 * have no {flags} equivalent. Bare executable names: the client must be on the user's PATH.
 */
export interface SshPreset {
  id: string;
  label: string;
  template: string;
}

export const CUSTOM = 'custom';

export const SSH_PRESETS: readonly SshPreset[] = [
  { id: 'openssh', label: 'OpenSSH (ssh)', template: 'ssh {user}@{host} -p {port} {flags}' },
  { id: 'putty', label: 'PuTTY', template: 'putty.exe -ssh {user}@{host} -P {port}' },
  { id: 'plink', label: 'Plink (PuTTY command line)', template: 'plink.exe -ssh {user}@{host} -P {port}' },
  { id: 'wt', label: 'Windows Terminal + OpenSSH', template: 'wt ssh {user}@{host} -p {port} {flags}' },
];

const norm = (t: string) => t.trim().replace(/\s+/g, ' ');

/** The preset whose template matches (ignoring extra whitespace), else "custom". */
export function presetFor(template: string): string {
  const t = norm(template);
  return SSH_PRESETS.find((p) => norm(p.template) === t)?.id ?? CUSTOM;
}

/** Client-side preview with sample values, mirroring the server's interpolation (empty {flags} collapses). */
export function previewSsh(template: string, sample = { user: 'jdoe', host: 'rtr01.example.net', port: '22' }): string {
  return norm(
    (template || SSH_PRESETS[0]!.template)
      .replaceAll('{user}', sample.user)
      .replaceAll('{host}', sample.host)
      .replaceAll('{port}', sample.port)
      .replaceAll('{flags}', ''),
  );
}
