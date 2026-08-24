# DBInsight MVP PRD

## 1. 프로젝트 개요

### 1.1 프로젝트명

**DBInsight**

### 1.2 목적

MySQL/MariaDB의 Performance Schema, Global Status, 시스템 리소스 데이터를 정기적으로 수집하고, 수집한 데이터를 기준선(Baseline)과 비교하여 이상 징후를 추출한 뒤 AI가 DBA 관점에서 확인해야 할 내용을 요약한 리포트를 생성한다.

MVP에서는 완전한 장애 탐지 시스템이나 실시간 모니터링 시스템을 목표로 하지 않는다.

첫 번째 목표는 다음과 같다.

> DBA가 매일 직접 여러 모니터링 지표와 Performance Schema를 조회하지 않아도, 중요한 변화와 확인이 필요한 항목을 정리한 Daily Health Report를 받을 수 있도록 한다.

---

# 2. MVP 실행 환경

MVP는 별도 서버를 구성하지 않고 **개인 Windows 데스크탑에서 실행**한다.

## 개발 및 실행 환경

- OS: Windows 10/11
- Language: Python 3.11 이상
- DB Connection: PyMySQL 또는 mysql-connector-python
- Local Storage: SQLite
- Data Processing: pandas
- Configuration: YAML
- Scheduler: APScheduler 또는 Windows Task Scheduler
- AI API: OpenAI API 또는 Claude API
- Output:
  - Markdown 파일
  - 콘솔 출력
- Version Control: Git

Docker는 MVP 필수 요구사항이 아니다.

초기 개발에서는 복잡성을 줄이기 위해 Python Virtual Environment를 사용한다.

```text
Python
  ↓
MySQL / MariaDB
  ↓
SQLite
  ↓
Rule Analyzer
  ↓
LLM
  ↓
Markdown Report
```

---

# 3. MVP 범위

## 포함

MVP에서는 **MySQL/MariaDB 한 대**만 대상으로 한다.

구현 대상:

1. DB 접속
2. 서버 기본 정보 수집
3. Performance Schema 데이터 수집
4. Global Status 수집
5. 주요 DB 상태 데이터 수집
6. 로컬 SQLite에 Snapshot 저장
7. 과거 Snapshot과 현재 데이터 비교
8. 기본 Rule 기반 이상 징후 판단
9. AI를 통한 Daily Health Report 생성
10. Markdown 파일 저장

## 제외

MVP에서는 다음 기능을 구현하지 않는다.

- 다중 DB 서버 관리
- Web UI
- Grafana 구축
- Prometheus 구축
- Slack / Telegram 알림
- 실시간 장애 감지
- 자동 장애 복구
- SQL 자동 Kill
- SQL 자동 튜닝
- DB Parameter 자동 변경
- 머신러닝 기반 Anomaly Detection
- Vector DB
- RAG
- Kubernetes
- Docker 기반 배포
- 사용자 인증
- 권한 관리

위 기능들은 MVP 검증 이후 확장한다.

---

# 4. 핵심 사용자

주 사용자는 DBA이다.

사용자가 원하는 것은 다음과 같다.

기존에는 DBA가 직접 다음 데이터를 확인해야 한다.

```text
Grafana
Performance Schema
SHOW GLOBAL STATUS
SHOW ENGINE INNODB STATUS
Slow Query
Connection
Lock
Transaction
Disk / CPU / Memory
```

MVP에서는 이 데이터를 자동으로 정리하여 다음 질문에 답한다.

> 오늘 DB에서 평소와 달라진 것은 무엇인가?

> 지금 확인해야 할 항목은 무엇인가?

> 어떤 SQL이 DB 부하에 영향을 주고 있는가?

> Connection, Lock, Transaction 등에 위험 신호가 있는가?

---

# 5. 핵심 설계 원칙

## 5.1 LLM이 직접 모든 데이터를 판단하지 않는다

다음 구조를 사용한다.

```text
Raw Data
   ↓
Normalization
   ↓
Rule Engine
   ↓
Finding
   ↓
LLM
   ↓
Human-readable Report
```

다음 구조는 사용하지 않는다.

```text
Performance Schema 전체
      ↓
     LLM
      ↓
장애 여부 판단
```

LLM은 **분석 엔진이 아니라 설명 및 요약 계층**으로 사용한다.

---

# 6. 전체 Architecture

