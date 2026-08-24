-- 실행 중 트랜잭션 요약 (information_schema.innodb_trx). PROCESS 권한 필요.
-- 한 행 반환: 전체/실행중/락대기 트랜잭션 수 + 최장 실행시간(초).
SELECT
    COUNT(*)                                                    AS trx_count,
    COALESCE(SUM(trx_state = 'RUNNING'), 0)                     AS trx_running,
    COALESCE(SUM(trx_state = 'LOCK WAIT'), 0)                   AS trx_lock_waiting,
    COALESCE(MAX(TIMESTAMPDIFF(SECOND, trx_started, NOW())), 0) AS longest_trx_seconds
FROM information_schema.innodb_trx;
