# Airflow 기반 MySQL → GCS 증분 데이터 파이프라인

## 개요

MySQL 데이터베이스에서 데이터를 추출하여 Google Cloud Storage(GCS)에 자동 적재하는 데이터 파이프라인입니다.  
Apache Airflow DAG로 구성하였으며, 테이블 특성에 따라 추출 전략을 분리 설계하였습니다.

## 아키텍처

```
MySQL Database
      ↓ (SQL Query)
Apache Airflow DAG
      ↓ (Python / Pandas)
CSV File 생성
      ↓ (GCS API)
Google Cloud Storage
```

## 기술 스택

| 항목 | 기술 |
|------|------|
| Workflow Engine | Apache Airflow |
| Source Database | MySQL / MariaDB |
| Data Processing | Python, Pandas |
| Storage | Google Cloud Storage |
| Alert | AWS SES Email |

---

## 데이터 추출 전략

테이블 특성에 따라 4가지 추출 전략을 분리하여 적용하였습니다.

| 전략 | 대상 | 설명 |
|------|------|------|
| Full Snapshot | 전체 적재가 필요한 테이블 | 매 실행마다 전체 데이터 추출 |
| Year Snapshot | 연도 기준 필터가 필요한 테이블 | 해당 연도 데이터만 추출 |
| created_at 기반 | 생성일 기준 증분이 가능한 테이블 | 최근 1일 데이터 추출 |
| ID 기반 증분 | PK가 있는 테이블 | Control Table Watermark 패턴으로 마지막 처리 ID 이후 데이터만 추출 |

---

## 주요 구현 내용

### Control Table 기반 Watermark 패턴

ID 기반 증분 추출 시 마지막으로 처리된 ID를 Control Table에 저장하고, 다음 실행 시 이를 기준으로 신규 데이터만 가져옵니다.

```python
def get_last_id(cursor, table_name: str) -> int:
    cursor.execute(
        "SELECT last_id FROM airflow_control WHERE table_name = %s",
        (table_name,),
    )
    row = cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else 0
```

GCS 업로드 완료 후에만 Watermark를 커밋하여 업로드 실패 시 데이터 누락을 방지하였습니다.

---

### DAG Factory 패턴

테이블별 추출 전략과 PK 정보를 딕셔너리로 관리하고, 이를 기반으로 Task를 동적으로 생성합니다.  
테이블 추가 시 딕셔너리에 한 줄만 추가하면 자동으로 Task가 생성됩니다.

```python
ID_TABLE_PK = {
    "product": "product_id",
    "sales_items": "id",
    ...
}

for t in TABLES:
    PythonOperator(
        task_id=f"extract_{t}",
        python_callable=run_one_table,
        op_kwargs={"table": t},
    )
```

---

### 데이터 품질 정제

MariaDB 특유의 bad date 값과 null-like 문자열을 정제하여 다운스트림에서 오류가 발생하지 않도록 처리하였습니다.

```python
NULL_LIKE = {"null", "none", "nan"}
BAD_DATE_LIKE = {"0000-00-00", "0000-00-00 00:00:00", "00000000"}
```

---

### Backfill 지원

`pendulum.now()` 대신 `context["data_interval_start"]`를 사용하여 과거 날짜로 재실행 시에도 올바른 GCS 경로에 데이터가 적재되도록 설계하였습니다.

```python
def make_day_prefix_from_context(context) -> str:
    dt = context["data_interval_start"].in_timezone("Asia/Seoul")
    return f"{GCS_BASE_PREFIX}/{dt.format('YYYY')}/{dt.format('MM')}/{dt.format('DD')}"
```

---

### 운영 안정성

- **retry 설정** : Task 실패 시 2회 자동 재시도 (5분 간격)
- **임시 파일 관리** : GCS 업로드 완료 후 로컬 CSV 즉시 삭제
- **0건 처리** : 데이터가 없는 경우에도 헤더 CSV를 업로드하여 스키마 유지
- **중복 제거** : `SELECT DISTINCT`로 소스 DB 중복 데이터 방지

## 파일 구성

```
airflow-etl/
├── README.md
└── salesdata_mysql_to_gcs.py
```
