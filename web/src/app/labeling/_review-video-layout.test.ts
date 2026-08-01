import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const ROOT = dirname(fileURLToPath(import.meta.url));

function source(path: string): string {
  return readFileSync(join(ROOT, path), 'utf8');
}

describe('review video desktop width contract', () => {
  it('allows a 220px navigation beside 1200px content', () => {
    const roleShell = source('_role-shell.tsx');

    expect(roleShell).toContain('max-w-[1484px]');
    expect(roleShell).toContain('lg:grid-cols-[220px_minmax(0,1200px)]');
  });

  it('does not keep video detail pages at the old narrow widths', () => {
    const paths = [
      'motion/[clipId]/page.tsx',
      '_blind-review-detail.tsx',
      'blind/conflicts/[clipId]/page.tsx',
      'quarantine/[clipId]/page.tsx',
    ];

    for (const path of paths) {
      const detail = source(path);
      expect(detail, path).toContain('max-w-[1200px]');
      expect(detail, path).not.toMatch(/max-w-(2xl|3xl)/);
    }
  });
});
