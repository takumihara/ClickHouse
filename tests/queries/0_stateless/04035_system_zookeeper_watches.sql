-- Tags: zookeeper, no-replicated-database

-- Schema check: verify all 8 columns exist
SELECT name FROM system.columns WHERE table = 'zookeeper_watches' AND database = 'system' ORDER BY position;

-- Create a ReplicatedMergeTree table to establish ZK watches
DROP TABLE IF EXISTS test_zk_watches_04035;
CREATE TABLE test_zk_watches_04035
(
    key UInt64,
    value String
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/{database}/04035_zk_watches', '1')
ORDER BY key;

INSERT INTO test_zk_watches_04035 VALUES (1, 'a');
SYSTEM SYNC REPLICA test_zk_watches_04035;

-- Verify watches exist for our path
SELECT count(*) > 0 FROM system.zookeeper_watches WHERE path LIKE '%04035_zk_watches%';
SELECT countIf(zookeeper_name != 'default') = 0 FROM system.zookeeper_watches WHERE path LIKE '%04035_zk_watches%';
SELECT countIf(create_time < yesterday() OR create_time > now() + INTERVAL 3 SECOND) = 0 FROM system.zookeeper_watches WHERE path LIKE '%04035_zk_watches%';
SELECT countIf(session_id = 0) = 0 FROM system.zookeeper_watches WHERE path LIKE '%04035_zk_watches%';
SELECT countIf(watch_type = 'Data') > 0 FROM system.zookeeper_watches WHERE path LIKE '%04035_zk_watches%';

-- Drop table and verify watches are cleaned up
DROP TABLE test_zk_watches_04035 SYNC;
SELECT count(*) FROM system.zookeeper_watches WHERE path LIKE '%04035_zk_watches%';