```text
┌─────────────────────────┐
│ MySQL / MariaDB         │
│                         │
│ Performance Schema      │
│ information_schema      │
│ Global Status           │
│ Global Variables        │
└────────────┬────────────┘
             │
             │ SQL
             ▼
┌─────────────────────────┐
│ Collector               │
│ Python                  │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ SQLite                  │
│                         │
│ snapshots               │
│ metrics                 │
│ sql_digest              │
│ findings                │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ Analyzer                │
│                         │
│ Baseline                │
│ Delta                   │
│ Rule Engine             │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ Findings                │
│                         │
│ Normal                  │
│ Warning                 │
│ Critical                │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ LLM                     │
│                         │
│ Findings 설명           │
│ 확인 포인트 정리        │
│ Daily Report 생성       │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ Markdown Report         │
└─────────────────────────┘
```

---

# 7. 프로젝트 디렉터리

```text
DBInsight/

├─ app/
│  ├─ collector/
│  │  ├─ mysql_collector.py
│  │  ├─ status_collector.py
│  │  └─ performance_schema_collector.py
│  │
│  ├─ analyzer/
│  │  ├─ baseline.py
│  │  ├─ rules.py
│  │  └─ findings.py
│  │
│  ├─ ai/
│  │  ├─ client.py
│  │  ├─ prompt.py
│  │  └─ reporter.py
│  │
│  ├─ storage/
│  │  ├─ sqlite.py
│  │  └─ repository.py
│  │
│  └─ main.py
│
├─ queries/
│  ├─ mysql/
│  │  ├─ global_status.sql
│  │  ├─ statement_digest.sql
│  │  ├─ table_io.sql
│  │  ├─ lock_wait.sql
│  │  └─ transaction.sql
│
├─ config/
│  └─ config.example.yaml
│
├─ data/
│  └─ dbinsight.db
│
├─ reports/
├─ tests/
├─ .env.example
├─ .gitignore
├─ requirements.txt
└─ README.md
```

---

# 8. Configuration

DB 접속정보와 API Key를 코드에 직접 작성하지 않는다.

`.env`

```text
DB_PASSWORD=example
AI_API_KEY=example
```

`config.yaml`

```yaml
database:
  host: 10.0.0.10
  port: 3306
  user: db_monitor
  password_env: DB_PASSWORD
  database: performance_schema

collector:
  interval_minutes: 10

report:
  output_directory: ./reports

ai:
  provider: openai
  model: MODEL_NAME
```

실제 `.env`와 `config.yaml`은 Git에 Commit하지 않는다.

---

# 9. DB 계정

수집 전용 계정을 사용한다.

원칙:

- DML 권한 없음
- DDL 권한 없음
- 관리자 권한 없음
- 가능한 범위 내 최소 권한 사용

MVP 개발 단계에서는 실제 필요한 권한을 확인하여 별도 문서화한다.

---

# 10. 수집 데이터

## 10.1 서버 기본정보

다음 정보를 Snapshot마다 함께 기록한다.

```sql
SELECT VERSION();
SELECT @@hostname;
SELECT @@port;
SELECT @@server_uuid;
SELECT @@uptime;
```

가능하면 다음도 저장한다.

- MySQL / MariaDB 여부
- DB Version
- Server Hostname
- Snapshot Time

---

# 11. Global Status

최소 다음 항목을 수집한다.

### Connection

```text
Threads_connected
Threads_running
Connections
Max_used_connections
Aborted_connects
Aborted_clients
```

### Query

```text
Queries
Questions
Slow_queries
Com_select
Com_insert
Com_update
Com_delete
```

### InnoDB Buffer Pool

```text
Innodb_buffer_pool_read_requests
Innodb_buffer_pool_reads
Innodb_buffer_pool_pages_total
Innodb_buffer_pool_pages_free
Innodb_buffer_pool_pages_dirty
```

### InnoDB I/O

```text
Innodb_data_reads
Innodb_data_writes
Innodb_data_read
Innodb_data_written
Innodb_data_fsyncs
```

### Row Operations

```text
Innodb_rows_read
Innodb_rows_inserted
Innodb_rows_updated
Innodb_rows_deleted
```

### Lock

```text
Innodb_row_lock_current_waits
Innodb_row_lock_time
Innodb_row_lock_time_max
Innodb_row_lock_waits
```

### Temporary Table

```text
Created_tmp_tables
Created_tmp_disk_tables
```

### Table Cache

```text
Opened_tables
Open_tables
Table_open_cache_hits
Table_open_cache_misses
```

---

# 12. Performance Schema

## 12.1 SQL Digest

사용:

```text
performance_schema.events_statements_summary_by_digest
```

최소 수집 컬럼:

