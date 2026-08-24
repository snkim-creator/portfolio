-- InnoDB History List Length (미purge undo 길이). (개선요청 §16)
-- information_schema.INNODB_METRICS 의 trx_rseg_history_len (MySQL 5.6+/MariaDB 10.x).
-- 실패 시 Collector 가 SHOW ENGINE INNODB STATUS 파싱으로 폴백한다.
SELECT COUNT AS hll
FROM information_schema.INNODB_METRICS
WHERE NAME = 'trx_rseg_history_len';
