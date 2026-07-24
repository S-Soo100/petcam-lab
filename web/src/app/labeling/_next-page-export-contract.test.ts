import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const labelingDir = dirname(fileURLToPath(import.meta.url));

const ROLE_PAGE_FILES = [
  'blind/canary/[cohortId]/page.tsx',
  'library/page.tsx',
  'library/[clipId]/page.tsx',
  'owner/page.tsx',
];

describe('Next.js page export contract', () => {
  it('role page modules export only the default page component', () => {
    for (const relativePath of ROLE_PAGE_FILES) {
      const source = readFileSync(join(labelingDir, relativePath), 'utf8');
      expect(source, relativePath).not.toMatch(
        /^export\s+(?:async\s+)?(?:function|const|class|interface|type)\s+(?!default\b)/m,
      );
    }
  });
});
