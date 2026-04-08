# Sung-Nyeon Kim | Data Engineer / DBA Portfolio

## About Me

MariaDB DBA 5년차로 데이터 엔지니어링 업무를 병행하고 있습니다.  
데이터베이스 운영 경험을 바탕으로 안정적인 데이터 파이프라인 설계와 운영에 관심이 있습니다.

- **Email** : clfska123@gmail.com
- **Certifications** : AWS SAA, SQLD

---

## Skills

| 분야 | 기술 |
|------|------|
| Database | MariaDB, MySQL, PostgreSQL |
| Data Engineering | Apache Airflow, Pandas |
| Cloud | AWS (EC2, Lambda, EventBridge, SSM, SES), GCP (Cloud Storage) |
| Monitoring | Prometheus, Grafana, sql_exporter |
| BI | Tableau, Apache Superset |
| Language | Python, Shell Script, SQL |

---

## Projects

### 1. Airflow 기반 MySQL → GCS 증분 데이터 파이프라인
> `Airflow` `Python` `Pandas` `GCS` `MariaDB`

MySQL 데이터베이스에서 데이터를 추출하여 Google Cloud Storage에 자동 적재하는 파이프라인을 설계 및 운영하였습니다.

**주요 구현 내용**
- 테이블 특성에 따라 4가지 추출 전략을 분리 설계
  - Full Snapshot / Year Snapshot / created_at 기반 / ID 기반 증분(Incremental)
- Control Table 기반 Watermark 패턴으로 증분 추출 구현
- DAG Factory 패턴 적용 - 딕셔너리 설정만으로 테이블별 Task 자동 생성
- MariaDB 특유의 bad date(`0000-00-00`) 및 null-like 문자열 정제 로직 구현
- Backfill을 고려한 날짜 로직 적용 (`data_interval_start` 기준)
- GCS 업로드 실패 시 Watermark가 커밋되지 않도록 트랜잭션 설계
- Task 실패 시 AWS SES 이메일 알림 연동

📁 [airflow-etl](./data-engineering/airflow-etl)

---

### 2. Google Drive 데이터 업로드 자동화
> `Python` `Google Drive API` `OAuth2` `Crontab` `FTP`

매주 반복되는 MariaDB 데이터 수동 업로드 업무를 자동화한 프로젝트입니다.

**주요 구현 내용**
- Google Drive API v3 + OAuth2 서비스 계정 기반 인증 구현
- Access Token 만료 시 Refresh Token으로 자동 갱신하여 무인 실행 환경 대응
- FTP를 통한 DB 서버 간 파일 전송 후 Google Drive 업로드
- 파일별 다운로드/복사/공유 권한 세밀하게 설정
- 업로드 후 파일 소유권 담당자 계정으로 자동 이전
- Crontab 스케줄로 주 1회 자동 실행
- 연도/주차 기반 파일명 자동 생성 (예: FILE1_2026_15.csv)

📁 [google-drive-upload](./data-engineering/google-drive-upload)

---

### 3. Airflow Task 실패 이메일 알림 시스템 구축
> `Airflow` `AWS SES` `SMTP` `AWS IAM`

데이터 파이프라인 운영 중 Task 실패 시 자동으로 이메일 알림을 전송하는 시스템을 구축하였습니다.

**주요 구현 내용**
- AWS SES SMTP를 활용한 Airflow 이메일 알림 설정
- Airflow Private Subnet 환경에서 NAT Gateway를 통한 SES 통신 구성
- IAM 정책에 `aws:SourceIp` 조건을 적용하여 허용된 서버에서만 메일 전송 가능하도록 보안 설계

📁 [airflow-email-alert](./data-engineering/airflow-email-alert)

---

### 3. Prometheus 커스텀 메트릭 구축 (MariaDB InnoDB Lock Wait)
> `Prometheus` `Grafana` `sql_exporter` `MariaDB`

기본 `mysqld_exporter`에서 제공하지 않는 InnoDB Lock Wait 수를 커스텀 메트릭으로 수집하는 모니터링 시스템을 구축하였습니다.

**주요 구현 내용**
- `sql_exporter`를 활용해 SQL 쿼리 결과를 Prometheus 메트릭으로 변환
- Lock Wait 급증 시 Grafana 알람 연동
- 최소 권한 원칙 적용 (PROCESS 권한만 부여)
- systemd 등록으로 서비스 자동 재시작 구성
- 커스텀 메트릭 추가가 용이한 확장 가능한 구조로 설계

📁 [monitoring](./dba/monitoring)

---

### 4. MariaDB 테이블 Fragmentation 분석 및 OPTIMIZE 운영 기준 수립
> `MariaDB` `SQL` `DBA`

운영 중인 MariaDB 서버의 210개 테이블 전체를 대상으로 `DATA_FREE` 기반 fragmentation 상태를 분석하고, 실무 관점의 OPTIMIZE 실행 기준을 수립하였습니다.

**주요 구현 내용**
- `information_schema.tables` 기반 fragmentation 점검 SQL 작성
- 테이블 크기, free 공간 절대값, free 비율을 기준으로 4단계 판정 기준 수립
- 로그/세션/이력성 테이블의 구조적 특성을 고려한 보류 기준 적용
- 즉시 실행 대신 추세 모니터링이 적합한 근거를 분석 문서로 정리
- OPTIMIZE 후보 자동 추출 SQL 및 실행 스크립트 작성

📁 [dba/optimize-analysis](./dba/mysql operate/optimize-analysis)

---

### 5. MariaDB Performance Schema 운영 가이드 수립
> `MariaDB` `Performance Schema` `DBA`

MariaDB 10.11.9 운영 환경에서 Lock 분석, 쿼리 성능 확인, 장애 대응을 목적으로 Performance Schema 설정 기준과 운영 가이드를 수립하였습니다.

**주요 구현 내용**
- 운영 기본안 / 장애 분석 확장안 / 원복 스크립트 3단계로 구성
- Master-Master 양방향 Sync 환경을 고려한 설정 적용
- Lock 발생 시 문제 쿼리 추적을 위한 조회 SQL 세트 작성
- stage 계열은 상시 OFF, 장애 시만 활성화하는 보수적 운영 기준 적용

📁 [dba/performance-schema](./dba/mysql operate/performance-schema)

---

## Repository Structure

```
portfolio/
├── README.md
│
├── data-engineering/
│     ├── airflow-etl/
│     │     ├── README.md
│     │     └── salesdata_mysql_to_gcs.py
│     │
│     ├── google-drive-upload/
│     │     ├── README.md
│     │     └── google_drive_upload.py
│     │
│     └── airflow-email-alert/
│           └── README.md
│
└── dba/
      ├── mysql-to-oracle-migration/
      │     ├── README.md
      │     └── mysql_to_oracle.ksh
      ├── monitoring/
      │     └── README.md
      ├── optimize-analysis/
      │     └── README.md
      └── performance-schema/
            └── README.md
```
