# MariaDB 테이블 Fragmentation 분석 및 OPTIMIZE 운영 기준 수립

## 개요

현재 운영 중인 MariaDB 서버의 전체 테이블을 대상으로 `DATA_FREE` 기반 fragmentation 상태를 분석하고,  
실무 관점의 OPTIMIZE 실행 기준을 수립한 프로젝트입니다.

---

## 분석 배경

`OPTIMIZE TABLE`은 InnoDB 기준으로 테이블 재구성에 가깝습니다.  
무분별하게 실행하면 테이블 재작성 부하, 디스크 I/O 증가, 인덱스 재생성 비용이 발생합니다.  
따라서 `free_pct`(비율)만 보고 판단하지 않고, 절대 회수 가능 공간과 테이블 크기를 함께 고려한 기준을 수립하였습니다.

---

## 분석 결과 요약

| 항목 | 값 |
|------|---:|
| 총 테이블 수 | 210 |
| 총 용량(MB) | 32,193 |
| 총 free 공간(MB) | 394 |
| 즉시 OPTIMIZE 권장 | 0 |
| 모니터링 대상 | 4 |
| 보류 (비율만 높음) | 44 |
| 유지 | 162 |

**결론 : 즉시 OPTIMIZE를 실행할 테이블 없음. 모니터링 대상 4개만 추세 관찰.**

---

## 판정 기준

| 판정 | 테이블 크기 | free 공간 | free 비율 |
|------|------------|----------|----------|
| 즉시 OPTIMIZE 권장 | >= 1GB | >= 128MB | >= 10% |
| 검토 대상 | >= 256MB | >= 32MB | >= 10% |
| 모니터링 | >= 40MB | >= 4MB | >= 10% |
| 보류 | 작음 | >= 4MB | >= 20% (절대량 작음) |

> `free_pct`가 높아도 절대 회수 공간이 작으면 실행 효과가 거의 없습니다.  
> 특히 log, session, history 계열 테이블은 삭제/갱신 후 free page가 남는 구조적 특성이 있어 보류 처리하였습니다.

---

## 점검 SQL

### 기본 Fragmentation 점검

```sql
SELECT
    table_schema,
    table_name,
    ROUND((data_length + index_length) / 1024 / 1024, 2) AS total_mb,
    ROUND(data_free / 1024 / 1024, 2) AS free_mb,
    ROUND(data_free / NULLIF(data_length + index_length, 0) * 100, 2) AS free_pct,
    engine
FROM information_schema.tables
WHERE table_schema = 'YOUR_DB'
  AND table_type = 'BASE TABLE'
ORDER BY free_mb DESC, free_pct DESC;
```

### OPTIMIZE 후보 자동 추출

```sql
SELECT
    table_name,
    ROUND((data_length + index_length) / 1024 / 1024, 2) AS total_mb,
    ROUND(data_free / 1024 / 1024, 2) AS free_mb,
    ROUND(data_free / NULLIF(data_length + index_length, 0) * 100, 2) AS free_pct,
    CONCAT('OPTIMIZE TABLE `', table_schema, '`.`', table_name, '`;') AS optimize_sql
FROM information_schema.tables
WHERE table_schema = 'YOUR_DB'
  AND engine = 'InnoDB'
  AND table_type = 'BASE TABLE'
  AND (data_length + index_length) >= 1024 * 1024 * 256
  AND data_free >= 1024 * 1024 * 32
  AND data_free / NULLIF(data_length + index_length, 0) >= 0.10
ORDER BY free_mb DESC, total_mb DESC;
```

### 로그/세션성 테이블 따로 확인

```sql
SELECT
    table_name,
    ROUND((data_length + index_length) / 1024 / 1024, 2) AS total_mb,
    ROUND(data_free / 1024 / 1024, 2) AS free_mb,
    ROUND(data_free / NULLIF(data_length + index_length, 0) * 100, 2) AS free_pct
FROM information_schema.tables
WHERE table_schema = 'YOUR_DB'
  AND (
       table_name LIKE '%log%'
    OR table_name LIKE '%session%'
    OR table_name LIKE '%history%'
    OR table_name LIKE '%\_h'
  )
ORDER BY free_mb DESC, free_pct DESC;
```

---

## 운영 권장안

- 이번 점검 : 일괄 OPTIMIZE 미실행
- 모니터링 대상 4개 테이블만 1개월 후 재측정
- 디스크 사용률 압박이 생길 때만 reclaim 우선순위 상향
