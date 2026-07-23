import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';

import { SelectionChip, SelectionCard, type SelectionTone } from './SelectionControl';

describe('SelectionChip', () => {
  it('selected chip shows check + 선택됨 + aria-pressed + semantic border, no black fill', () => {
    const html = renderToStaticMarkup(
      <SelectionChip pressed tone="success" onClick={() => undefined}>
        최근 3일
      </SelectionChip>,
    );
    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain('✓');
    expect(html).toContain('선택됨');
    expect(html).toContain('border-emerald-600');
    expect(html).not.toContain('bg-zinc-900');
    expect(html).toContain('min-h-11');
    expect(html).toContain('focus-visible:ring-2');
  });

  it('idle chip has neutral border and no 선택됨', () => {
    const html = renderToStaticMarkup(
      <SelectionChip pressed={false} tone="neutral" onClick={() => undefined}>
        전체
      </SelectionChip>,
    );
    expect(html).toContain('aria-pressed="false"');
    expect(html).toContain('border-zinc-300');
    expect(html).not.toContain('선택됨');
  });

  it('disabled chip is disabled and not clickable', () => {
    const html = renderToStaticMarkup(
      <SelectionChip pressed={false} tone="neutral" disabled onClick={() => undefined}>
        재생 불가
      </SelectionChip>,
    );
    expect(html).toContain('disabled=""');
    expect(html).toContain('cursor-not-allowed');
  });
});

describe('SelectionCard', () => {
  it('idle card renders title/description without 선택됨', () => {
    const html = renderToStaticMarkup(
      <SelectionCard
        pressed={false}
        tone="warning"
        title="보류"
        description="지금 확정하기 어려워"
        onClick={() => undefined}
      />,
    );
    expect(html).toContain('aria-pressed="false"');
    expect(html).toContain('border-zinc-300');
    expect(html).toContain('보류');
    expect(html).toContain('지금 확정하기 어려워');
    expect(html).not.toContain('선택됨');
  });

  it('selected card shows check + 선택됨', () => {
    const html = renderToStaticMarkup(
      <SelectionCard pressed tone="danger" title="제외" description="쓸 수 없어" onClick={() => undefined} />,
    );
    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain('✓');
    expect(html).toContain('선택됨');
    expect(html).toContain('border-rose-500');
  });
});

describe('selected tone colors', () => {
  const cases: [SelectionTone, string][] = [
    ['success', 'border-emerald-600'],
    ['warning', 'border-amber-500'],
    ['danger', 'border-rose-500'],
    ['neutral', 'border-sky-500'],
  ];
  it.each(cases)('%s -> %s', (tone, cls) => {
    const html = renderToStaticMarkup(
      <SelectionChip pressed tone={tone} onClick={() => undefined}>
        x
      </SelectionChip>,
    );
    expect(html).toContain(cls);
    expect(html).not.toContain('bg-zinc-900');
  });
});

describe('Button.tsx source contract', () => {
  it('preserves original primary and adds labeling-only variants', () => {
    const src = readFileSync(new URL('./Button.tsx', import.meta.url), 'utf8');
    // 기존 primary 는 byte-equivalent 로 보존한다(로그인/회원관리 out-of-scope).
    expect(src).toContain(
      "primary:\n    'bg-zinc-900 text-white hover:bg-zinc-800 disabled:bg-zinc-400 disabled:hover:bg-zinc-400'",
    );
    expect(src).toContain('labelingPrimary');
    expect(src).toContain('bg-emerald-700');
    expect(src).toContain('labelingSecondary');
    expect(src).toContain('labelingDanger');
  });
});
