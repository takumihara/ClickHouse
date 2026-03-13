#!/usr/bin/env python3
import math
import os
import re
import time
import pytest

import helpers.keeper_utils as keeper_utils
from helpers.cluster import CLICKHOUSE_CI_MIN_TESTED_VERSION, ClickHouseCluster

# ── Small-chunk cluster: local disk ──────────────────────────────────────────
# node1 has the highest leader priority so it will be the leader.
cluster_local = ClickHouseCluster(__file__)

node1 = cluster_local.add_instance(
    "node1",
    main_configs=["configs/enable_keeper1.xml"],
    stay_alive=True,
    with_remote_database_disk=False,
)
node2 = cluster_local.add_instance(
    "node2",
    main_configs=["configs/enable_keeper2.xml"],
    stay_alive=True,
    with_remote_database_disk=False,
)
node3 = cluster_local.add_instance(
    "node3",
    main_configs=["configs/enable_keeper3.xml"],
    stay_alive=True,
    with_remote_database_disk=False,
)

# ── Small-chunk cluster: S3 (non-local) disk ─────────────────────────────────
# Same topology and chunk size as cluster_local, but snapshots are stored on
# MinIO.  This exercises the non-local-disk code path in read/save_logical_snp_obj.
cluster_s3 = ClickHouseCluster(__file__)

node7 = cluster_s3.add_instance(
    "node7",
    main_configs=["configs/enable_keeper7_s3.xml"],
    stay_alive=True,
    with_minio=True,
    with_remote_database_disk=False,
)
node8 = cluster_s3.add_instance(
    "node8",
    main_configs=["configs/enable_keeper8_s3.xml"],
    stay_alive=True,
    with_minio=True,
    with_remote_database_disk=False,
)
node9 = cluster_s3.add_instance(
    "node9",
    main_configs=["configs/enable_keeper9_s3.xml"],
    stay_alive=True,
    with_minio=True,
    with_remote_database_disk=False,
)

# ── Large-chunk cluster: local disk ──────────────────────────────────────────
# Configured with a large chunk size (100 MB) so that even a multi-hundred-KB
# snapshot is sent as a single NuRaft object, exercising the chunk_size >
# file_size code path (is_first_obj=is_last_obj=true on the leader side).
cluster_large_chunk = ClickHouseCluster(__file__)

node4 = cluster_large_chunk.add_instance(
    "node4",
    main_configs=["configs/enable_keeper4_large_chunk.xml"],
    stay_alive=True,
    with_remote_database_disk=False,
)
node5 = cluster_large_chunk.add_instance(
    "node5",
    main_configs=["configs/enable_keeper5_large_chunk.xml"],
    stay_alive=True,
    with_remote_database_disk=False,
)
node6 = cluster_large_chunk.add_instance(
    "node6",
    main_configs=["configs/enable_keeper6_large_chunk.xml"],
    stay_alive=True,
    with_remote_database_disk=False,
)

# ── Compatibility cluster: old leader, new follower ───────────────────────────
# compat1 and compat2 run the oldest supported ClickHouse version and act as
# leader/active-follower.  Old versions have no snapshot_transfer_chunk_size
# setting and always send the whole snapshot as a single NuRaft object
# (is_first_obj=is_last_obj=true).  compat3 runs the current (new) version and
# is the lagging node that must recover via snapshot transfer.  This verifies
# that the new save_logical_snp_obj correctly handles the single-chunk path
# produced by an old leader.
cluster_compat = ClickHouseCluster(__file__)

