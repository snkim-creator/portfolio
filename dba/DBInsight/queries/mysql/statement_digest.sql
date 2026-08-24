-- Performance Schema SQL Digest 요약.
-- Timer 값 단위는 picosecond. 상위 N개는 Collector 에서 LIMIT 로 제한한다.
SELECT
    SCHEMA_NAME,
    DIGEST,
    DIGEST_TEXT,
    COUNT_STAR,
    SUM_TIMER_WAIT,
    MIN_TIMER_WAIT,
    AVG_TIMER_WAIT,
    MAX_TIMER_WAIT,
    SUM_ROWS_AFFECTED,
    SUM_ROWS_SENT,
    SUM_ROWS_EXAMINED,
    SUM_CREATED_TMP_DISK_TABLES,
    SUM_CREATED_TMP_TABLES,
    SUM_SELECT_SCAN,
    SUM_SELECT_FULL_JOIN,
    SUM_NO_INDEX_USED,
    SUM_NO_GOOD_INDEX_USED,
    FIRST_SEEN,
    LAST_SEEN
FROM performance_schema.events_statements_summary_by_digest
WHERE DIGEST IS NOT NULL
ORDER BY {order_by} DESC
LIMIT %(limit)s;
