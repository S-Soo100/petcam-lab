# Flutter 추정 활동시간 canary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. 이 작업은 기존 Flutter feature를 수정하는 **CAOF Standard**다. 시작 응답에서 트랙과 작업 순서를 먼저 알리고, 아래 승인 경계를 지켜.
>
> **실행 결과(2026-07-14):** Flutter 기능 커밋 `b4db4dc`, release marker `2e4fced`(`v0.20.1+35`). 테스트 55·debug APK build 통과, iPhone 17 simulator 홈/상세/리포트 smoke 완료. 카메라 A static-only canary에서 `8h 50m → 8h 45m` 반영 확인. 이 문서는 완료된 실행계획의 감사 기록이며 재실행 지시문이 아니다.

**Goal:** Flutter의 홈·카메라 상세·어젯밤 리포트가 원본 모션 클립 길이 합이 아니라 DB의 `effective_activity_sec` 합을 같은 기준으로 표시하게 만든다.

**Architecture:** 영상 목록·재생·개별 영상 길이는 계속 `motion_clips`를 사용하고, 활동시간 집계 두 메서드만 RLS view `v_clip_effective_activity`를 읽는다. view/행 값에 문제가 있으면 원본 `motion_clips.duration_sec`로 fail-open해서 장애를 0초 활동으로 오인하지 않는다. Flutter 구현·검증까지만 수행하고 DB 제외 스위치, 배포, commit/push는 건드리지 않는다.

**Tech Stack:** Flutter, Dart 3.5+, Riverpod, Supabase Flutter, easy_localization, flutter_test

## Global Constraints

- 작업 레포는 `/Users/baek/myProjects/tera-ai-flutter`다.
- 시작 전에 `AGENTS.md`, `CLAUDE.md`, `docs/design-system.md`와 이 문서를 읽고 `git status --short`, branch, HEAD를 보고해.
- 다른 세션의 수정과 untracked 파일을 보존해. 파괴적 Git 명령을 사용하지 마.
- 신규 패키지를 추가하지 마. 기존 Repository/Riverpod/easy_localization 패턴을 유지해.
- 활동시간 집계만 바꿔. 영상 목록, 영상 재생, 다운로드, 썸네일, 개별 영상의 실제 duration은 바꾸지 마.
- `exclude_absent`는 알려진 false exclusion이 있으므로 **절대 활성화하지 마**. Flutter도 absent를 임의로 0초 처리하지 말고 DB view의 `effective_activity_sec`만 신뢰해.
- DB migration, DB write, LaunchAgent, Gate, worker, VLM, 카메라 설정은 수정하지 마.
- 앱 코드에 카메라 UUID, owner UUID, 비밀값을 넣지 마.
- view 조회 실패나 값 누락을 0초로 표시하지 마. 원본 duration으로 fail-open해.
- 앱 구현 후에도 운영 DB의 두 제외 스위치는 현재 상태(false)를 유지해. canary 활성화는 별도 승인 단계다.
- 사용자 승인 전 commit, push, 앱 배포를 하지 말고 검증 결과와 diff만 보고해.
- 구현 루프는 최대 3회다. 3회 실패하면 수정 반복을 멈추고 오류와 원인을 보고해.

---

## 1. 배경과 현재 운영 계약

현재 Flutter의 `MotionClipRepository.motionSeconds`와 `motionSecondsByHour`는 `motion_clips.duration_sec`를 전부 더한다. 따라서 게코가 움직이지 않은 모션 클립도 활동시간에 들어간다.

Mac mini에서는 Claude/VLM을 호출하지 않는 `activity-v1` worker가 매시간 다음 evidence와 판정을 shadow로 쌓고 있다.

- `active`: 활동 증거 있음
- `exclude_static`: 게코는 보이지만 활동 증거 없음
- `exclude_absent`: 게코 미검출
- `unknown` 또는 미분석: 근거 부족

운영 DB에는 RLS가 적용된 `public.v_clip_effective_activity`가 있고 Flutter authenticated owner가 읽을 수 있다.

