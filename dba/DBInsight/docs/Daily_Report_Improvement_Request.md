# DBInsight Daily Report 개선 요청

현재 DBInsight MVP에서 Daily Report가 생성되고 있다.

현재 리포트에는 다음 정보가 포함되어 있다.

- 전체 상태
- Critical / Warning / Info 개수
- 확인이 필요한 항목
- 부하 상위 SQL
- 테이블별 I/O 상위
- 전체 SQL Digest 목록
- AI 요약 및 권장 확인사항

현재 구조는 기본적인 MVP로는 동작하지만, 실제 DBA가 매일 아침 확인하는 리포트로 사용하기에는 개선이 필요하다.

이번 작업에서는 **AI 문장 품질보다 분석 데이터의 품질과 비교 기준을 개선하는 것**을 우선한다.

핵심 목표는 다음과 같다.

> 단순히 현재 값이나 누적값을 보여주는 리포트가 아니라, 최근 기간 동안 실제로 발생한 변화와 평소 대비 이상 징후를 보여주는 Daily Report로 개선한다.

---

# 1. 현재 리포트의 문제점

## 1.1 Summary와 본문의 상태가 일치하지 않음

현재 예시에서는:

```text
전체 상태: 주의

Critical: 0
Warning: 5
Info: 0
```

라고 표시되지만, 실제 `확인이 필요한 항목`에는 일부 Warning만 표시된다.

또한 마지막에는:

```text
현재는 특이사항이 없습니다.
즉시 조치가 필요하지 않습니다.
```

라고 출력되어 Summary와 모순된다.

### 개선 요구사항

- Critical / Warning / Info Count와 실제 Finding 개수가 반드시 일치해야 한다.
- Warning이 하나 이상 존재하면 `특이사항 없음`이라는 표현을 사용하지 않는다.
- Overall Status는 Findings를 기준으로 deterministic하게 결정한다.

예:

```text
CRITICAL 존재 → CRITICAL
WARNING 존재 → WARNING
INFO만 존재 → INFO
Finding 없음 → NORMAL
```

LLM이 임의로 Overall Status를 변경해서는 안 된다.

---

# 2. Performance Schema 누적값을 기간 Delta로 변경

현재 `events_statements_summary_by_digest`의 값을 그대로 사용하고 있다.

예:

```text
COUNT_STAR
SUM_TIMER_WAIT
SUM_ROWS_EXAMINED
SUM_ROWS_SENT
```

이 값들은 서버 기동 이후 또는 Performance Schema Reset 이후의 누적값이기 때문에 Daily Report에는 적절하지 않다.

예:

```text
어제 09:00
COUNT_STAR = 30,000,000

오늘 09:00
COUNT_STAR = 31,000,000
```

Daily Report에서는:

```text
최근 24시간 Execution Count = 1,000,000
```

으로 계산해야 한다.

## 구현 대상

SQL Digest별로 이전 Snapshot과 현재 Snapshot의 차이를 계산한다.

최소 다음 Delta를 계산한다.

```text
delta_count_star
delta_sum_timer_wait
delta_rows_examined
delta_rows_sent
delta_rows_affected
delta_tmp_tables
delta_tmp_disk_tables
delta_select_scan
delta_select_full_join
delta_no_index_used
delta_no_good_index_used
```

파생값:

```text
period_avg_latency
period_rows_examined_per_exec
period_rows_examined_ratio
period_tmp_disk_ratio
```

예:

```text
period_avg_latency =
delta_sum_timer_wait / delta_count_star
```

Performance Schema Reset 또는 DB Restart 때문에 현재값이 이전값보다 작아진 경우에는 Delta를 음수로 계산하지 않는다.

해당 Snapshot은 Reset으로 판단하여 별도로 처리한다.

---

# 3. Daily Report의 분석 기간 명확화

리포트에는 반드시 분석 대상 기간을 표시한다.

예:

```text
Analysis Window:
2026-08-23 09:00:00
~
2026-08-24 09:00:00
```

SQL, Lock, Counter Metric 분석은 가능하면 해당 기간의 Delta 기준으로 수행한다.

---

# 4. Baseline 비교 기능 추가

단순 `현재 vs 이전 Snapshot` 비교만으로는 부족하다.

Snapshot 데이터가 충분히 쌓인 경우 다음 Baseline을 계산한다.

```text
24h Average
7d Average
7d Median
7d P95
```

최소 우선순위:

```text
Current
Previous
7d Median
7d P95
```

Finding에서는 가능한 경우 다음 데이터를 포함한다.

