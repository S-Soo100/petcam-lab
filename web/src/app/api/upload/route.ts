import { NextRequest, NextResponse } from 'next/server';
import fs from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { supabaseAdmin } from '@/lib/supabase';
import { SPECIES } from '@/types';

const POC_CLIPS_DIR = process.env.POC_CLIPS_DIR;
const DEV_USER_ID = process.env.DEV_USER_ID;
const DEV_PET_ID = process.env.DEV_PET_ID || null;

if (!POC_CLIPS_DIR || !DEV_USER_ID) {
  throw new Error('POC_CLIPS_DIR / DEV_USER_ID 누락. web/.env.local 확인.');
}

const MAX_BYTES = 50 * 1024 * 1024; // 50MB. Gemini inline 한계 ~20MB지만 60s mp4 보통 5~10MB.

function todayDir(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export async function POST(req: NextRequest) {
  const form = await req.formData();
  const file = form.get('file');
  const species = form.get('species');
  const durationRaw = form.get('duration_sec');

  if (!(file instanceof File)) {
    return NextResponse.json({ error: 'file 누락' }, { status: 400 });
  }
  if (file.type !== 'video/mp4') {
    return NextResponse.json({ error: `mp4만 허용. 받은 type=${file.type}` }, { status: 400 });
  }
  if (file.size > MAX_BYTES) {
    return NextResponse.json(
      { error: `파일 너무 큼: ${file.size}B > ${MAX_BYTES}B` },
      { status: 413 }
    );
  }
  if (typeof species !== 'string' || !(SPECIES as readonly string[]).includes(species)) {
    return NextResponse.json({ error: `잘못된 종: ${species}` }, { status: 400 });
  }
  const duration = typeof durationRaw === 'string' ? parseFloat(durationRaw) : NaN;
  if (!Number.isFinite(duration) || duration <= 0) {
    return NextResponse.json({ error: 'duration_sec 누락/잘못' }, { status: 400 });
  }

  const dateDir = todayDir();
  const uuid = randomUUID();
  const dirPath = path.join(POC_CLIPS_DIR!, dateDir);
  await fs.mkdir(dirPath, { recursive: true });
  const fullPath = path.join(dirPath, `${uuid}.mp4`);

  const buf = Buffer.from(await file.arrayBuffer());
  await fs.writeFile(fullPath, buf);

  const { data, error } = await supabaseAdmin
    .from('camera_clips')
    .insert({
      user_id: DEV_USER_ID,
      pet_id: DEV_PET_ID,
      camera_id: null,
      source: 'upload',
      started_at: new Date().toISOString(),
      duration_sec: duration,
      file_path: fullPath,
      file_size: file.size,
      has_motion: true, // 업로드는 항상 라벨 대상 → 큐에 노출
    })
    .select('id')
    .single();

  if (error) {
    await fs.unlink(fullPath).catch(() => {});
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ id: data.id, file_path: fullPath, species }, { status: 201 });
}