compat1 = cluster_compat.add_instance(
    "compat1",
    main_configs=["configs/enable_keeper_compat1.xml"],
    stay_alive=True,
    image="clickhouse/clickhouse-server",
    tag=CLICKHOUSE_CI_MIN_TESTED_VERSION,
    with_installed_binary=True,
    with_remote_database_disk=False,
)
compat2 = cluster_compat.add_instance(
    "compat2",
    main_configs=["configs/enable_keeper_compat2.xml"],
    stay_alive=True,
    image="clickhouse/clickhouse-server",
    tag=CLICKHOUSE_CI_MIN_TESTED_VERSION,
    with_installed_binary=True,
    with_remote_database_disk=False,
)
compat3 = cluster_compat.add_instance(
    "compat3",
    main_configs=["configs/enable_keeper_compat3.xml"],
    stay_alive=True,
    with_remote_database_disk=False,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(
    scope="module",
    params=["local", "s3"],
    ids=["local_disk", "s3_disk"],
)
def chunked_transfer_nodes(request):
    """
    Parametrized fixture that yields a dict of cluster nodes for the two tests
    that exercise chunked snapshot transfer.  The same test logic runs against
    both a local-disk cluster and an S3-backed cluster, ensuring the non-local
    code path in read/save_logical_snp_obj is covered.
    """
    if request.param == "local":
        try:
            cluster_local.start()
            yield {
                "cluster": cluster_local,
                "leader": node1,
                "middle": node2,
                "lagging": node3,
            }
        finally:
            cluster_local.shutdown()
    else:
        try:
            cluster_s3.start()
            cluster_s3.minio_client.make_bucket("snapshots")
            yield {
                "cluster": cluster_s3,
                "leader": node7,
                "middle": node8,
                "lagging": node9,
            }
        finally:
            cluster_s3.shutdown()


@pytest.fixture(scope="module")
def started_cluster_large_chunk():
    try:
        cluster_large_chunk.start()
        yield cluster_large_chunk
    finally:
        cluster_large_chunk.shutdown()


@pytest.fixture(scope="module")
def started_cluster_compat():
    try:
        cluster_compat.start()
        yield cluster_compat
    finally:
        cluster_compat.shutdown()


CHUNK_SIZE = 4096  # snapshot_transfer_chunk_size used by the small-chunk clusters


def stop_zk(zk):
    try:
        if zk:
            zk.stop()
            zk.close()
    except:
        pass


def get_new_snapshot_log_lines(node, total_log_lines_before):
    """
    Return log lines containing "Saving snapshot" that were written after
    total_log_lines_before (a total log-file line count recorded before the
    operation under test).  Using a total-line baseline instead of a pattern-
    match count avoids any cross-test contamination: only lines physically
    appended to the log after the baseline are examined.
    """
    output = node.exec_in_container(
        [
            "bash",
            "-c",
            f"tail -n +{total_log_lines_before + 1}"
            " /var/log/clickhouse-server/clickhouse-server.log"
            " | grep 'Saving snapshot' || true",
        ]
    )
    return [line for line in output.splitlines() if line]


def get_latest_snapshot_size(cl, node):
    """
    Return the size in bytes of the latest snapshot file visible to this node.
    For local-disk clusters the file is on the container filesystem; for S3
    clusters it is an object in the MinIO "snapshots" bucket.
    """
    if cl is cluster_s3:
        objects = sorted(
            cl.minio_client.list_objects("snapshots", recursive=True),
            key=lambda o: o.last_modified,
        )
        assert objects, "No snapshot objects found in the MinIO 'snapshots' bucket"
        return objects[-1].size
    else:
        result = node.exec_in_container(
            [
                "bash",
                "-c",
                "find /var/lib/clickhouse/coordination/snapshots/ -name '*.bin'"
                " -printf '%T@ %s\\n' | sort -n | tail -1 | awk '{print $2}'",
            ]
        ).strip()
        assert result, "No snapshot files found under coordination/snapshots/"
        return int(result)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_recover_from_snapshot_with_chunked_transfer(chunked_transfer_nodes):
    """
    node_lagging is stopped while node_leader/node_middle accumulate enough writes
    to trigger several snapshots.  When node_lagging restarts it is too stale to
    replay logs so the leader must send it a snapshot.  With
    snapshot_transfer_chunk_size=4096 the ~300 KB snapshot is split into multiple
    4 KB chunks.  We verify:
      1. Data on node_lagging matches the rest of the cluster after recovery.
      2. The snapshot was transferred in exactly ceil(snapshot_size / CHUNK_SIZE)
         chunks: we parse all "Saving snapshot … obj_id N" lines written during
         this recovery (anchored to a total-log-line baseline) and check that the
         set of obj_ids is exactly {0, 1, …, expected_chunks-1}.

    The test runs for both local-disk and S3-backed clusters (parametrized).
    """
    cl = chunked_transfer_nodes["cluster"]
    node_leader = chunked_transfer_nodes["leader"]
    node_middle = chunked_transfer_nodes["middle"]
    node_lagging = chunked_transfer_nodes["lagging"]

    leader_zk = middle_zk = lagging_zk = None
    prefix = "/test_chunked_snapshot_transfer"

    try:
        leader_zk = keeper_utils.get_fake_zk(cl, node_leader.name)
        middle_zk = keeper_utils.get_fake_zk(cl, node_middle.name)
        lagging_zk = keeper_utils.get_fake_zk(cl, node_lagging.name)

        leader_zk.create(prefix, b"somedata")

        middle_zk.sync(prefix)
        lagging_zk.sync(prefix)

        assert leader_zk.get(prefix)[0] == b"somedata"
        assert middle_zk.get(prefix)[0] == b"somedata"
        assert lagging_zk.get(prefix)[0] == b"somedata"

        # Isolate node_lagging so it falls behind.
        node_lagging.stop_clickhouse(kill=True)

        # Write enough data to exceed stale_log_gap=10 and create multiple
        # snapshots (snapshot_distance=50).  Use unique random bytes so ZSTD
        # compression doesn't shrink the snapshot below the chunk size.
        for i in range(300):
            leader_zk.create(prefix + str(i), os.urandom(1024))

        for i in range(300):
            if i % 10 == 0:
                leader_zk.delete(prefix + str(i))

    finally:
        for zk in [leader_zk, middle_zk, lagging_zk]:
            stop_zk(zk)

    # Record the total log-file line count before recovery so the chunk-count
    # assertion below is anchored to lines physically appended during this
    # recovery and not contaminated by any previous test runs on the same node.
    total_log_lines_before = node_lagging.count_log_lines()

    # node_lagging is stale: it must recover via snapshot transfer (not log replay).
    node_lagging.start_clickhouse(20)
    keeper_utils.wait_until_connected(cl, node_lagging)

    try:
        leader_zk = keeper_utils.get_fake_zk(cl, node_leader.name)
        middle_zk = keeper_utils.get_fake_zk(cl, node_middle.name)
        lagging_zk = keeper_utils.get_fake_zk(cl, node_lagging.name)

        leader_zk.sync(prefix)
        middle_zk.sync(prefix)
        lagging_zk.sync(prefix)

        assert leader_zk.get(prefix)[0] == b"somedata"
        assert middle_zk.get(prefix)[0] == b"somedata"
        assert lagging_zk.get(prefix)[0] == b"somedata"

        for i in range(300):
            if i % 10 != 0:
                value_on_leader = leader_zk.get(prefix + str(i))[0]
                assert middle_zk.get(prefix + str(i))[0] == value_on_leader
                assert lagging_zk.get(prefix + str(i))[0] == value_on_leader
            else:
                assert leader_zk.exists(prefix + str(i)) is None
                assert middle_zk.exists(prefix + str(i)) is None
                assert lagging_zk.exists(prefix + str(i)) is None

    finally:
        try:
            leader_zk = keeper_utils.get_fake_zk(cl, node_leader.name)
            for i in range(300):
                if leader_zk.exists(prefix + str(i)):
                    leader_zk.delete(prefix + str(i))
            if leader_zk.exists(prefix):
                leader_zk.delete(prefix)
        except:
            pass

        for zk in [leader_zk, middle_zk, lagging_zk]:
            stop_zk(zk)

    # Verify the exact number of chunks transferred.  The follower logs
    # "Saving snapshot <idx> obj_id <n>" for every received chunk; we collect
    # all obj_ids from lines added after the baseline and assert they form the
    # contiguous range [0, expected_chunks).
    snapshot_lines = get_new_snapshot_log_lines(node_lagging, total_log_lines_before)
    snapshot_size = get_latest_snapshot_size(cl, node_lagging)
    expected_chunks = math.ceil(snapshot_size / CHUNK_SIZE)
    obj_ids = sorted(
        int(m.group(1))
        for line in snapshot_lines
        if (m := re.search(r"obj_id (\d+)", line))
    )
    assert obj_ids == list(range(expected_chunks)), (
        f"Expected obj_ids 0..{expected_chunks - 1} ({expected_chunks} chunks for "
        f"{snapshot_size}-byte snapshot / {CHUNK_SIZE}-byte chunks), got: {obj_ids}"
    )


def test_recover_after_interrupted_transfer(chunked_transfer_nodes):
    """
    Verify that a partial temp file left by a mid-transfer crash does not prevent
    the next recovery from succeeding.

    node_lagging is stopped while the leader accumulates enough data to trigger a
    snapshot.  node_lagging is then started and killed while it is provably
    mid-transfer: the `keeper_save_snapshot_pause_mid_transfer` PAUSEABLE_ONCE failpoint causes
    save_logical_snp_obj to block after writing a non-last chunk; SYSTEM WAIT
    FAILPOINT confirms the pause before we kill the process.  The second full
    recovery (failpoint disabled on restart) must produce correct data.

    The test runs for both local-disk and S3-backed clusters (parametrized).
    """
    cl = chunked_transfer_nodes["cluster"]
    node_leader = chunked_transfer_nodes["leader"]
    node_lagging = chunked_transfer_nodes["lagging"]

    prefix = "/test_interrupted_chunked_transfer"
    leader_zk = lagging_zk = None

    try:
        leader_zk = keeper_utils.get_fake_zk(cl, node_leader.name)

        # node_lagging may still be running from the previous test; kill it.
        node_lagging.stop_clickhouse(kill=True)

        leader_zk.ensure_path(prefix)
        for i in range(300):
            leader_zk.create(prefix + "/" + str(i), os.urandom(1024))
        for i in range(300):
            if i % 10 == 0:
                leader_zk.delete(prefix + "/" + str(i))
    finally:
        stop_zk(leader_zk)

    # First start: pause node_lagging mid-transfer via failpoint, then kill it.
    # Enabling the failpoint right after startup is safe: NuRaft needs several
    # seconds to connect, detect staleness, and receive the first snapshot chunk —
    # well after the single ENABLE query completes.
    node_lagging.start_clickhouse(20)
    node_lagging.query("SYSTEM ENABLE FAILPOINT keeper_save_snapshot_pause_mid_transfer")
    # Block until a NuRaft thread is suspended inside save_logical_snp_obj,
    # guaranteeing node_lagging is killed while the transfer is in progress.
    node_lagging.query("SYSTEM WAIT FAILPOINT keeper_save_snapshot_pause_mid_transfer PAUSE")
    node_lagging.stop_clickhouse(kill=True)

    # Second start: let node_lagging recover fully from whatever partial state
    # was left by the mid-transfer kill.
    node_lagging.start_clickhouse(20)
    keeper_utils.wait_until_connected(cl, node_lagging)

    try:
        leader_zk = keeper_utils.get_fake_zk(cl, node_leader.name)
        lagging_zk = keeper_utils.get_fake_zk(cl, node_lagging.name)

        leader_zk.sync(prefix)
        lagging_zk.sync(prefix)

        for i in range(300):
            if i % 10 != 0:
                assert lagging_zk.get(prefix + "/" + str(i))[0] == leader_zk.get(prefix + "/" + str(i))[0]
            else:
                assert lagging_zk.exists(prefix + "/" + str(i)) is None

    finally:
        try:
            leader_zk = keeper_utils.get_fake_zk(cl, node_leader.name)
            for i in range(300):
                if leader_zk.exists(prefix + "/" + str(i)):
                    leader_zk.delete(prefix + "/" + str(i))
            if leader_zk.exists(prefix):
                leader_zk.delete(prefix)
        except:
            pass

        for zk in [leader_zk, lagging_zk]:
            stop_zk(zk)


def test_recover_with_chunk_size_larger_than_snapshot(started_cluster_large_chunk):
    """
    Verify recovery when snapshot_transfer_chunk_size exceeds the snapshot file size.

    With chunk_size=104857600 (100 MB) the ~300 KB test snapshot is smaller than one
    chunk, so the leader sets is_first_obj=is_last_obj=true and sends a single NuRaft
    object.  This exercises the same single-object code path that was used before
    chunked transfer was introduced, and ensures no regression for that case.

    We verify:
      1. Data on node6 matches node4 after recovery.
      2. Only obj_id 0 appears in node6's log during this recovery (single-chunk
         transfer), anchored to lines added during this run.
    """
    prefix = "/test_large_chunk_transfer"
    node4_zk = node6_zk = None

    node6.stop_clickhouse(kill=True)

    # Total-line baseline before recovery so the assertion below sees only lines
    # appended during this run and is not contaminated by previous tests.
    total_log_lines_before = node6.count_log_lines()

    try:
        node4_zk = keeper_utils.get_fake_zk(cluster_large_chunk, "node4")

        node4_zk.ensure_path(prefix)
        for i in range(300):
            node4_zk.create(prefix + "/" + str(i), os.urandom(1024))
        for i in range(300):
            if i % 10 == 0:
                node4_zk.delete(prefix + "/" + str(i))
    finally:
        stop_zk(node4_zk)

    node6.start_clickhouse(20)
    keeper_utils.wait_until_connected(cluster_large_chunk, node6)

    try:
        node4_zk = keeper_utils.get_fake_zk(cluster_large_chunk, "node4")
        node6_zk = keeper_utils.get_fake_zk(cluster_large_chunk, "node6")

        node4_zk.sync(prefix)
        node6_zk.sync(prefix)

        for i in range(300):
            if i % 10 != 0:
                assert node6_zk.get(prefix + "/" + str(i))[0] == node4_zk.get(prefix + "/" + str(i))[0]
            else:
                assert node6_zk.exists(prefix + "/" + str(i)) is None

    finally:
        try:
            node4_zk = keeper_utils.get_fake_zk(cluster_large_chunk, "node4")
            for i in range(300):
                if node4_zk.exists(prefix + "/" + str(i)):
                    node4_zk.delete(prefix + "/" + str(i))
            if node4_zk.exists(prefix):
                node4_zk.delete(prefix)
        except:
            pass

        for zk in [node4_zk, node6_zk]:
            stop_zk(zk)

    # With a 100 MB chunk size the snapshot fits in a single object, so the
    # leader calls read_logical_snp_obj exactly once (obj_id=0, is_last=true),
    # and the follower's save_logical_snp_obj takes the is_first&&is_last branch.
    snapshot_lines = get_new_snapshot_log_lines(node6, total_log_lines_before)
    assert snapshot_lines, "No 'Saving snapshot' log lines appeared during recovery"
    obj_ids = sorted(
        int(m.group(1))
        for line in snapshot_lines
        if (m := re.search(r"obj_id (\d+)", line))
    )
    assert obj_ids == [0], (
        "Expected snapshot to be transferred as a single chunk (obj_id list must be [0]). "
        f"Got: {obj_ids}"
    )


def test_recover_from_snapshot_sent_by_old_leader(started_cluster_compat):
    """
    Backward-compatibility test: a new follower (current version) must be able
    to recover from a snapshot sent by an old leader (CLICKHOUSE_CI_MIN_TESTED_VERSION).

    Old versions have no snapshot_transfer_chunk_size setting and always send the
    whole snapshot in a single NuRaft object (is_first_obj=is_last_obj=true).
    The new save_logical_snp_obj must handle that path correctly.

    We verify:
      1. compat3 (new version) recovers with correct data after the old cluster
         compat1/compat2 accumulates a snapshot it cannot replay from logs.
      2. Only obj_id 0 appears in compat3's new log lines, confirming the old
         leader sent a single-chunk snapshot (no chunking in old version).
    """
    prefix = "/test_compat_snapshot_transfer"
    leader_zk = lagging_zk = None

    compat3.stop_clickhouse(kill=True)

    total_log_lines_before = compat3.count_log_lines()

    try:
        leader_zk = keeper_utils.get_fake_zk(cluster_compat, "compat1")

        leader_zk.ensure_path(prefix)
        for i in range(300):
            leader_zk.create(prefix + "/" + str(i), os.urandom(1024))
        for i in range(300):
            if i % 10 == 0:
                leader_zk.delete(prefix + "/" + str(i))
    finally:
        stop_zk(leader_zk)

    compat3.start_clickhouse(20)
    keeper_utils.wait_until_connected(cluster_compat, compat3)

    try:
        leader_zk = keeper_utils.get_fake_zk(cluster_compat, "compat1")
        lagging_zk = keeper_utils.get_fake_zk(cluster_compat, "compat3")

        leader_zk.sync(prefix)
        lagging_zk.sync(prefix)

        for i in range(300):
            if i % 10 != 0:
                assert lagging_zk.get(prefix + "/" + str(i))[0] == leader_zk.get(prefix + "/" + str(i))[0]
            else:
                assert lagging_zk.exists(prefix + "/" + str(i)) is None

    finally:
        try:
            leader_zk = keeper_utils.get_fake_zk(cluster_compat, "compat1")
            for i in range(300):
                if leader_zk.exists(prefix + "/" + str(i)):
                    leader_zk.delete(prefix + "/" + str(i))
            if leader_zk.exists(prefix):
                leader_zk.delete(prefix)
        except:
            pass

        for zk in [leader_zk, lagging_zk]:
            stop_zk(zk)

    # The old leader has no chunking: it always sends is_first_obj=is_last_obj=true,
    # so the new follower must have taken the is_first&&is_last branch.
    # Confirm exactly one obj_id (0) was logged during this recovery.
    snapshot_lines = get_new_snapshot_log_lines(compat3, total_log_lines_before)
    assert snapshot_lines, "No 'Saving snapshot' log lines appeared during compat3 recovery"
    obj_ids = sorted(
        int(m.group(1))
        for line in snapshot_lines
        if (m := re.search(r"obj_id (\d+)", line))
    )
    assert obj_ids == [0], (
        "Old leader must send a single-chunk snapshot; obj_id list must be [0]. "
        f"Got: {obj_ids}"
    )