```json
{
  "metric": "threads_running",
  "current": 13,
  "previous": 5,
  "baseline_median": 4,
  "baseline_p95": 8,
  "change_vs_median": 3.25
}
```

Snapshot 데이터가 부족하여 Baseline 계산이 불가능한 경우 프로그램이 실패해서는 안 된다.

예:

```text
baseline_status = INSUFFICIENT_DATA
```

형태로 처리한다.

---

# 5. 리포트 최상단에 "오늘의 주요 변화" 추가

DBA가 Daily Report에서 가장 먼저 보고 싶은 것은:

> 오늘 평소와 다른 것이 무엇인가?

이다.

따라서 Summary 바로 아래에 다음 섹션을 추가한다.

```markdown
## 오늘의 주요 변화

1. Digest ABC 평균 실행시간 증가
   - 이전: 1.2 ms
   - 현재 기간: 7.8 ms
   - 변화: +550%

2. Threads_running 증가
   - 현재: 13
   - 7d Median: 4
   - 7d P95: 8

3. Lock Wait 신규 발생
   - 어제: 0
   - 오늘: 3
```

유의미한 변화가 없으면:

```text
최근 분석 기간 동안 기준선 대비 유의미한 변화가 확인되지 않았습니다.
```

로 표시한다.

---

# 6. SQL Ranking 구조 개선

현재 Top SQL 하나에 여러 성격의 SQL이 섞여 있다.

특히 다음과 같은 SQL은 DBA 관점의 Top SQL 목록에서 정보 가치가 낮다.

```sql
COMMIT
ROLLBACK
SET autocommit = ?
SET NAMES ...
```

## 개선 요구사항

기본 Top SQL에서는 Transaction Control / Session Control Statement를 제외한다.

가능하면 DIGEST_TEXT 기준으로 필터링한다.

예:

```text
COMMIT
ROLLBACK
SET %
USE %
BEGIN
START TRANSACTION
```

단, 원본 데이터 자체를 삭제할 필요는 없다.

DBA Report의 기본 Ranking에서만 제외한다.

---

# 7. SQL Ranking을 목적별로 분리

다음 카테고리별 Top SQL을 제공한다.

## 7.1 Total DB Time Top

최근 분석 기간 동안 DB 시간을 가장 많이 소비한 SQL.

정렬:

```text
delta_sum_timer_wait DESC
```

Top 5.

---

## 7.2 Execution Count Top

가장 많이 호출된 SQL.

```text
delta_count_star DESC
```

Top 5.

---

## 7.3 Average Latency Top

평균 실행시간이 긴 SQL.

단, 실행 횟수가 지나치게 적은 SQL은 제외할 수 있도록 minimum execution threshold를 둔다.

예:

```text
delta_count_star >= 10
```

정렬:

```text
period_avg_latency DESC
```

---

## 7.4 Rows Examined Top

비효율적인 읽기 후보를 찾는다.

예:

```text
delta_rows_examined / delta_count_star
```

또는:

```text
delta_rows_examined / delta_rows_sent
```

사용.

Division by Zero 처리 필요.

---

## 7.5 Full Scan Top

```text
delta_select_scan
delta_select_full_join
```

기준.

---

## 7.6 Disk Temporary Table Top

```text
delta_tmp_disk_tables
```

기준.

---

# 8. SQL Regression 탐지 추가

단순 Top SQL보다 중요한 기능이다.

기존에는 빠르던 SQL이 최근 느려진 경우를 탐지해야 한다.

예:

```text
7d Median Avg Latency = 1.2 ms
Current Period Avg Latency = 8.7 ms

증가율 = +625%
```

다음 조건 등을 Rule로 사용한다.

예시:

```text
Current Avg Latency >= Baseline Median * 3

AND

delta_count_star >= minimum_execution_count
```

또는:

```text
Rows Examined Per Execution 증가율 >= threshold
```

SQL Regression Finding 예:

```json
{
  "category": "sql_regression",
  "severity": "WARNING",
  "digest": "ABC",
  "avg_latency_current_ms": 8.7,
  "avg_latency_baseline_ms": 1.2,
  "latency_change_ratio": 7.25,
  "execution_count": 21188
}
```

리포트:

```markdown
## SQL Regression

### Digest ABC

Avg Latency
- Baseline: 1.2 ms
- Current: 8.7 ms
- Change: +625%

Execution Count:
21,188

Rows Examined / Execution:
12 → 183
```

---

# 9. Finding에 근거 수치 표시

현재 AI가 다음처럼 표현한다.

```text
rows_examined_ratio가 매우 높습니다.
```