```text
SCHEMA_NAME
DIGEST
DIGEST_TEXT
COUNT_STAR
SUM_TIMER_WAIT
MIN_TIMER_WAIT
AVG_TIMER_WAIT
MAX_TIMER_WAIT
SUM_ROWS_AFFECTED
SUM_ROWS_SENT
SUM_ROWS_EXAMINED
SUM_CREATED_TMP_DISK_TABLES
SUM_CREATED_TMP_TABLES
SUM_SELECT_SCAN
SUM_SELECT_FULL_JOIN
SUM_NO_INDEX_USED
SUM_NO_GOOD_INDEX_USED
FIRST_SEEN
LAST_SEEN
```

## 12.2 Top SQL

각 Snapshot 시점에서 다음 기준으로 Top SQL을 추출한다.

- Total Latency: `SUM_TIMER_WAIT DESC`
- Average Latency: `AVG_TIMER_WAIT DESC`
- Execution Count: `COUNT_STAR DESC`
- Rows Examined: `SUM_ROWS_EXAMINED DESC`

각 기준 Top 10 정도만 저장해도 된다.

---

# 13. Table I/O

```text
performance_schema.table_io_waits_summary_by_table
```

최소:

```text
OBJECT_SCHEMA
OBJECT_NAME
COUNT_READ
COUNT_WRITE
SUM_TIMER_READ
SUM_TIMER_WRITE
```

---

# 14. Transaction / Lock

```text
information_schema.innodb_trx
```

또는 Performance Schema 기반 Transaction/Lock 정보를 사용한다.

최소 수집:

```text
Transaction Count
Running Transaction Count
Longest Transaction Time
Lock Waiting Transaction Count
```

가능하면 다음도 저장한다.

```text
trx_id
trx_started
trx_state
trx_mysql_thread_id
trx_query
```

단, SQL 원문 저장에 민감정보가 포함될 수 있으므로 추후 Masking 기능을 고려한다.

---

# 15. Baseline

## MVP 1차 버전

```text
Current Value
Previous Value
Delta
Delta %
```

예:

```text
Threads_connected

previous: 84
current: 213
change: +129
change_rate: +153.6%
```

## MVP 2차 버전

Snapshot이 충분히 쌓인 이후:

```text
24h Average
7d Average
7d Median
7d P95
Current / Median Ratio
Current / P95 Ratio
```

를 추가한다.

---

# 16. Counter Metric 처리

Global Status에는 누적 Counter가 많다.

따라서 단순 현재값을 비교해서는 안 된다.

예:

```text
Queries

10:00
1,000,000

10:10
1,060,000
```

실제 10분간 Query:

```text
60,000
```

QPS:

```text
60,000 / 600
= 100 QPS
```

Metrics마다 다음 Type을 정의한다.

```text
GAUGE
COUNTER
RATIO
DERIVED
```

---

# 17. Derived Metrics

## Buffer Pool Hit Ratio

```text
1 -
Innodb_buffer_pool_reads
/
Innodb_buffer_pool_read_requests
```

## Temporary Disk Table Ratio

```text
Created_tmp_disk_tables
/
Created_tmp_tables
```

## Connection Usage

```text
Threads_connected
/
max_connections
```

## Rows Examined Ratio

```text
SUM_ROWS_EXAMINED
/
SUM_ROWS_SENT
```

단, `SUM_ROWS_SENT = 0` 처리 필요.

## Dirty Page Ratio

```text
Innodb_buffer_pool_pages_dirty
/
Innodb_buffer_pool_pages_total
```

---

# 18. Rule Engine

LLM 호출 전에 Python 코드로 이상 여부를 판단한다.

Finding 구조:

```json
{
  "category": "connection",
  "metric": "connection_usage",
  "severity": "WARNING",
  "current": 0.87,
  "baseline": 0.42,
  "message": "Connection usage increased significantly."
}
```

Severity:

```text
NORMAL
INFO
WARNING
CRITICAL
```

---

# 19. 초기 Rule

Threshold는 Configuration으로 관리한다.

## Connection

```text
Connection Usage >= 70% → INFO
Connection Usage >= 80% → WARNING
Connection Usage >= 90% → CRITICAL
```

## Threads Running

```text
Current >= Baseline Median * 3
AND Current >= 10
→ WARNING
```

## Slow Query 증가

```text
Slow Query Rate가 이전 Snapshot 대비 급증
→ WARNING
```

## Temporary Disk Table

```text
Tmp Disk Table Ratio >= 20%
→ WARNING
```

## Lock Wait

```text
현재 Lock Waiting Transaction > 0
→ WARNING
```

지속 시간이 일정 시간 이상이면 `CRITICAL`.

## Long Transaction