| column | 의미 |
|---|---|
| `clip_id` | `motion_clips.id` |
| `camera_id` | 카메라 ID |
| `owner_id` | 영상 owner |
| `started_at` | 클립 시작시각 |
| `raw_duration_sec` | 원본 클립 길이 |
| `activity_decision` | worker 판정 또는 `pending` |
| `effective_activity_sec` | 현재 카메라 스위치까지 반영된 활동시간 |
| `analysis_pending` | 미분석 여부 |
| `policy_version` | 카메라의 활성 policy version |

view의 제품 계약은 다음과 같다.

- settings가 없거나 disabled면 `effective_activity_sec == raw_duration_sec`.
- `active`, `unknown`, `pending`은 원본 길이를 유지한다.
- `exclude_static_enabled=true`인 카메라에서 `exclude_static`만 0초가 된다.
- `exclude_absent_enabled=true`인 카메라에서만 absent가 0초가 되지만, **이번 canary에서는 이 스위치를 계속 false로 둔다.**
- 현재 세 테스트 카메라는 shadow 중이고 두 exclude 스위치가 모두 false라 앱 수치는 아직 raw와 같다.

## 2. 확정된 canary 정책

앱 구현과 배포 검증이 끝난 뒤 운영 담당자가 **카메라 A 한 대만** 아래처럼 바꾼다. Flutter 에이전트는 이 DB 변경을 실행하지 않는다.

| 항목 | 값 |
|---|---|
| `enabled` | `true` |
| `active_policy_version` | `activity-v1` |
| `exclude_static_enabled` | `true` — 카메라 A만 |
| `exclude_absent_enabled` | `false` — 전 카메라 고정 |

다른 카메라는 기존 raw 계산을 유지한다. 미래의 신규/고객 카메라는 settings row가 없으면 자동으로 raw 계산이므로 canary가 확장되지 않는다.

### 약 3일 뒤 재검수

고정된 72시간 자체가 통과 기준은 아니다. 다음 조건을 만족하는 첫 checkpoint에서 검수한다.

- 서로 다른 날짜의 데이터가 3개 이상 쌓임
- 30분 이내 연속 클립을 한 episode로 dedup
- 독립 `exclude_static` episode가 20개 이상
- 사람이 blind로 영상을 보고 실제 포함해야 할 활동을 제외한 사례가 0개

false exclusion이 1개라도 있으면 즉시 카메라 A의 `exclude_static_enabled=false`로 되돌린다. 데이터가 부족하면 기간만 연장하고 다른 카메라로 확대하지 않는다.

## 3. 사용자 체험 설계

### 홈 활동 카드

1. `[화면]` 사용자가 홈을 열면 대표 카메라 이름과 `어제 추정 활동시간`을 본다.
2. `[조작]` 별도 조작 없이 카드가 로드된다.
3. `[반응]` 총 시간과 시간대별 그래프가 모두 같은 `effective_activity_sec` 행 집합으로 계산된다.
4. `[감정]` 사용자는 이 값이 완전한 실측이 아니라 카메라 영상 기반 추정치라는 점을 바로 이해한다.

### 카메라 상세 활동 카드

1. `[화면]` `추정 활동시간`과 `카메라 영상으로 추정 · 07:00 ~ 익일 07:00` 안내를 본다.
2. `[조작]` 오늘/어제를 전환한다.
3. `[반응]` 총 시간과 24시간 그래프가 같은 범위와 같은 필터 기준으로 다시 계산된다.
4. `[감정]` 총합과 그래프가 서로 달라 보이지 않아 신뢰할 수 있다.

### 어젯밤 리포트

1. `[화면]` 사용자가 리포트를 열면 `추정 활동` 시간을 본다.
2. `[반응]` 사용자의 여러 카메라 중 canary 설정이 있는 카메라는 필터값, 없는 카메라는 raw값으로 합산된다.
3. `[감정]` 기능 적용 범위가 달라도 앱이 하나의 안정적인 합계를 제공한다.

### 영상 목록과 재생

1. `[화면]` 모든 원본 영상과 실제 재생시간은 지금과 동일하게 보인다.
2. `[반응]` 활동시간에서 제외된 static 영상도 삭제되거나 숨겨지지 않는다.
3. `[감정]` 사용자는 필요하면 원본 근거를 직접 확인할 수 있다.

