/** SSH URI handler setup: the URL is only ever a -File argument, and both clients get the right command. */
import { describe, expect, it } from 'vitest';
import { handlerExample, handlerScript, removeCommand, setupCommand } from '@/components/profile/sshHandler';

describe('ssh handler commands', () => {
  it('passes the URL as a -File argument, never inside PowerShell code', () => {
    const setup = setupCommand('putty', 'panic-ssh');
    expect(setup).toContain(`-File "' + $f + '" "%1"`);
    expect(handlerScript('putty', 'panic-ssh')).not.toContain('%1');
    expect(setup).toContain('HKCU:\\Software\\Classes\\panic-ssh');
    expect(setup).not.toMatch(/HKLM|RunAs/);
  });

  it('escapes single quotes when embedding the script', () => {
    const setup = setupCommand('openssh', 'panic-ssh');
    const embedded = setup.split('-Value ')[1]!.split('; New-Item')[0]!;
    expect(embedded.startsWith("'") && embedded.endsWith("'")).toBe(true);
    expect(embedded.slice(1, -1)).not.toMatch(/(^|[^'])'([^']|$)/); // every inner quote is doubled
  });

  it('uses the configured scheme and the chosen client', () => {
    expect(handlerScript('putty', 'corp-ssh')).toContain("'^corp-ssh://");
    expect(handlerScript('putty', 'x')).toContain('putty.exe');
    expect(handlerScript('openssh', 'x')).toContain('ssh.exe');
    expect(handlerExample('openssh', 'panic-ssh').runs).toBe('ssh.exe -p 22 jdoe@rtr01.example.net');
    expect(removeCommand('corp-ssh')).toContain("Classes\\corp-ssh'");
  });
});
