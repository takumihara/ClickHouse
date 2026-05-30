-- Tags: no-async-insert, no-parallel
-- Verify per-state ProfileEvents are emitted for GROUP BY, DISTINCT, ORDER BY, IN, and JOIN.
-- See issue ClickHouse/ClickHouse#43235.

DROP TABLE IF EXISTS t_main_04500;
DROP TABLE IF EXISTS t_join_04500;

CREATE TABLE t_main_04500 (a UInt32, b UInt32) ENGINE = Memory;
CREATE TABLE t_join_04500 (a UInt32, c UInt32) ENGINE = Memory;

INSERT INTO t_main_04500 SELECT number % 10, number FROM numbers(1000);
INSERT INTO t_join_04500 SELECT number, number * 10 FROM numbers(200);

-- Pin to single-threaded execution so per-thread state counts are deterministic.
SET max_threads = 1;

-- GROUP BY produces 10 group keys; AggregatorStateRows should equal 10.
SELECT a, count() FROM /* 04500 group_by */ t_main_04500 GROUP BY a FORMAT Null;
SYSTEM FLUSH LOGS query_log;
SELECT
    ProfileEvents['AggregatorStateRows'] AS group_by_rows,
    ProfileEvents['AggregatorStateBytes'] > 0 AS group_by_bytes_positive
FROM system.query_log
WHERE current_database = currentDatabase()
  AND query LIKE '%/* 04500 group_by */%'
  AND type = 'QueryFinish'
  AND event_date >= yesterday()
ORDER BY event_time DESC
LIMIT 1;

-- DISTINCT produces 10 unique rows.
SELECT DISTINCT a FROM /* 04500 distinct */ t_main_04500 FORMAT Null;
SYSTEM FLUSH LOGS query_log;
SELECT
    ProfileEvents['DistinctStateRows'] AS distinct_rows,
    ProfileEvents['DistinctStateBytes'] > 0 AS distinct_bytes_positive
FROM system.query_log
WHERE current_database = currentDatabase()
  AND query LIKE '%/* 04500 distinct */%'
  AND type = 'QueryFinish'
  AND event_date >= yesterday()
ORDER BY event_time DESC
LIMIT 1;

-- ORDER BY sorts 1000 rows; OrderByStateRows is positive (in-memory rows merged).
SELECT a, b FROM /* 04500 order_by */ t_main_04500 ORDER BY b FORMAT Null;
SYSTEM FLUSH LOGS query_log;
SELECT
    ProfileEvents['OrderByStateRows'] > 0 AS order_by_rows_positive,
    ProfileEvents['OrderByStateBytes'] > 0 AS order_by_bytes_positive
FROM system.query_log
WHERE current_database = currentDatabase()
  AND query LIKE '%/* 04500 order_by */%'
  AND type = 'QueryFinish'
  AND event_date >= yesterday()
ORDER BY event_time DESC
LIMIT 1;

-- IN materialises a Set of 200 rows.
SELECT count() FROM /* 04500 in_set */ t_main_04500 WHERE a IN (SELECT a FROM t_join_04500) FORMAT Null;
SYSTEM FLUSH LOGS query_log;
SELECT
    ProfileEvents['SetStateRows'] AS set_rows,
    ProfileEvents['SetStateBytes'] > 0 AS set_bytes_positive
FROM system.query_log
WHERE current_database = currentDatabase()
  AND query LIKE '%/* 04500 in_set */%'
  AND type = 'QueryFinish'
  AND event_date >= yesterday()
ORDER BY event_time DESC
LIMIT 1;

-- JOIN builds a hash table from t_join_04500 (200 rows).
SELECT count() FROM /* 04500 join */ t_main_04500 JOIN t_join_04500 USING (a) FORMAT Null;
SYSTEM FLUSH LOGS query_log;
SELECT
    ProfileEvents['JoinStateRows'] AS join_rows,
    ProfileEvents['JoinStateBytes'] > 0 AS join_bytes_positive
FROM system.query_log
WHERE current_database = currentDatabase()
  AND query LIKE '%/* 04500 join */%'
  AND type = 'QueryFinish'
  AND event_date >= yesterday()
ORDER BY event_time DESC
LIMIT 1;

-- Two-level aggregation dynamic conversion: trigger by setting low threshold.
SET group_by_two_level_threshold = 100;
SELECT a, count() FROM /* 04500 two_level */ t_main_04500 GROUP BY a, b FORMAT Null;
SYSTEM FLUSH LOGS query_log;
SELECT
    ProfileEvents['AggregationConvertedToTwoLevel'] > 0 AS converted_to_two_level
FROM system.query_log
WHERE current_database = currentDatabase()
  AND query LIKE '%/* 04500 two_level */%'
  AND type = 'QueryFinish'
  AND event_date >= yesterday()
ORDER BY event_time DESC
LIMIT 1;

DROP TABLE t_main_04500;
DROP TABLE t_join_04500;