### 장애 시

1. `[상황]` view가 일시적으로 없거나 RLS/네트워크 조회가 실패한다.
2. `[반응]` Repository가 같은 범위의 `motion_clips.duration_sec`를 다시 조회한다.
3. `[결과]` 필터가 잠시 적용되지 않을 수는 있지만, 장애 때문에 활동시간이 0으로 축소되지는 않는다.

---

## 4. 파일 구조와 책임

| 파일 | 작업 | 책임 |
|---|---|---|
| `lib/features/my_cage/domain/cage_activity.dart` | 수정 | view/raw row에서 사용할 초를 안전하게 고르는 순수함수 |
| `lib/features/my_cage/data/motion_clip_repository.dart` | 수정 | effective view 우선 조회, raw query fallback, 총합/시간대 집계 |
| `lib/features/my_cage/presentation/my_cage_providers.dart` | 수정 | 현재 계약에 맞는 주석 + 전체 data source 장애를 0초로 숨기는 nightly catch 제거 |
| `assets/l10n/ko.json` | 수정 | 세 화면의 활동 문구를 일관된 `추정 활동시간`으로 변경 |
| `test/features/my_cage/cage_activity_test.dart` | 수정 | row 선택 규칙과 기존 시간 bucket 회귀 테스트 |
| `test/features/my_cage/motion_clip_repository_test.dart` | 신규 | view 우선, raw fallback, query 실패 전파, 총합/시간대 정합성 |

새 화면, 새 Provider, 새 DB model, 새 패키지는 만들지 않는다.

---

### Task 1: effective duration 순수 계약을 TDD로 추가

**Files:**
- Modify: `lib/features/my_cage/domain/cage_activity.dart`
- Modify: `test/features/my_cage/cage_activity_test.dart`

**Interfaces:**
- Produces: `double activityDurationSeconds(Map<String, dynamic> row)`
- Consumes: view row의 `effective_activity_sec`, `raw_duration_sec` 또는 raw row의 `duration_sec`

- [ ] **Step 1: 아래 실패 테스트를 `cage_activity_test.dart`에 추가해**

```dart
  group('activityDurationSeconds', () {
    test('유효한 effective 값이 있으면 raw보다 우선한다', () {
      expect(
        activityDurationSeconds({
          'effective_activity_sec': 0,
          'raw_duration_sec': 31.8,
        }),
        0,
      );
    });

    test('effective가 null이면 view의 raw 값으로 fail-open한다', () {
      expect(
        activityDurationSeconds({
          'effective_activity_sec': null,
          'raw_duration_sec': 31.8,
        }),
        31.8,
      );
    });

    test('raw query row의 duration_sec도 읽는다', () {
      expect(activityDurationSeconds({'duration_sec': 12.5}), 12.5);
    });

    test('음수·NaN effective는 raw 값으로 fail-open한다', () {
      expect(
        activityDurationSeconds({
          'effective_activity_sec': -1,
          'raw_duration_sec': 20,
        }),
        20,
      );
      expect(
        activityDurationSeconds({
          'effective_activity_sec': double.nan,
          'raw_duration_sec': 20,
        }),
        20,
      );
    });

    test('유효한 초가 하나도 없으면 오류로 드러낸다', () {
      expect(
        () => activityDurationSeconds(const {}),
        throwsFormatException,
      );
    });

    test('앱은 decision 이름을 재해석하지 않고 view 계산값만 사용한다', () {
      final rows = [
        {
          'activity_decision': 'active',
          'effective_activity_sec': 30,
          'raw_duration_sec': 30,
        },
        {
          'activity_decision': 'exclude_static',
          'effective_activity_sec': 0,
          'raw_duration_sec': 30,
        },
        {
          'activity_decision': 'exclude_absent',
          'effective_activity_sec': 30,
          'raw_duration_sec': 30,
        },
        {
          'activity_decision': 'unknown',
          'effective_activity_sec': 30,
          'raw_duration_sec': 30,
        },
        {
          'activity_decision': 'pending',
          'effective_activity_sec': 30,
          'raw_duration_sec': 30,
        },
      ];

      expect(rows.map(activityDurationSeconds), [30, 0, 30, 30, 30]);
    });
  });
```

