# AWS CloudWatch Logs → ColumnStore ETL 파이프라인

Apache Airflow를 활용하여 AWS CloudWatch Logs에서 로그 데이터를 수집하고, MariaDB ColumnStore(DW)에 적재하는 ETL 파이프라인.

---

## 프로젝트 배경

사내 제품(RV)의 HAProxy Access Log, Tomcat Error Log가 AWS CloudWatch에 적재되고 있었으나, 분석을 위해서는 매번 CloudWatch 콘솔에서 수동으로 쿼리해야 했고 이력 보존도 불가능한 상황이었다.

이를 해결하기 위해 **CloudWatch Logs Insights → CSV → MariaDB ColumnStore** 흐름의 자동화 파이프라인을 설계 및 구현했다.

---

## 아키텍처

```
AWS CloudWatch Logs
  ├── HAProxy Access Log Group
  └── Tomcat Error Log Group
          │
          │  CloudWatch Logs Insights Query (매 시간)
          ▼
   Airflow Server (PythonOperator)
          │
          │  1. start_query       : Insights 쿼리 실행 → query_id 반환
          │  2. process_and_save  : 결과 배치 수집 → CSV 저장
          │  3. insert_columnstore: CSV → pandas 가공 → ColumnStore 적재
          ▼
   MariaDB ColumnStore (DW)
     ├── dw_schema.st_aws_haproxy_log
     └── dw_schema.st_tomcat_error_log
```

---

## DAG 구성

### Task 흐름 (HAProxy / Tomcat 공통)

```
start_query_task >> process_and_save_task >> insert_columnstore_task
```

| Task | 역할 |
|---|---|
| `start_query_task` | CloudWatch Insights 쿼리 실행, `query_id` 반환 |
| `process_and_save_task` | 결과 배치 수집, CSV 저장 |
| `insert_columnstore_task` | CSV 읽기, 타입 정리, ColumnStore 일괄 적재 |

### 스케줄
- `schedule_interval="0 * * * *"` : 매 시간 실행
- `catchup=False` : 과거 누락 실행 방지

---

## 주요 구현 포인트

### 1. XCom을 활용한 Task 간 query_id 전달

CloudWatch Logs Insights는 쿼리 실행과 결과 조회가 비동기로 분리되어 있다. `start_query`에서 반환된 `query_id`를 XCom으로 넘겨 다음 Task에서 결과를 조회하는 구조로 설계했다.

```python
# start_query_task: query_id 반환 (자동으로 XCom push)
def start_query():
    ...
    return query_id

# process_and_save_task: XCom에서 query_id pull
def process_and_save(**kwargs):
    query_id = kwargs["ti"].xcom_pull(task_ids="start_query_task")
```

### 2. 제너레이터 패턴으로 배치 처리

`get_query_results_iter()`를 제너레이터로 구현하여 전체 결과를 메모리에 올리지 않고 `batch_size` 단위로 처리한다.

```python
def get_query_results_iter(query_id, batch_size=50):
    while True:
        result = subprocess.run(get_results_command, ...)
        status = query_results.get("status")

        if status == "Complete":
            results = query_results.get("results", [])
            for i in range(0, len(results), batch_size):
                yield results[i:i + batch_size]
            break
        elif status in ["Failed", "Cancelled"]:
            raise ValueError(...)
```

### 3. HAProxy 로그 파싱 (CloudWatch Insights 쿼리)

HAProxy 로그는 구조화되지 않은 원시 텍스트다. CloudWatch Insights의 `parse` 구문으로 컬럼 17개를 추출하고, 불필요한 큰따옴표는 `replace()`로 정리했다.

```
fields @timestamp, @message
| parse "* * * * *[*]: *=*:* *=*:* *=* *=* *=* ..."
    as month, day, time, localhost, daemon, process,
       data1, client_ip, port1, data2, backend_server_ip, port2, ...
| filter @message not like "SSL handshake failure"
| display @timestamp, daemon, ...,
          replace(user_agent, '"', '') as user_agent_clean, ...
| sort by @timestamp asc
| limit 5000
```

> CloudWatch Insights 쿼리는 인프라 담당자와 협업하여 작성

### 4. Tomcat ERROR 로그 필터링 및 구조화

Tomcat 로그에서 ERROR 레벨만 필터링하고, `trace_id` / `span_id`를 파싱해 분산 추적이 가능한 형태로 적재했다.

```
| filter status like "ERROR"
| filter @message not like "java.lang.NullPointerException: null"
| parse msg_all "* - * * - *" as data1, trace_id, span_id, msg
```

### 5. pandas + executemany 기반 일괄 적재

문자열 컬럼 결측값은 `''`으로, 숫자형 컬럼(`response`, `total_time`, `bytes`)은 `0`으로 채운 뒤 `cursor.executemany()`로 일괄 적재했다. `iterrows()` 대비 성능상 이점이 있다.

```python
for col in ['response', 'total_time', 'bytes']:
    df[col] = df[col].fillna(0).astype(int)

values = list(df[[...]].itertuples(index=False, name=None))
cursor.executemany(insert_query, values)
```

---

## 적재 테이블

### `dw_schema.st_aws_haproxy_log`

| 컬럼 | 설명 |
|---|---|
| `created_dt` | 로그 발생 시각 (`@timestamp`) |
| `client_ip` | 클라이언트 IP |
| `backend_server_ip` | 백엔드 서버 IP |
| `response_status` | HAProxy 응답 상태 |
| `path` | 요청 경로 |
| `http_status` | HTTP 상태 코드 |
| `response` / `total_time` / `bytes` | 응답 시간 및 크기 |
| `user_agent_clean` | User-Agent (따옴표 제거) |

### `dw_schema.st_tomcat_error_log`

| 컬럼 | 설명 |
|---|---|
| `created_dt` | 로그 발생 시각 |
| `http` | HTTP 메서드/경로 |
| `trace_id` / `span_id` | 분산 추적 ID |
| `msg` | 에러 메시지 본문 |

---

## 기술 스택

| 항목 | 사용 기술 |
|---|---|
| 워크플로우 | Apache Airflow 2.x |
| 로그 수집 | AWS CloudWatch Logs Insights |
| AWS 연동 | boto3, AWS CLI (`subprocess`) |
| 데이터 가공 | pandas |
| 적재 대상 | MariaDB ColumnStore (DW) |
| Airflow Hook | `MySqlHook` (apache-airflow-providers-mysql) |

---

## 개선 가능한 부분

- CSV 중간 저장 제거 → CloudWatch 결과를 메모리에서 직접 ColumnStore로 적재
- Watermark 패턴 적용 → 중복 적재 방지 (현재는 매 시간 전량 재적재)
- DAG `execution_date` 기반으로 쿼리 시간 범위 동적 계산