이 표현만으로는 판단 근거가 부족하다.

앞으로 Finding에는 반드시 가능한 경우 아래 내용을 포함한다.

```text
Current
Previous
Threshold
Baseline Median
Baseline P95
Change Rate
```

예:

```text
rows_examined_ratio

Current: 14.9
Previous: 3.1
7d Median: 2.1
Threshold: 10
```

AI는 이 값을 기반으로 설명한다.

---

# 10. Finding Lifecycle 추가

매일 같은 Warning이 반복되면 DBA 입장에서 신규 문제인지 기존 문제인지 알 수 없다.

Finding에 상태를 추가한다.

```text
NEW
PERSISTENT
RESOLVED
```

## NEW

이전 Report에서는 없었으나 현재 새로 발생.

## PERSISTENT

이전 Report에도 있었고 현재도 지속.

가능하면 연속 발생 일수도 저장한다.

예:

```text
PERSISTENT
3 days
```

## RESOLVED

이전 Report에서는 Warning/Critical이었지만 현재는 정상화.

---

# 11. Report에 Finding Lifecycle 표시

예:

```markdown
## 상태 변화

### NEW

- SQL Digest ABC Avg Latency 증가
- Lock Wait 발생

### PERSISTENT

- Temporary Disk Table Ratio
  - 3일 연속 Warning

### RESOLVED

- Connection Usage
  - 어제 Warning
  - 오늘 Normal
```

---

# 12. Connection Health 섹션 추가

다음 항목을 Daily Report에 표시한다.

```text
Threads_connected
Threads_running
max_connections
Connection Usage
Max_used_connections
Aborted_connects
Aborted_clients
```

가능하면 최근 24시간:

```text
Average
Maximum
7d Median
7d P95
```

를 표시한다.

예:

```text
Threads Connected

Current: 238
24h Max: 312
7d Median: 124
max_connections: 500

Usage: 47.6%
```

---

# 13. Transaction Health 추가

가능하면 `information_schema.innodb_trx` 또는 대응 Performance Schema를 이용한다.

표시:

```text
Current Transaction Count
Long Transaction Count
Longest Transaction Runtime
Lock Waiting Transaction Count
```

Long Transaction Rule은 Configurable하게 한다.

예:

```text
>= 60 sec → WARNING
>= 300 sec → CRITICAL
```

---

# 14. Lock Health 개선

현재 Snapshot 순간의 Lock Wait만 보면 중요한 이벤트를 놓칠 수 있다.

따라서 가능한 경우:

```text
Innodb_row_lock_waits
Innodb_row_lock_time
Innodb_row_lock_time_max
```

Counter Delta를 이용한다.

예:

```text
최근 24h Lock Wait 발생: 17
최근 24h Row Lock Time: xxxx ms
```

현재 Lock이 0이어도 분석 기간 중 Lock이 발생했다면 리포트에 나타나야 한다.

---

# 15. InnoDB Health 섹션 추가

최소 다음 지표를 분석한다.

```text
Buffer Pool Hit Ratio
Buffer Pool Usage
Dirty Page Ratio
Innodb_buffer_pool_wait_free
Innodb_log_waits
Innodb_row_lock_waits
```

특히 Counter Metric:

```text
Innodb_buffer_pool_wait_free
Innodb_log_waits
Innodb_row_lock_waits
```

는 기간 Delta로 분석한다.

단순 Buffer Pool Hit Ratio가 높다는 이유로 전체 InnoDB 상태를 정상으로 판단하지 않는다.

---

# 16. History List Length

DB 버전 및 수집 가능 여부에 따라 History List Length를 수집할 수 있도록 구조를 준비한다.

가능하다면:

```text
Current History List Length
Previous
Baseline
Trend
```

를 분석한다.

증가 추세가 지속되는 경우 Long Transaction 또는 Purge 지연 가능성을 Finding으로 생성한다.

단, History List Length만으로 Root Cause를 확정하지 않는다.

---

# 17. Table I/O도 기간 변화 중심으로 변경

현재:

```text
sample_orders 테이블 읽기 I/O가 가장 많습니다.
```

정도만 보여주는 것은 정보 가치가 낮다.

대신:

```text
최근 24시간 Read/Write
이전 기간
7d Median
증가율
```

을 비교한다.

예:

```text
sample_session_logs

Write Operations

Previous 24h: 1.2M
Current 24h: 4.8M
7d Median: 1.4M
Change: +300%
```

단순 `Top Table`과 `평소 대비 급증한 Table`을 구분한다.

---

# 18. DBA Action Items 섹션 추가