- [ ] **Step 2: 테스트가 함수 미정의로 실패하는지 확인해**

Run:

```bash
cd /Users/baek/myProjects/tera-ai-flutter
flutter test test/features/my_cage/cage_activity_test.dart
```

Expected: `activityDurationSeconds`가 없어 FAIL.

- [ ] **Step 3: `cage_activity.dart`에 최소 구현을 추가해**

```dart
/// DB view가 계산한 effective 초를 우선 사용하되, 누락·비정상 값이면 원본
/// duration으로 fail-open한다. 필터 장애를 0초 활동으로 오인하지 않기 위함이다.
double activityDurationSeconds(Map<String, dynamic> row) {
  double? validSeconds(Object? value) {
    if (value is! num) return null;
    final seconds = value.toDouble();
    if (!seconds.isFinite || seconds < 0) return null;
    return seconds;
  }

  final seconds = validSeconds(row['effective_activity_sec']) ??
      validSeconds(row['raw_duration_sec']) ??
      validSeconds(row['duration_sec']);
  if (seconds == null) {
    throw const FormatException('Activity duration is missing or invalid');
  }
  return seconds;
}
```

- [ ] **Step 4: 관련 테스트를 다시 실행해 PASS를 확인해**

Run: `flutter test test/features/my_cage/cage_activity_test.dart`

Expected: 기존 테스트와 신규 6개 모두 PASS.

---

### Task 2: Repository에 테스트 가능한 view→raw fallback 경계를 추가

**Files:**
- Modify: `lib/features/my_cage/data/motion_clip_repository.dart`
- Create: `test/features/my_cage/motion_clip_repository_test.dart`

**Interfaces:**
- Produces: `ActivityRowsLoader` typedef
- Produces: constructor optional parameter `ActivityRowsLoader? activityRowsLoader`
- Produces: private `_loadActivityRows(cameraId, from, to)`
- Consumes: Task 1의 `activityDurationSeconds(row)`

- [ ] **Step 1: repository 테스트 파일을 만들고 view 우선/row fallback을 검증해**

테스트용 loader는 네트워크를 쓰지 않고 요청한 table/columns를 기록해야 한다. Repository 생성 시 아래 형태를 사용해.

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:tera_ai/features/my_cage/data/motion_clip_repository.dart';

void main() {
  final from = DateTime.utc(2026, 7, 13, 7);
  final to = DateTime.utc(2026, 7, 14, 7);

  MotionClipRepository repository(ActivityRowsLoader loader) {
    return MotionClipRepository(
      supabase: SupabaseClient('http://localhost', 'test-anon-key'),
      terraApiUrl: 'http://localhost',
      tokenProvider: () async => null,
      activityRowsLoader: loader,
    );
  }

  test('motionSeconds는 effective view를 우선 합산한다', () async {
    final tables = <String>[];
    final repo = repository(({
      required table,
      required columns,
      required cameraId,
      required from,
      required to,
    }) async {
      tables.add(table);
      return [
        {
          'started_at': '2026-07-13T07:10:00Z',
          'effective_activity_sec': 30,
          'raw_duration_sec': 30,
        },
        {
          'started_at': '2026-07-13T08:10:00Z',
          'effective_activity_sec': 0,
          'raw_duration_sec': 30,
        },
      ];
    });

    expect(await repo.motionSeconds('camera-a', from, to), 30);
    expect(tables, ['v_clip_effective_activity']);
  });

  test('view query 실패 시 motion_clips raw 합으로 fail-open한다', () async {
    final tables = <String>[];
    final repo = repository(({
      required table,
      required columns,
      required cameraId,
      required from,
      required to,
    }) async {
      tables.add(table);
      if (table == 'v_clip_effective_activity') {
        throw const PostgrestException(message: 'view unavailable');
      }
      return [
        {
          'started_at': '2026-07-13T07:10:00Z',
          'duration_sec': 30,
        },
        {
          'started_at': '2026-07-13T08:10:00Z',
          'duration_sec': 30,
        },
      ];
    });

    expect(await repo.motionSeconds('camera-a', from, to), 60);
    expect(tables, ['v_clip_effective_activity', 'motion_clips']);
  });

  test('view와 raw query가 모두 실패하면 0으로 숨기지 않고 오류를 전파한다', () async {
    final repo = repository(({
      required table,
      required columns,
      required cameraId,
      required from,
      required to,
    }) async {
      throw PostgrestException(message: '$table unavailable');
    });

    await expectLater(
      repo.motionSeconds('camera-a', from, to),
      throwsA(isA<PostgrestException>()),
    );
  });
}
```

- [ ] **Step 2: 테스트가 `ActivityRowsLoader`와 constructor parameter 미정의로 실패하는지 확인해**

Run:

```bash
flutter test test/features/my_cage/motion_clip_repository_test.dart
```

Expected: compile FAIL.

- [ ] **Step 3: `motion_clip_repository.dart`의 import 아래에 loader typedef를 추가해**

```dart
typedef ActivityRowsLoader = Future<List<Map<String, dynamic>>> Function({
  required String table,
  required String columns,
  required String cameraId,
  required DateTime from,
  required DateTime to,
});
```

- [ ] **Step 4: Repository constructor에 loader seam을 추가해**

필드:

```dart
  final ActivityRowsLoader _activityRowsLoader;
