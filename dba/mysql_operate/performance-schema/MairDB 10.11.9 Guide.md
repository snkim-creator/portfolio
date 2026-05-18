# MariaDB Performance Schema 운영 가이드

## 개요

MariaDB 10.11.9 운영 환경에서 Lock 분석, 쿼리 성능 확인, 장애 대응을 목적으로  
Performance Schema 설정 기준과 운영 가이드를 수립하였습니다.

---

## 운영 환경

- MariaDB 10.11.9
- Master-Master 양방향 Sync 구조
- CPU 사용량 평소 20% 이하

---

## 핵심 개념

### setup_consumers
어떤 이벤트를 **저장할지** 정하는 설정입니다.  
Consumer가 꺼져 있으면 이벤트가 발생해도 조회 테이블에 쌓이지 않습니다.

### setup_instruments
어떤 이벤트를 **실제로 계측할지** 정하는 설정입니다.  
Consumer가 켜져 있어도 Instrument가 꺼져 있으면 데이터가 수집되지 않습니다.

---

## 운영 기준

### 상시 ON

| 항목 | 종류 | 목적 |
|------|------|------|
| events_statements_current | Consumer | 현재 실행 중인 SQL 확인 |
| events_statements_history | Consumer | 최근 SQL 이력 확인 |
| events_statements_history_long | Consumer | 전역 SQL 이력 확인 |
| events_waits_current | Consumer | 현재 wait 확인 |
| events_waits_history | Consumer | 최근 wait 이력 확인 |
| statement/% | Instrument | SQL 성능 수집 |
| wait/synch/% | Instrument | Lock 대기 분석 |
| wait/lock/metadata% | Instrument | Metadata Lock 분석 |

### 상시 OFF (장애 시만 활성화)

| 항목 | 이유 |
|------|------|
| events_waits_history_long | 상시 운영에서는 과함 |
| events_stages_* | 기본 운영 분석에서는 불필요 |
| stage/% | 장애 시 세부 단계 분석 용도 |

---

## 설정 스크립트

### 운영 기본안 적용

```sql
-- Consumer 활성화
UPDATE performance_schema.setup_consumers
SET ENABLED = 'YES'
WHERE NAME IN (
  'events_statements_current',
  'events_statements_history',
  'events_statements_history_long',
  'events_waits_current',
  'events_waits_history'
);

-- 불필요한 Consumer 비활성화
UPDATE performance_schema.setup_consumers
SET ENABLED = 'NO'
WHERE NAME IN (
  'events_waits_history_long',
  'events_stages_current',
  'events_stages_history',
  'events_stages_history_long'
);

-- Instrument 활성화
UPDATE performance_schema.setup_instruments
SET ENABLED = 'YES', TIMED = 'YES'
WHERE NAME LIKE 'statement/%';

UPDATE performance_schema.setup_instruments
SET ENABLED = 'YES', TIMED = 'YES'
WHERE NAME LIKE 'wait/synch/%'
   OR NAME LIKE 'wait/lock/metadata%';

-- Stage 비활성화
UPDATE performance_schema.setup_instruments
SET ENABLED = 'NO', TIMED = 'NO'
WHERE NAME LIKE 'stage/%';
```

### 장애 분석 시 확장

```sql
UPDATE performance_schema.setup_consumers
SET ENABLED = 'YES'
WHERE NAME IN ('events_stages_current', 'events_stages_history');

UPDATE performance_schema.setup_instruments
SET ENABLED = 'YES', TIMED = 'YES'
WHERE NAME LIKE 'stage/%';
```

### 장애 분석 후 원복

```sql
UPDATE performance_schema.setup_consumers
SET ENABLED = 'NO'
WHERE NAME IN (
  'events_stages_current',
  'events_stages_history',
  'events_stages_history_long'
);

UPDATE performance_schema.setup_instruments
SET ENABLED = 'NO', TIMED = 'NO'
WHERE NAME LIKE 'stage/%';
```

---

## 장애 대응 조회 순서

문제 발생 시 아래 순서로 확인합니다.

```
1단계  현재 실행 중인 SQL 확인     → events_statements_current
2단계  현재 wait 확인              → events_waits_current
3단계  Metadata Lock 확인          → metadata_locks
4단계  최근 SQL 이력 확인           → events_statements_history
5단계  평소 SQL 패턴 부하 확인      → events_statements_summary_by_digest
```

---

## 주요 조회 SQL

### 현재 실행 중인 SQL

```sql
SELECT
    t.PROCESSLIST_ID,
    t.PROCESSLIST_USER,
    t.PROCESSLIST_TIME,
    ROUND(esc.TIMER_WAIT / 1000000000000, 6) AS wait_sec,
    LEFT(esc.SQL_TEXT, 500) AS sql_text
FROM performance_schema.events_statements_current esc
JOIN performance_schema.threads t ON esc.THREAD_ID = t.THREAD_ID
ORDER BY t.PROCESSLIST_TIME DESC;
```

### 상위 부하 SQL 패턴

```sql
SELECT
    LEFT(DIGEST_TEXT, 200) AS digest_text,
    COUNT_STAR,
    ROUND(SUM_TIMER_WAIT / 1000000000000, 3) AS total_sec,
    ROUND(AVG_TIMER_WAIT / 1000000000000, 6) AS avg_sec,
    SUM_ROWS_EXAMINED
FROM performance_schema.events_statements_summary_by_digest
ORDER BY SUM_TIMER_WAIT DESC
LIMIT 20;
```

### Metadata Lock 확인

```sql
SELECT
    ml.OBJECT_SCHEMA,
    ml.OBJECT_NAME,
    ml.LOCK_TYPE,
    ml.LOCK_STATUS,
    t.PROCESSLIST_ID,
    t.PROCESSLIST_USER
FROM performance_schema.metadata_locks ml
LEFT JOIN performance_schema.threads t ON ml.OWNER_THREAD_ID = t.THREAD_ID
ORDER BY ml.OBJECT_SCHEMA, ml.OBJECT_NAME, ml.LOCK_STATUS;
```
