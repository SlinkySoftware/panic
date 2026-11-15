/** SSH presets: picking, detecting Custom after an edit, and the preview. */
import { describe, expect, it } from 'vitest';
import { CUSTOM, SSH_PRESETS, presetFor, previewSsh } from '@/components/profile/sshPresets';

describe('ssh presets', () => {
  it('recognises every preset, ignoring extra whitespace', () => {
    for (const p of SSH_PRESETS) expect(presetFor(`  ${p.template.replace(/ /g, '  ')} `)).toBe(p.id);
  });

  it('treats an edited template as custom', () => {
    expect(presetFor('ssh {user}@{host} -p {port} -A {flags}')).toBe(CUSTOM);
    expect(presetFor('')).toBe(CUSTOM);
  });

  it('previews with sample values and collapses an empty {flags}', () => {
    expect(previewSsh('ssh {user}@{host} -p {port} {flags}')).toBe('ssh jdoe@rtr01.example.net -p 22');
    expect(previewSsh('putty.exe -ssh {user}@{host} -P {port}')).toBe('putty.exe -ssh jdoe@rtr01.example.net -P 22');
  });
});