```text
Transaction Runtime >= 60 sec
→ WARNING

Transaction Runtime >= 300 sec
→ CRITICAL
```

## SQL Rows Examined

```text
Rows Examined / Rows Sent >= threshold
AND
Execution Count >= minimum executions
```

## SQL Latency

```text
AVG_TIMER_WAIT 증가율이 기준선 대비 300% 이상
AND
COUNT_STAR 일정 수준 이상
```

이면 Warning.

---

# 20. Finding 우선순위

LLM에는 모든 Metrics를 보내지 않는다.

Rule Engine이 생성한 Finding 중심으로 전달한다.

```json
{
  "database": "test-db",
  "snapshot_time": "2026-08-18 09:00:00",
  "summary": {
    "critical": 0,
    "warning": 3,
    "info": 2
  },
  "findings": [
    {
      "severity": "WARNING",
      "category": "connection",
      "metric": "connection_usage",
      "current": 87,
      "baseline": 43
    },
    {
      "severity": "WARNING",
      "category": "sql",
      "digest": "abc123",
      "avg_latency_ms": 1850,
      "baseline_ms": 210,
      "execution_count": 14213
    }
  ]
}
```

---

# 21. AI 역할

AI는 다음 업무만 담당한다.

1. Finding을 DBA 관점에서 설명
2. 서로 연관된 Finding 연결
3. 우선순위 정리
4. 확인해야 할 데이터 제안
5. 사람이 읽기 좋은 Daily Report 작성

AI가 다음 작업을 수행해서는 안 된다.

- SQL 실행
- DB Parameter 변경
- Process Kill
- DB Restart
- Index 자동 생성
- 데이터 변경
- 확정적인 Root Cause 선언

---

# 22. AI Prompt 요구사항

```text
You are a senior MySQL/MariaDB DBA assistant.

Your role is to analyze already-processed database findings
and create a concise daily database health report.

Do not assume causality without sufficient evidence.

Clearly distinguish:

- observed facts
- possible causes
- recommended checks

Do not recommend destructive actions.

Prioritize issues that require DBA attention.

If metrics appear normal, explicitly state that no immediate
action is required.
```

---

# 23. Daily Report

파일명:

```text
reports/
2026-08-18_db_health_report.md
```

---

# 24. SQLite Schema

## snapshots

```text
id
server_id
snapshot_time
db_version
created_at
```

## metrics

```text
id
snapshot_id
metric_name
metric_type
metric_value
```

## sql_digest_metrics

```text
id
snapshot_id
schema_name
digest
digest_text
execution_count
total_latency
avg_latency
rows_examined
rows_sent
tmp_tables
tmp_disk_tables
no_index_used
```

## findings

```text
id
snapshot_id
category
severity
metric
current_value
baseline_value
description
created_at
```

## reports

```text
id
snapshot_id
report_date
report_path
ai_provider
ai_model
created_at
```

---

# 25. 실행 방식

```bash
python -m app.main collect
python -m app.main analyze
python -m app.main report
python -m app.main run
```

전체 실행:

```text
Collect
 ↓
Store
 ↓
Analyze
 ↓
Generate Findings
 ↓
AI Report
 ↓
Save Markdown
```

---

# 26. Scheduler

MVP 테스트 단계에서는 수동 실행을 우선한다.

기능 검증 후 Windows Task Scheduler를 이용한다.

```text
10분마다
python -m app.main collect
```

```text
매일 오전 09:00
python -m app.main report
```

---

# 27. Logging

Python `logging` 모듈을 사용한다.

```text
logs/
app.log
```

최소 기록:

```text
Collector Start
Collector End
DB Connection Error
Query Error
Snapshot ID
Analyzer Start
Finding Count
AI API Request
AI API Error
Report Generated
```

---

# 28. Error Handling

다음 상황에서 전체 프로그램이 비정상 종료되지 않도록 한다.

- DB Connection Failure
- 특정 Performance Schema Table 미존재
- MySQL/MariaDB 버전 차이
- Query Permission 부족
- AI API Failure
- SQLite Write Failure
- Metric 값 NULL
- Division by Zero
- DB Restart로 Counter 초기화

AI 호출이 실패하더라도 Finding은 보존해야 한다.

---

# 29. MySQL / MariaDB 호환

MVP에서 우선 하나의 DB 버전을 대상으로 개발한다.

코드 구조상 다음 구분은 가능해야 한다.

```text
MySQL 8.0
MariaDB 10.x
MariaDB 11.x
```

---

# 30. 보안 요구사항

