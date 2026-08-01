import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, it } from 'vitest';

const ROOT = dirname(fileURLToPath(import.meta.url));

function productionTsxFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return productionTsxFiles(path);
    if (!entry.name.endsWith('.tsx') || entry.name.endsWith('.test.tsx')) return [];
    return [path];
  });
}

it('keeps the raw video element inside ReviewVideo only', () => {
  const offenders = productionTsxFiles(ROOT)
    .filter((path) => !path.endsWith('_review-video.tsx'))
    .filter((path) => readFileSync(path, 'utf8').includes('<video'))
    .map((path) => relative(ROOT, path))
    .sort();

  expect(offenders).toEqual([]);
});
