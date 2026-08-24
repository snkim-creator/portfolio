-- 테이블별 I/O 상위 (performance_schema.table_io_waits_summary_by_table).
-- Timer 단위는 picosecond. 시스템 스키마는 제외하고 상위 N개만.
SELECT
    OBJECT_SCHEMA,
    OBJECT_NAME,
    COUNT_READ,
    COUNT_WRITE,
    SUM_TIMER_READ,
    SUM_TIMER_WRITE
FROM performance_schema.table_io_waits_summary_by_table
WHERE OBJECT_SCHEMA NOT IN ('mysql', 'performance_schema', 'information_schema', 'sys')
  AND OBJECT_NAME IS NOT NULL
ORDER BY (SUM_TIMER_READ + SUM_TIMER_WRITE) DESC
LIMIT %(limit)s;
