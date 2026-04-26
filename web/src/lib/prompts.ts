import 'server-only';
import fs from 'node:fs/promises';
import path from 'node:path';
import { type Species, SPECIES_CLASSES } from '@/types';

// prompts/ 는 web/ 루트 (next dev/start의 cwd 기준).
const promptsRoot = path.join(process.cwd(), 'prompts');

export async function buildSystemPrompt(species: Species): Promise<string> {
  const [base, speciesFile] = await Promise.all([
    fs.readFile(path.join(promptsRoot, 'system_base.md'), 'utf8'),
    fs.readFile(path.join(promptsRoot, 'species', `${species}.md`), 'utf8'),
  ]);
  const classesBlock = SPECIES_CLASSES[species].map((c) => `- ${c}`).join('\n');
  return base
    .replace('{available_classes_block}', classesBlock)
    .replace('{species_name}', species)
    .replace('{species_specific_notes}', speciesFile);
}
