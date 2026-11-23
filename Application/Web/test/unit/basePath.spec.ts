import { describe, expect, it } from 'vitest';
import { appPath, basePathFrom, BASE_PATH } from '@/api/basePath';

describe('basePathFrom', () => {
  it('reads the prefix from a <base href>', () => {
    expect(basePathFrom('/')).toBe('');
    expect(basePathFrom('/panic/')).toBe('/panic');
    expect(basePathFrom('/ops/panic/')).toBe('/ops/panic');
    expect(basePathFrom(null)).toBe('');
    expect(basePathFrom(undefined)).toBe('');
  });
});

describe('appPath', () => {
  it('puts a path under the prefix', () => {
    expect(appPath('/api/v1/export', '')).toBe('/api/v1/export');
    expect(appPath('/api/v1/export', '/panic')).toBe('/panic/api/v1/export');
    expect(appPath('auth/oidc/login', '/panic')).toBe('/panic/auth/oidc/login');
  });

  it('defaults to the page prefix (none in the test page)', () => {
    expect(BASE_PATH).toBe('');
    expect(appPath('/login')).toBe('/login');
  });
});