```

constructor의 optional parameter와 initializer:

```dart
    ActivityRowsLoader? activityRowsLoader,
  })  : _supabase = supabase,
        _terraApiUrl = terraApiUrl,
        _tokenProvider = tokenProvider,
        _activityRowsLoader = activityRowsLoader ??
            (({
              required table,
              required columns,
              required cameraId,
              required from,
              required to,
            }) async {
              final rows = await supabase
                  .from(table)
                  .select(columns)
                  .eq('camera_id', cameraId)
                  .gte('started_at', from.toUtc().toIso8601String())
                  .lt('started_at', to.toUtc().toIso8601String())
                  .order('started_at', ascending: true)
                  .limit(5000);
              return (rows as List)
                  .map((row) => Map<String, dynamic>.from(row as Map))
                  .toList();
            });
```

- [ ] **Step 5: view 우선·raw fallback을 한 private method로 구현해**

```dart
  Future<List<Map<String, dynamic>>> _loadActivityRows(
    String cameraId,
    DateTime from,
    DateTime to,
  ) async {
    try {
      return await _activityRowsLoader(
        table: 'v_clip_effective_activity',
        columns: 'started_at, effective_activity_sec, raw_duration_sec',
        cameraId: cameraId,
        from: from,
        to: to,
      );
    } on PostgrestException {
      debugPrint('[activity] effective view unavailable; raw fallback used');
      return _activityRowsLoader(
        table: 'motion_clips',
        columns: 'started_at, duration_sec',
        cameraId: cameraId,
        from: from,
        to: to,
      );
    }
  }
```

`motion_clip_repository.dart`에 `package:flutter/foundation.dart`를 import해. catch는 `PostgrestException`만 받고, 범위는 **view query 호출만** 포함해야 한다. 이후 row 파싱이나 개발자 코드 오류까지 raw fallback으로 숨기지 마. 로그에는 DB 오류 전문·owner·camera ID를 넣지 마.

- [ ] **Step 6: `motionSeconds`를 공통 row 계약으로 교체해**

```dart
  /// 구간 [from, to)의 추정 활동시간. effective view를 우선하고 조회 장애 시
  /// motion_clips 원본 duration 합으로 fail-open한다.
  Future<int> motionSeconds(
      String cameraId, DateTime from, DateTime to) async {
    final rows = await _loadActivityRows(cameraId, from, to);
    var seconds = 0.0;
    for (final row in rows) {
      seconds += activityDurationSeconds(row);
    }
    return seconds.round();
  }
