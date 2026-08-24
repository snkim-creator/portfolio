# DBInsight Daily Report — Sample

> This file contains synthetic data only. It is not generated from a real production database.

- Database: `sample-db-01`
- DB Version: MySQL 8.0.x
- Analysis Window: 2026-08-23 09:00 ~ 2026-08-24 09:00
- Overall Status: **WARNING**

## 오늘의 주요 변화

1. **SQL Regression 감지**
   - Digest: `sample_digest_a1`
   - 7d Median Avg Latency: `1.8 ms`
   - Current Avg Latency: `8.1 ms`
   - Change: `+350%`

2. **Threads_running 증가**
   - Current: `14`
   - 7d Median: `4`
   - 7d P95: `9`

3. **Row Lock Wait 신규 발생**
   - Previous Window: `0`
   - Current Window: `5`

## 오늘 DBA 확인 권장

### Priority 1 — SQL 실행계획 확인

```sql
SELECT order_id, customer_id, created_at
FROM sample_orders
WHERE customer_id = ?
  AND created_at >= ?;
```

- Avg Latency가 7일 기준선 대비 증가
- Rows Examined / Execution도 함께 증가
- `EXPLAIN ANALYZE`, 인덱스 사용 여부, 최근 데이터 분포 변화를 확인

### Priority 2 — Lock 발생 구간 확인

- 최근 분석 기간에 Row Lock Wait 5회 발생
- 장기 트랜잭션 및 동시 UPDATE 패턴 확인

## 정상 범위

- Buffer Pool Hit Ratio: 정상
- Dirty Page Ratio: 정상
- Replication Lag: 정상
