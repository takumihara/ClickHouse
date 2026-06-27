-- Tags: no-parallel
-- Test for https://github.com/ClickHouse/ClickHouse/issues/86000
-- `CREATE TABLE dst AS source` must inherit the engine from `source` even when extra
-- storage clauses (SETTINGS / TTL / ORDER BY / ...) are present. Previously the engine
-- silently fell back to `default_table_engine` (MergeTree) whenever such a clause was
-- given, which was inconsistent with the no-clause case.

DROP TABLE IF EXISTS src_log;
DROP TABLE IF EXISTS src_rmt;
DROP TABLE IF EXISTS dst;

CREATE TABLE src_log (x UInt64) ENGINE = Log;
CREATE TABLE src_rmt (a DateTime, k UInt64) ENGINE = ReplacingMergeTree ORDER BY a;

SELECT '-- 1. plain AS inherits engine (unchanged behavior) --';
CREATE TABLE dst AS src_rmt;
SELECT engine FROM system.tables WHERE database = currentDatabase() AND name = 'dst';
DROP TABLE dst;

SELECT '-- 2. AS + storage SETTINGS inherits engine and applies the override --';
CREATE TABLE dst AS src_rmt SETTINGS index_granularity = 4096;
SELECT engine FROM system.tables WHERE database = currentDatabase() AND name = 'dst';
SHOW CREATE TABLE dst FORMAT TSVRaw;
DROP TABLE dst;

SELECT '-- 3. AS + session SETTINGS inherits engine --';
CREATE TABLE dst AS src_rmt SETTINGS date_time_output_format = 'iso';
SELECT engine FROM system.tables WHERE database = currentDatabase() AND name = 'dst';
DROP TABLE dst;

SELECT '-- 4. AS + TTL inherits engine and applies the TTL --';
CREATE TABLE dst AS src_rmt TTL a + INTERVAL 1 DAY;
SELECT engine FROM system.tables WHERE database = currentDatabase() AND name = 'dst';
SHOW CREATE TABLE dst FORMAT TSVRaw;
DROP TABLE dst;

SELECT '-- 5. AS a Log table + SETTINGS inherits Log --';
CREATE TABLE dst AS src_log SETTINGS max_compress_block_size = 65536;
SELECT engine FROM system.tables WHERE database = currentDatabase() AND name = 'dst';
DROP TABLE dst;

SELECT '-- 6. AS + explicit ENGINE still overrides the source (no regression) --';
CREATE TABLE dst AS src_rmt ENGINE = MergeTree ORDER BY a SETTINGS index_granularity = 256;
SELECT engine FROM system.tables WHERE database = currentDatabase() AND name = 'dst';
DROP TABLE dst;

SELECT '-- 7. AS + ORDER BY override keeps the inherited engine --';
CREATE TABLE dst AS src_rmt ORDER BY k;
SELECT engine FROM system.tables WHERE database = currentDatabase() AND name = 'dst';
SHOW CREATE TABLE dst FORMAT TSVRaw;
DROP TABLE dst;

DROP TABLE src_log;
DROP TABLE src_rmt;
