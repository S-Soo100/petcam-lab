'use client';

// 팀 관리 안 카메라 배정 패널(v4 스펙 §2 In 2·5). 배정은 "먼저 보여줄 카메라"일 뿐 권한이 아니다 —
// 배정이 없어도 승인 사용자는 /labeling/all 에서 아무 영상이나 확정할 수 있다(§4.1).
// 체크박스 하나 토글 = PUT 한 번(그 회원의 전체 배정 집합을 다시 보냄) → 성공 후 목록 재조회.

import { useCallback, useEffect, useState } from 'react';

import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { ApiError } from '@/lib/labelingApi';
import type { V4CameraOption, V4Member } from '@/lib/labelingV4';
import { getV4Members, setV4Assignments } from '@/lib/labelingV4Api';

export default function CameraAssignments() {
  const [members, setMembers] = useState<V4Member[]>([]);
  const [cameras, setCameras] = useState<V4CameraOption[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await getV4Members();
      setMembers(r.members);
      setCameras(r.cameras);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : (e as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const toggle = async (m: V4Member, cameraId: string) => {
    const next = m.camera_ids.includes(cameraId)
      ? m.camera_ids.filter((c) => c !== cameraId)
      : [...m.camera_ids, cameraId];
    setBusyId(m.user_id);
    setErr(null);
    try {
      await setV4Assignments(m.user_id, next);
      await load();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Card className="space-y-3">
      <CardTitle>카메라 배정 (먼저 보여줄 카메라 — 권한 아님)</CardTitle>
      {err && <p className="text-sm text-rose-700">{err}</p>}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr>
              <th className="text-left">회원</th>
              {cameras.map((c) => (
                <th key={c.id} className="text-left">
                  {c.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.user_id}>
                <td>{m.display_name}</td>
                {cameras.map((c) => (
                  <td key={c.id}>
                    <input
                      type="checkbox"
                      aria-label={`${m.display_name} ${c.name}`}
                      checked={m.camera_ids.includes(c.id)}
                      disabled={busyId === m.user_id}
                      onChange={() => toggle(m, c.id)}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {members.length === 0 && !err && <p className="text-xs text-zinc-500">활동 중인 회원이 없어.</p>}
      <Button variant="secondary" size="sm" onClick={load}>
        ↻ 새로고침
      </Button>
    </Card>
  );
}
