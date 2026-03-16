-- https://github.com/ClickHouse/ClickHouse/issues/99308
-- CREATE VIEW with WITH expression alias used in IN() failed because
-- AddDefaultDatabaseVisitor converted the alias to a table identifier.

DROP TABLE IF EXISTS test_view_cte_in;
DROP VIEW IF EXISTS test_view_cte_in_v;

CREATE TABLE test_view_cte_in (title String) ENGINE = MergeTree() ORDER BY title;
INSERT INTO test_view_cte_in VALUES ('a'), ('b'), ('c');

CREATE VIEW test_view_cte_in_v AS (
    WITH tuple('a', 'b') AS targets
    SELECT count() AS cnt FROM test_view_cte_in WHERE title IN targets
);
SELECT * FROM test_view_cte_in_v;

DROP VIEW test_view_cte_in_v;
DROP TABLE test_view_cte_in;