```

- [ ] **Step 7: 신규 repository 테스트를 실행해 PASS를 확인해**

Run: `flutter test test/features/my_cage/motion_clip_repository_test.dart`

Expected: 3 tests PASS.

---

### Task 3: 시간대 그래프도 같은 effective row 집합으로 변경

**Files:**
- Modify: `lib/features/my_cage/data/motion_clip_repository.dart`
- Modify: `test/features/my_cage/motion_clip_repository_test.dart`

**Interfaces:**
- Consumes: `_loadActivityRows`와 `activityDurationSeconds`
- Preserves: `bucketMotionSecondsByHour` signature와 24개 bucket 계약

- [ ] **Step 1: repository 테스트에 총합/시간대 합 일치 케이스를 추가해**

```dart
  test('시간대 그래프와 총합은 같은 effective 초를 사용한다', () async {
    final repo = repository(({
      required table,
      required columns,
      required cameraId,
      required from,
      required to,
    }) async {
      return [
        {
          'started_at': '2026-07-13T07:10:00Z',
          'effective_activity_sec': 30,
          'raw_duration_sec': 30,
        },
        {
          'started_at': '2026-07-13T08:10:00Z',
          'effective_activity_sec': 0,
          'raw_duration_sec': 30,
        },
        {
          'started_at': '2026-07-13T09:10:00Z',
          'effective_activity_sec': null,
          'raw_duration_sec': 20,
        },
      ];
    });

    final total = await repo.motionSeconds('camera-a', from, to);
    final hourly = await repo.motionSecondsByHour('camera-a', from, to);

    expect(total, 50);
    expect(hourly.fold<int>(0, (sum, value) => sum + value), total);
  });
```

- [ ] **Step 2: 현재 시간대 구현이 raw query를 직접 사용해 테스트가 실패하는지 확인해**

Run: `flutter test test/features/my_cage/motion_clip_repository_test.dart`

Expected: test FAIL 또는 loader 경로 불일치.

- [ ] **Step 3: `motionSecondsByHour` 구현을 교체해**

```dart
  /// 구간 [from,to)를 1시간 버킷 24개로 나눈 추정 활동시간.
  Future<List<int>> motionSecondsByHour(
      String cameraId, DateTime from, DateTime to) async {
    final rows = await _loadActivityRows(cameraId, from, to);
    final clips = <({DateTime startedAt, double durationSec})>[];
    for (final row in rows) {
      final startedAt = DateTime.tryParse(row['started_at']?.toString() ?? '');
      if (startedAt == null) continue;
      clips.add((
        startedAt: startedAt,
        durationSec: activityDurationSeconds(row),
      ));
    }
    return bucketMotionSecondsByHour(clips, from);
  }
```

- [ ] **Step 4: repository와 domain 테스트를 함께 실행해 PASS를 확인해**

Run:

```bash
flutter test \
  test/features/my_cage/motion_clip_repository_test.dart \
  test/features/my_cage/cage_activity_test.dart
```

Expected: 모두 PASS.

- [ ] **Step 5: raw 영상 경로가 유지됐는지 grep으로 확인해**

Run:

```bash
rg -n "from\('motion_clips'\)|v_clip_effective_activity" \
  lib/features/my_cage/data/motion_clip_repository.dart
