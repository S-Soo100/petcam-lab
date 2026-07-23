'use client';

// owner 그룹 배정(설계 §2·§6). 승인 라벨러 정확히 두 명 + 담당 카메라. display_name 표시(마스킹
// 이메일 fallback), 저장 key 는 user_id 뿐 — 비밀번호·이메일 입력란은 두지 않는다. owner 전용.

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';

import { Card, CardTitle } from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import { SelectionChip } from '@/components/ui/SelectionControl';
import { ApiError } from '@/lib/labelingApi';
import { getMotionCameras } from '@/lib/labelingV3Api';
import type { MotionCameraOption } from '@/lib/labelingV3';
import {
  getApprovedLabelers,
  manageBlindGroup,
  type ApprovedLabeler,
} from '@/lib/motionBlindReviewApi';
import { OWNER_GROUP_TITLE } from '../../_blind-review-view';

export default function OwnerGroupsPage() {
  const [labelers, setLabelers] = useState<ApprovedLabeler[]>([]);
  const [cameras, setCameras] = useState<MotionCameraOption[]>([]);
  const [name, setName] = useState('');
  const [members, setMembers] = useState<string[]>([]);
  const [cams, setCams] = useState<string[]>([]);
  const [confirm, setConfirm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const [l, c] = await Promise.all([getApprovedLabelers(), getMotionCameras()]);
        setLabelers(l);
        setCameras(c);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : (e as Error).message);
      }
    })();
  }, []);

  const canSubmit = useMemo(
    () => name.trim().length >= 1 && members.length === 2 && cams.length >= 1,
    [name, members, cams],
  );

  function toggleMember(id: string) {
    setConfirm(false);
    setMembers((prev) =>
      prev.includes(id) ? prev.filter((m) => m !== id) : prev.length >= 2 ? [prev[1], id] : [...prev, id],
    );
  }
  function toggleCam(id: string) {
    setConfirm(false);
    setCams((prev) => (prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]));
  }

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await manageBlindGroup({ name: name.trim(), memberIds: members, cameraIds: cams });
      setDone(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl space-y-3 px-4 py-6">
      <CardTitle>{OWNER_GROUP_TITLE}</CardTitle>
      {error && <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{error}</Card>}
      {done && <Card className="border-emerald-200 bg-emerald-50 text-sm text-emerald-900">그룹 배정을 저장했어.</Card>}

      <Card className="space-y-2">
        <label className="block text-sm font-medium">
          그룹 이름
          <input
            value={name}
            onChange={(e) => {
              setConfirm(false);
              setName(e.target.value);
            }}
            maxLength={80}
            className="mt-1 w-full rounded-lg border border-zinc-300 p-2 text-sm"
          />
        </label>
      </Card>

      <Card className="space-y-2">
        <div className="text-sm font-medium text-zinc-800">라벨러 두 명 선택</div>
        <div className="flex flex-wrap gap-2">
          {labelers.map((l) => (
            <SelectionChip key={l.user_id} pressed={members.includes(l.user_id)} tone="neutral" onClick={() => toggleMember(l.user_id)}>
              {l.display_name}
            </SelectionChip>
          ))}
        </div>
      </Card>

      <Card className="space-y-2">
        <div className="text-sm font-medium text-zinc-800">담당 카메라</div>
        <div className="flex flex-wrap gap-2">
          {cameras.map((c) => (
            <SelectionChip key={c.id} pressed={cams.includes(c.id)} tone="neutral" onClick={() => toggleCam(c.id)}>
              {c.name}
            </SelectionChip>
          ))}
        </div>
      </Card>

      {!confirm ? (
        <Button variant="labelingPrimary" size="lg" className="w-full" disabled={!canSubmit} onClick={() => setConfirm(true)}>
          배정 확인
        </Button>
      ) : (
        <Card className="space-y-2">
          <p className="text-sm text-zinc-700">이 구성으로 그룹을 배정할까? 활성 그룹은 정확히 두 명이야.</p>
          <div className="flex gap-2">
            <Button variant="labelingPrimary" size="md" disabled={saving} onClick={submit}>
              {saving ? '저장 중…' : '배정 저장'}
            </Button>
            <Button variant="labelingSecondary" size="md" onClick={() => setConfirm(false)}>
              취소
            </Button>
          </div>
        </Card>
      )}

      <Link className="text-sm text-emerald-700 underline" href="/labeling/blind/conflicts">불일치 검수로</Link>
    </main>
  );
}