- DB Password Git Commit 금지
- API Key Git Commit 금지
- `.env` Git Ignore
- DB Read Only 계정 사용
- AI에 Password 전달 금지
- AI에 Connection String 전달 금지
- SQL Literal Masking 향후 고려
- 개인정보가 포함될 가능성이 있는 SQL은 AI 전달 시 주의
- Raw SQL보다 Digest Text 우선

---

# 31. MVP 완료 기준

## 데이터 수집

- [ ] Windows에서 Python 프로그램 실행 가능
- [ ] MySQL/MariaDB 접속 가능
- [ ] Global Status 수집 가능
- [ ] Performance Schema SQL Digest 수집 가능
- [ ] SQLite Snapshot 저장 가능

## 분석

- [ ] Snapshot 간 Delta 계산 가능
- [ ] Counter Metric 처리 가능
- [ ] 최소 5개 이상의 Rule 구현
- [ ] Finding 생성 가능

## AI

- [ ] Finding JSON 생성 가능
- [ ] LLM API 호출 가능
- [ ] DBA 관점의 Markdown Report 생성 가능

## 운영

- [ ] `.env` 기반 Secret 관리
- [ ] Logging 구현
- [ ] 오류 발생 시 로그 확인 가능
- [ ] README를 보고 다른 환경에서도 실행 가능

---

# 32. 초기 구현 우선순위

## Phase 1 — Collector

```text
DB
 ↓
Python
 ↓
SQLite
```

수집:

```text
Global Status
Global Variables
SQL Digest
Transaction
```

## Phase 2 — Analyzer

```text
Snapshot A
Snapshot B
 ↓
Delta
 ↓
Rules
 ↓
Finding
```

## Phase 3 — AI Report

```text
Finding
 ↓
LLM
 ↓
Markdown
```

## Phase 4 — Scheduler

```text
10분 단위 Snapshot
1일 1회 Report
```

---

# 33. Claude에게 요청하는 첫 개발 작업

한 번에 프로젝트 전체를 구현하지 않는다.

## Task 1

Windows에서 실행 가능한 Python 프로젝트 기본 구조를 생성한다.

구현 범위:

1. Python 프로젝트 구조 생성
2. requirements.txt
3. `.env.example`
4. `config.example.yaml`
5. MySQL Connection Module
6. SQLite 초기화 Module
7. Snapshot Table 생성
8. Global Status Collector
9. `events_statements_summary_by_digest` Collector
10. SQLite 저장
11. CLI `collect` Command
12. Logging
13. README

아직 구현하지 않을 것:

```text
AI
Analyzer
Baseline
Scheduler
Web UI
```

---

# 34. Task 1 검증 시나리오

```bash
python -m app.main collect
```

정상 동작 시:

```text
[INFO] Connected to MySQL
[INFO] DB Version: MySQL 8.0.x
[INFO] Collecting Global Status
[INFO] Collected xxx metrics
[INFO] Collecting SQL Digest
[INFO] Collected xx digests
[INFO] Snapshot saved
[INFO] Snapshot ID: 1
```

SQLite의 다음 테이블에 데이터가 존재해야 한다.

```text
snapshots
metrics
sql_digest_metrics
```

---

# 35. 향후 확장

### Phase A
```text
One DB
Daily Report
```

### Phase B
```text
Multiple DB
```

### Phase C
```text
Prometheus API Integration
CPU
Memory
Disk
Network
```

### Phase D
```text
Anomaly Detection
Baseline Median
P95
Trend
```

### Phase E
```text
Incident Detection
```

### Phase F
```text
Slack / Telegram Alert
```

### Phase G
```text
Web Dashboard
```

### Phase H
```text
Amazon Linux 2023 EC2 배포
```

---

# 36. 최종 목표

최종적으로는 DBA가 여러 시스템을 직접 순회하며 데이터를 확인하는 대신 다음 결과를 받는 것을 목표로 한다.

```text
DB Daily Health Report

오늘 확인이 필요한 DB: 2대

PROD-DB-01
WARNING

- Connection 평소 대비 2.8배 증가
- SQL Digest ABC 평균 실행시간 5.4배 증가
- Lock Wait 3건 발생

PROD-DB-03
WARNING

- History List Length 지속 증가
- 17분 이상 실행 중인 Transaction 존재

나머지 8대
특이사항 없음
```

서비스의 핵심 가치는 단순한 Monitoring Dashboard가 아니다.

> **DBA가 데이터를 찾아보는 시간을 줄이고, 어떤 데이터를 먼저 확인해야 하는지 자동으로 정리해주는 시스템을 만드는 것**

을 목표로 한다.
