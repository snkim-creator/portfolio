# 경력기술서

## 기본 정보

| 항목 | 내용 |
|------|------|
| 이름 | 김성년 |
| 이메일 | clfska123@gmail.com |
| 학력 | 명지대학교 컴퓨터공학과 학사 졸업 |
| 자격증 | AWS SAA, SQLD, 정보처리기사 |

---

## 경력

### Rsupport (2021.07 ~ 현재) | DBA / 데이터 엔지니어

---

## 주요 업무 및 성과

### 1. MariaDB 운영 및 최적화

- MariaDB 이중화 구성(Master-Master) 운영 및 장애 대응
- EXPLAIN 기반 슬로우 쿼리 분석 및 인덱스 설계를 통한 쿼리 튜닝
- 커버링 인덱스, 복합 인덱스 설계 및 적용
- 전체 테이블(210개) 대상 Fragmentation 분석 및 OPTIMIZE 운영 기준 수립
- Performance Schema 운영 가이드 수립 (Lock 분석, 쿼리 성능 확인, 장애 대응)

---

### 2. MySQL → Oracle 데이터 마이그레이션

- **고객사 요청으로 MySQL → Oracle 데이터 마이그레이션 ksh 스크립트 제작 및 납품**
- 약 GB 중규모 데이터 실제 운영 환경에서 성공적으로 마이그레이션 완료
- `information_schema` 기반 테이블/컬럼 메타데이터 자동 조회로 전체 DB 자동 처리
- MySQL → Oracle 데이터 타입 자동 변환 (DATE, DATETIME, BIT, 숫자형, 문자열)
- NULL, 특수문자(\0, \r, \n, \t), 싱글쿼터 이스케이프 처리로 INSERT 오류 방지
- `INSERT ALL ~ SELECT 1 FROM DUAL` 구문으로 500건 단위 Batch INSERT 처리
- 접속 정보 환경변수 주입으로 스크립트 내 하드코딩 방지

---

### 3. 백업 자동화 시스템 구축

- mysqldump, Mariabackup, Binary Log 기반 백업 체계 구축 및 운영
- **AWS SSM Parameter Store + Run Command + EventBridge 기반 Cross-Account DB 백업 자동화 설계 및 주도**
  - 기존 통합 백업 서버 제거 → 각 DB 서버에서 독립적으로 백업 실행
  - SSM Parameter Store로 DB 비밀번호를 스크립트 외부에서 관리하여 보안 강화
  - EventBridge 스케줄로 일관된 시간에 동시 백업 시작, 백업 시간 편차 제거
  - S3 기반 백업 파일 저장 및 IAM 정책 관리

---

### 3. DB 보안 관리 및 접근 제어

- AWS EC2 Security Group 기반 IP/Port 단위 인바운드·아웃바운드 접근 제어
- DB 접속 계정 생성 및 권한 관리 (최소 권한 원칙 적용)
- **ISO 27001 / ISO 27017 보안 심사 대응**
  - 보안팀 점검 항목 수령 후 DB 영역 전체 보안 점검 수행
  - 점검 항목별 현황 파악 및 답변서 작성

---

### 4. 모니터링 시스템 구축

- Prometheus + Grafana 기반 MariaDB 모니터링 대시보드 구축
- sql_exporter를 활용한 커스텀 메트릭 추가 (InnoDB Lock Wait 수 등)
- Gmail 알람 연동으로 장애 즉시 감지 체계 구축

---

### 5. Airflow 기반 데이터 파이프라인 설계 및 운영

#### 프로젝트 계기

전략기획팀 데이터 활용 과정에서 외부 솔루션 업체가 파이프라인 1개 구축에 약 1,000만 원 수준의 비용을 제안한 상황을 확인하였고, 내부 기술 역량으로 직접 구축 가능하다고 판단하여 프로젝트를 진행하였습니다.

#### 주요 구현 내용

* MariaDB → GCS 증분 데이터 적재 파이프라인 설계 및 운영
* 테이블 특성에 따라 4가지 추출 전략 분리 설계

  * Full Snapshot
  * Year Snapshot
  * created_at 기반 Incremental
  * ID 기반 Incremental
* Control Table 기반 Watermark 패턴 적용으로 안정적인 증분 적재 구현
* DAG Factory 패턴 적용으로 신규 테이블 추가 시 설정만으로 Task 자동 생성 가능하도록 구조화
* MariaDB 특유의 bad date(`0000-00-00`) 및 null-like 문자열 정제 로직 구현
* Backfill을 고려한 날짜 처리 로직 적용 (`data_interval_start` 기반)
* GCS 업로드 실패 시 Watermark Commit 방지 구조 적용
* AWS SES SMTP 기반 Task 실패 이메일 알림 시스템 구축

#### 성과

