/**
 * Per-user SSH URI handler setup (Windows, no admin rights): PowerShell one-liners that write a small
 * validating handler script to %LOCALAPPDATA%\PANIC and register `<scheme>://` under HKCU\Software\Classes.
 *
 * Security: the browser passes the raw URL as %1. It reaches the script only as a `-File` argument, i.e. a
 * plain string that PowerShell never parses as code, and the script launches the client only when the URL
 * matches `<scheme>://user@host:port` exactly (no leading '-', no spaces or quotes). Only cmdlets and
 * operators are used, so it also runs under Constrained Language Mode.
 */
export type HandlerClient = 'putty' | 'openssh';

export const HANDLER_CLIENTS: { value: HandlerClient; label: string }[] = [
  { value: 'putty', label: 'PuTTY (putty.exe on PATH)' },
  { value: 'openssh', label: 'OpenSSH (Windows built-in ssh.exe)' },
];

const DIR = '$env:LOCALAPPDATA\\PANIC';
const SCRIPT = 'panic-ssh.ps1';

/** The handler script, as one PowerShell line (statements separated by `;`). */
export function handlerScript(client: HandlerClient, scheme: string): string {
  const launch =
    client === 'putty'
      ? "$exe = 'putty.exe'; $argv = @('-ssh', ($u + '@' + $h), '-P', [string]$p)"
      : "$exe = 'ssh.exe'; $argv = @('-p', [string]$p, ($u + '@' + $h))";
  return [
    "param([string]$Uri = '')",
    `$pattern = '^${scheme}://([A-Za-z0-9][A-Za-z0-9._-]{0,63})@([A-Za-z0-9][A-Za-z0-9.-]{0,252}|\\[[0-9A-Fa-f:]{2,45}\\]):([0-9]{1,5})/?$'`,
    '$m = [regex]::Match($Uri, $pattern)',
    'if (-not $m.Success) { exit 2 }',
    '$u = $m.Groups[1].Value; $h = $m.Groups[2].Value; $p = [int]$m.Groups[3].Value',
    'if ($p -lt 1 -or $p -gt 65535) { exit 2 }',
    launch,
    "if ($env:PANIC_SSH_DRYRUN) { Write-Output ($exe + ' ' + ($argv -join ' ')); exit 0 }",
    'Start-Process -FilePath $exe -ArgumentList $argv',
  ].join('; ');
}

const psQuote = (s: string) => `'${s.replace(/'/g, "''")}'`;

/** One line to paste into PowerShell: writes the script, then registers the scheme for this user only. */
export function setupCommand(client: HandlerClient, scheme: string): string {
  const key = `HKCU:\\Software\\Classes\\${scheme}`;
  const handlerCmd = `'powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $f + '" "%1"'`;
  return [
    `$d = "${DIR}"`,
    'New-Item -ItemType Directory -Force -Path $d | Out-Null',
    `$f = Join-Path $d '${SCRIPT}'`,
    `Set-Content -LiteralPath $f -Encoding UTF8 -Value ${psQuote(handlerScript(client, scheme))}`,
    `New-Item -Force -Path '${key}\\shell\\open\\command' | Out-Null`,
    `Set-ItemProperty -Path '${key}' -Name '(default)' -Value 'URL:PANIC SSH'`,
    `Set-ItemProperty -Path '${key}' -Name 'URL Protocol' -Value ''`,
    `Set-ItemProperty -Path '${key}\\shell\\open\\command' -Name '(default)' -Value (${handlerCmd})`,
    `Write-Output 'PANIC SSH handler installed for ${scheme}://'`,
  ].join('; ');
}

/** Undo setupCommand: removes the per-user scheme registration and the script folder. */
export function removeCommand(scheme: string): string {
  return [
    `Remove-Item -Recurse -Force -ErrorAction SilentlyContinue -Path 'HKCU:\\Software\\Classes\\${scheme}'`,
    `Remove-Item -Recurse -Force -ErrorAction SilentlyContinue -Path "${DIR}"`,
    `Write-Output 'PANIC SSH handler removed'`,
  ].join('; ');
}

/** Example of what the handler runs for a sample link, for the instructions. */
export function handlerExample(client: HandlerClient, scheme: string): { uri: string; runs: string } {
  const uri = `${scheme}://jdoe@rtr01.example.net:22`;
  const runs =
    client === 'putty' ? 'putty.exe -ssh jdoe@rtr01.example.net -P 22' : 'ssh.exe -p 22 jdoe@rtr01.example.net';
  return { uri, runs };
}
