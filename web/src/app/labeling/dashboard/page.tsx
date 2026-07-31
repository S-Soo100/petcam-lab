'use client';

import { useCallback, useEffect, useState } from 'react';

import Button from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { getLabelingDashboard } from '@/lib/rbaBoundaryApi';
import type { LabelingDataDashboard } from '@/lib/rbaBoundaryServer';
import DashboardView from './_dashboard-view';

export default function LabelingDashboardPage() {
  const [data, setData] = useState<LabelingDataDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    setError(null);
    getLabelingDashboard().then(setData).catch((cause) => setError((cause as Error).message));
  }, []);
  useEffect(load, [load]);
  if (error) return <Card className="my-6"><p className="text-sm text-rose-700">{error}</p><Button className="mt-3" onClick={load}>다시 시도</Button></Card>;
  if (!data) return <p className="py-10 text-sm text-zinc-500">데이터 현황을 불러오는 중…</p>;
  return <DashboardView data={data} />;
}