Daily Report 마지막에는 AI의 일반적인 설명 대신 실제 확인할 항목을 우선순위로 정리한다.

예:

```markdown
## 오늘 DBA 확인 권장

### Priority 1

Digest ABC

- Avg Latency +430%
- Rows Examined / Exec +680%
- Execution Count 14,213

확인 권장:

- EXPLAIN ANALYZE
- Index 사용 여부
- 최근 데이터 증가 여부

### Priority 2

Long Transaction

- Runtime: 247 sec

확인 권장:

- Transaction 내용
- Lock 보유 여부
- Application Transaction 범위

### 참고

sample_session_logs Write +220%

서비스 트래픽 증가 여부 확인
```

Action Item은 Finding에서 생성된 데이터를 기반으로 작성한다.

LLM이 근거 없는 Action을 추가해서는 안 된다.

---

# 19. LLM 역할 수정

LLM은 계속 분석 엔진이 아니라 Report Writer 역할을 수행한다.

LLM 입력에는 가능한 한 Raw Metric 전체를 전달하지 않는다.

다음과 같은 정제 데이터를 전달한다.

```text
Summary
Major Changes
Findings
Lifecycle
SQL Regression
SQL Ranking
Connection Health
Transaction Health
Lock Health
InnoDB Health
Table I/O Changes
```

LLM 역할:

1. 중요도 순서 정리
2. 관찰된 사실 설명
3. 가능한 원인 설명
4. 추가 확인 항목 제안
5. 중복 Finding 통합

LLM은 다음 세 가지를 명확히 구분해야 한다.

```text
Observed Facts
Possible Causes
Recommended Checks
```

Root Cause가 명확하지 않으면 확정 표현을 금지한다.

---

# 20. 권장 Daily Report 구조

최종적으로 Report를 다음 형태로 변경한다.

```markdown
# DBInsight Daily Report

Date:
Database:
DB Version:
Analysis Window:

## Overall Status

WARNING

New: 1
Persistent: 2
Resolved: 1

Critical: 0
Warning: 3
Info: 1

---

## 오늘의 주요 변화

1. Digest ABC Avg Latency +550%
2. Threads_running 7d Median 대비 3.2배
3. Lock Wait 3건 신규 발생

---

## 오늘 DBA 확인 권장

1. Digest ABC 실행계획 확인
2. Long Transaction 확인

---

## Finding 상태

### NEW
...

### PERSISTENT
...

### RESOLVED
...

---

## SQL Regression

...

---

## SQL Analysis

### Total DB Time Top
...

### Execution Count Top
...

### Average Latency Top
...

### Rows Examined Top
...

### Full Scan Top
...

### Disk Temporary Table Top
...

---

## Connection Health

...

---

## Transaction / Lock Health

...

---

## InnoDB Health

...

---

## Table I/O Changes

...

---

## Normal Metrics

...
```

---

# 21. 구현 우선순위

한 번에 모든 기능을 구현하지 말고 아래 순서로 진행한다.

## Priority 1

**Performance Schema Snapshot Delta**

가장 먼저 구현한다.

Daily Report가 누적값 대신 분석 기간 Delta를 사용할 수 있도록 한다.

---

## Priority 2

**Baseline**

```text
Previous
7d Median
7d P95
```

비교 가능하도록 한다.

---

## Priority 3

**SQL Regression Detection**

평소보다 성능이 악화된 SQL을 탐지한다.

---

## Priority 4

**Finding Lifecycle**

```text
NEW
PERSISTENT
RESOLVED
```

구현.

---

## Priority 5

**Daily Report 재구성**

```text
오늘의 주요 변화
DBA Action Items
Health Sections
```

추가.

---

# 22. 이번 작업에서 가장 중요한 원칙

현재 DBInsight에서 개선해야 할 핵심은 LLM 자체가 아니다.

현재:

```text
누적값
+
현재값
+
LLM
```

구조를:

```text
최근 기간 Delta
+
Baseline
+
Rule Engine
+
Finding Lifecycle
+
LLM Report
```

구조로 변경하는 것이 핵심이다.

최종적으로 DBA가 Daily Report를 열었을 때 1분 안에 다음 질문에 답할 수 있어야 한다.

```text
오늘 무엇이 달라졌는가?

새로운 문제가 발생했는가?

어제 문제는 계속되고 있는가?

어떤 SQL의 성능이 악화됐는가?

지금 가장 먼저 무엇을 확인해야 하는가?
```

이 기준으로 기존 코드를 검토하고, 우선 **Priority 1인 Performance Schema Snapshot Delta부터 구현**해줘.