```

Expected:

- `listByCamera`, `getById`, `latestMotionAt` 등 영상 기능은 계속 `motion_clips`.
- 활동 집계 loader에서만 `v_clip_effective_activity` 우선 + `motion_clips` fallback.

---

### Task 4: 세 화면의 사용자 문구를 `추정 활동시간`으로 통일

**Files:**
- Modify: `assets/l10n/ko.json`
- Modify: `lib/features/my_cage/presentation/my_cage_providers.dart`

**Interfaces:**
- Preserves: localization key 이름과 Widget 구조
- Changes: 한국어 표시값과 stale 주석만

- [ ] **Step 1: `ko.json`의 기존 key 값을 정확히 아래처럼 바꿔**

```json
"home_activity_tooltip": "추정 활동시간 통계",
"home_activity_section": "활동 분석 요약",
"home_activity_total_label": "어제 추정 활동시간",
"nightly_activity": "추정 활동",
"crecam_detail_activity_title": "추정 활동시간",
"crecam_detail_activity_baseline": "* 카메라 영상으로 추정 · 07:00 ~ 익일 07:00",
"crecam_detail_stat_motion": "활동"
```

기존 key를 재사용하고 문자열을 Widget에 하드코딩하지 마. JSON의 다른 항목 순서나 문구는 바꾸지 마.

- [ ] **Step 2: Provider 주석의 raw 정의만 현재 계약으로 고쳐**

```dart
/// 추정 활동시간(초) — effective activity view 합. view 장애 시 repository가
/// motion_clips 원본 duration 합으로 fail-open한다. 하루 경계는 오전 7시다.
```

```dart
/// 시간대별 추정 활동시간(초) 24개 — 총합과 같은 effective row를 1시간
/// bucket으로 나눈다. 하루 경계는 오전 7시다.
```

`nightlyReportProvider`는 같은 `motionSeconds`를 카메라별로 합산하되, 카메라 목록 또는 raw fallback까지 실패한 경우 0초로 숨기지 않고 화면의 기존 retry 상태로 보내야 한다. 아래 두 catch만 제거해.

Before:

```dart
  List<TerraCamera> cameras;
  try {
    cameras = await ref.watch(camerasProvider.future);
  } catch (_) {
    cameras = const [];
  }
  final motionRepo = ref.watch(motionClipRepositoryProvider);
  final secs = await Future.wait(cameras.map((c) async {
    try {
      return await motionRepo.motionSeconds(c.id, start, end);
    } catch (_) {
      return 0;
    }
  }));
```

After:

```dart
  final cameras = await ref.watch(camerasProvider.future);
  final motionRepo = ref.watch(motionClipRepositoryProvider);
  final secs = await Future.wait(
    cameras.map((c) => motionRepo.motionSeconds(c.id, start, end)),
  );
```

하이라이트 목록 조회의 기존 catch는 활동시간과 별개이므로 유지해.

- [ ] **Step 3: 사용자에게 노출되는 stale 문구가 남았는지 확인해**

Run:

```bash
rg -n '총 활동 시간|간단 활동량|"nightly_activity": "활동"|motion_clips duration 합' \
  assets/l10n/ko.json \
  lib/features/home \
  lib/features/my_cage
```

Expected: 이번 세 화면의 stale 문구 0건. 영상 duration 설명처럼 활동 집계와 무관한 문구는 수정하지 않는다.

- [ ] **Step 4: nightly가 활동 data source 실패를 0으로 숨기지 않는지 확인해**

Run:

```bash
sed -n '365,410p' lib/features/my_cage/presentation/my_cage_providers.dart
```

Expected: highlight catch는 남아 있지만, `camerasProvider.future`와 `motionSeconds` 주변에는 `catch (_)`, `cameras = const []`, `return 0`이 없다.

---

### Task 5: 전체 회귀 검증과 수동 사용자 흐름 확인

**Files:**
- No new files
- Verify all modified files from Tasks 1–4

- [ ] **Step 1: formatter와 diff 검사를 실행해**

Run:

```bash
dart format \
  lib/features/my_cage/domain/cage_activity.dart \
  lib/features/my_cage/data/motion_clip_repository.dart \
  lib/features/my_cage/presentation/my_cage_providers.dart \
  test/features/my_cage/cage_activity_test.dart \
  test/features/my_cage/motion_clip_repository_test.dart
git diff --check
```

Expected: formatter 성공, `git diff --check` 출력 없음.

- [ ] **Step 2: 전체 정적 분석과 테스트를 실행해**

Run:

```bash
flutter analyze
flutter test
```

Expected: analyze error 0, 전체 test PASS.

- [ ] **Step 3: Android debug build를 실행해**

Run:

```bash
flutter build apk --debug
```

Expected: build 성공.

- [ ] **Step 4: 로그인된 실제 앱에서 아래 흐름을 확인하고 화면별 결과를 기록해**

DB exclude 스위치는 아직 false이므로 배포 전/후 수치가 같아야 한다.

1. 홈: `어제 추정 활동시간` 문구, 총합, 그래프 로드
2. 카메라 상세: `추정 활동시간`, 추정 안내, 오늘/어제 전환
3. 어젯밤 리포트: `추정 활동` 표시
4. 같은 카메라·같은 날짜에서 총합과 시간대 bucket 합 일치
5. 영상 목록 개수, 재생, 실제 영상 duration이 변경 전과 동일

앱을 실행할 수 없으면 실행하지 않았다고 명시하고 코드 검증만으로 실기기 확인을 통과 처리하지 마.

- [ ] **Step 5: 변경 범위를 최종 확인해**

Run:

```bash
git status --short
git diff --stat
git diff -- \
  lib/features/my_cage/domain/cage_activity.dart \
  lib/features/my_cage/data/motion_clip_repository.dart \
  lib/features/my_cage/presentation/my_cage_providers.dart \
  assets/l10n/ko.json \
  test/features/my_cage/cage_activity_test.dart \
  test/features/my_cage/motion_clip_repository_test.dart