* 외부 솔루션 구축 비용(파이프라인당 약 1,000만 원) 절감
* 주간 반복 데이터 전달 업무 자동화를 통해 주당 약 1~2시간의 수작업 제거
* 설정 기반 DAG 구조 도입으로 신규 적재 파이프라인 확장 용이성 확보
* 운영 안정성과 재처리(backfill) 대응 가능한 배치 구조 구축


---

### 6. Google Drive 데이터 업로드 자동화

#### 프로젝트 계기
사내 일부 부서에 통계 데이터를 주기적으로 Google Drive를 통해 전달하는 업무가 반복적으로 수작업 처리되고 있었으며, 데이터 요청 및 전달 과정에서 운영 효율이 떨어지는 문제를 확인하여 자동화 프로젝트를 진행하였습니다.

#### 주요 구현 내용
- MariaDB 데이터 추출 후 CSV 변환 및 FTP 기반 서버 간 파일 전송 자동화
- Google Service Account 기반 Google Drive API 연동으로 CSV 파일 자동 업로드 구현
- 파일별 다운로드/공유 권한 설정 기능 구현
- Crontab 기반 주 1회 스케줄 자동 실행 환경 구성
- 연도/주차 기반 파일명 자동 생성 로직 구현

#### 성과
- 약 15건 규모의 정기 데이터 전달 업무 자동화
- 반복적인 데이터 요청 및 전달 과정 단축으로 운영 병목 감소
- 수작업 기반 파일 업로드 업무 제거를 통해 운영 효율 향상
- 담당자 개입 없이 주간 데이터 전달이 가능한 무인 운영 환경 구축

  
---

### 7. BI 대시보드 구축 및 셀프서비스 환경 구축

- Apache Superset, Tableau를 활용한 데이터 시각화 및 BI 대시보드 구축
- 제품 사용 통계, 에러 발생 현황, 신규 고객 추이, 로그인 통계, 실시간 현황 등 대시보드 제작
- **마케팅팀 수신 거부 리스트 수동 제공 업무를 Superset 대시보드로 전환하여 반복 요청 업무 제거 및 유관부서 셀프서비스 환경 구축**

---

---

### 8. AWS CloudWatch Logs ETL 파이프라인 구축

### 프로젝트 계기
사내 시스템 로그가 AWS CloudWatch Logs에서만 조회 가능하여 접근성이 제한적이었고, Logs Insights 기반의 복잡한 쿼리를 직접 작성해야 하는 불편함이 존재했습니다.
개발자 및 PM 조직에서도 시스템 로그 데이터를 보다 쉽게 조회하고 분석할 수 있도록 로그 ETL 파이프라인 구축 프로젝트를 진행하였습니다.

#### 주요 구현 내용
- HAProxy Access Log, Tomcat Error Log를 CloudWatch Logs Insights에서 매 시간 자동 수집
- CloudWatch Logs Insights 쿼리 실행 → 배치 수집 → ColumnStore 적재 3단계 DAG 설계
- XCom 기반 Task 간 query_id 전달 (비동기 쿼리 결과 조회 패턴 적용)
- 제너레이터 패턴으로 배치 단위 결과 처리 및 pandas executemany() 기반 일괄 적재
- HAProxy 로그 17개 컬럼 파싱, Tomcat ERROR 로그 trace_id/span_id 구조화 적재
- 인프라 담당자와 협업하여 CloudWatch Insights 쿼리 작성

#### 성과
- 장애 발생 시 시스템 엔지니어 외 개발자, PM 조직에서도 로그 데이터를 직접 조회 및 활용 가능하도록 데이터 접근성 개선
- CloudWatch Logs 직접 조회 없이 DW 기반 SQL 조회 환경 및 Apache Superset을 활용할 수 있는 환경 제공
- 로그 데이터 구조화를 통해 장애 분석 및 서비스 이슈 추적 효율 향상
- 반복적인 Logs Insights 조회 작업 감소 및 분석 생산성 향상

#### 회고
기술적으로는 로그 접근성과 분석 편의성을 개선할 수 있었지만, 실제 조직 내 활용도는 기대보다 높지 않았습니다.

기존에는 개발자 조직이 시스템 엔지니어에게 직접 로그 조회를 요청하는 방식으로 운영되고 있었으며, 해당 프로세스가 사용자 입장에서 충분히 큰 불편으로 인식되지 않았던 점이 주요 원인이었습니다.

이 경험을 통해 단순히 기술적으로 우수한 시스템을 만드는 것뿐만 아니라, 실제 사용자의 Pain Point와 조직의 업무 흐름을 함께 고려하는 것이 중요하다는 점을 배울 수 있었습니다.

---

## 기술 스택

| 분야 | 기술 |
|------|------|
| Database | MariaDB, MySQL |
| Data Engineering | Apache Airflow, Pandas |
| Cloud | AWS (EC2, S3, Lambda, EventBridge, SSM, SES), GCP (Cloud Storage) |
| Monitoring | Prometheus, Grafana, sql_exporter |
| BI | Apache Superset, Tableau |
| Language | Python, Shell Script, SQL |
| Certifications | AWS SAA, SQLD |
