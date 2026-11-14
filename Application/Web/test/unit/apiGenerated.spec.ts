// @vitest-environment node
/** AR-1.7: src/api/generated/openapi.ts must match Documents/Architecture/openapi/server.yaml. */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { generate, OUT_FILE } from '../../scripts/gen-api.mjs';

describe('generated OpenAPI types', () => {
  it('are up to date with the committed spec (run `npm run gen:api` if this fails)', async () => {
    const expected = await generate();
    const committed = readFileSync(OUT_FILE, 'utf8');
    expect(committed === expected, 'src/api/generated/openapi.ts is stale: run `npm run gen:api`').toBe(true);
  });
});