```

Expected: 위 6개 파일만 작업 범위다. 기존 사용자 변경이 발견되면 덮어쓰지 말고 별도 보고해.

---

## 5. 구현 완료 후 반드시 멈출 경계

Flutter 에이전트는 아래를 실행하지 않는다.

- `git commit`, `git push`
- TestFlight/Play internal/Vercel 등 어떤 배포도 실행
- `camera_activity_filter_settings` INSERT/UPDATE
- `exclude_static_enabled` 또는 `exclude_absent_enabled` 변경
- migration 적용
- Mac mini LaunchAgent 변경
- Gate threshold/policy 변경

구현·검증 결과를 사용자에게 보고하고 멈춰. 사용자가 이 응답을 petcam-lab 작업에 가져가 검토한 뒤 다음 승인 순서를 결정한다.

## 6. 다음 운영 단계 — Flutter 에이전트의 작업 범위 밖

1. 구현 diff와 테스트 결과를 petcam-lab 쪽에서 검토
2. 승인 후 Flutter commit/push
3. exclude 스위치가 모두 false인 상태로 앱 배포
4. 홈·상세·리포트의 수치가 기존 raw와 동일한지 확인
5. 카메라 A만 `exclude_static_enabled=true`, `exclude_absent_enabled=false`
6. 앱 새로고침 후 카메라 A의 실제 수치 감소 및 총합/그래프/리포트 정합 확인
7. 이상 시 `exclude_static_enabled=false`로 즉시 rollback
8. 약 3일 또는 검수 표본 충족 후 blind audit
9. audit 통과 전에는 다른 카메라 확대 및 대외 Slack 완료 공지 금지

## 7. 완료 보고 형식

아래 순서로 빠짐없이 보고해.

1. CAOF 트랙과 실제 작업 범위
2. 변경 파일별 요약
3. view 우선·raw fallback 구현 방식
4. `active/static/absent/unknown/pending` fixture별 계산 결과
5. 총합과 시간대 합 정합 테스트 결과
6. `flutter analyze`, `flutter test`, `flutter build apk --debug` 결과
7. 실제 앱 화면 확인 여부와 화면별 결과
8. 영상 목록·재생·개별 duration 무변경 확인
9. `git status --short`와 미커밋 상태 확인
10. DB write·스위치·commit·push·배포를 하지 않았다는 확인
11. 발견한 blocker 또는 후속 위험

## 8. 최종 수용 기준

- 홈·카메라 상세·어젯밤 리포트의 활동시간이 모두 `v_clip_effective_activity.effective_activity_sec`를 기준으로 계산된다.
- 총 활동시간과 시간대별 bucket 합이 같은 데이터 계약을 사용한다.
- view 조회 실패 또는 effective 값 누락 시 raw duration으로 fail-open한다.
- view와 raw 조회가 모두 실패하면 오류가 전파되고, data source 장애를 0초로 숨기지 않는다.
- 영상 목록·재생·다운로드·썸네일·개별 duration은 기존 `motion_clips` 계약을 유지한다.
- 사용자 문구가 이 값이 추정치임을 명확히 알린다.
- `exclude_absent`를 앱이나 DB에서 임의로 적용하지 않는다.
- 전체 analyze/test/debug build가 통과한다.
- 운영 DB와 배포 상태는 변경하지 않은 채 사용자 검토를 기다린다.
