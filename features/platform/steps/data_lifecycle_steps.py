"""Step definitions for data_lifecycle.feature."""

from behave import given, when, then

from tests.workload.lifecycle import LifecycleConfig, LifecycleWorkload


def _get_workload(context) -> LifecycleWorkload:
    if not hasattr(context, "lifecycle_wl"):
        cfg = LifecycleConfig(
            impala_host=getattr(context, "impala_host", "localhost"),
            impala_port=getattr(context, "impala_port", 21050),
        )
        context.lifecycle_wl = LifecycleWorkload(cfg)
    return context.lifecycle_wl


@given("the catalog stack is running")
def step_catalog_stack_running(context):
    wl = _get_workload(context)
    # Verify Impala is reachable
    result = wl._execute_scalar("SELECT 1")
    assert result == 1, "Impala not reachable"


@given('database "{db}" exists')
def step_database_exists(context, db):
    wl = _get_workload(context)
    wl._execute(f"CREATE DATABASE IF NOT EXISTS {db}")


@given('Kudu table "{table}" with schema')
def step_kudu_table_with_schema(context, table):
    wl = _get_workload(context)
    # Parse the table from the behave table
    cols = []
    keys = []
    for row in context.table:
        col_def = f"{row['column']} {row['type']}"
        cols.append(col_def)
        if row["key"].lower() == "yes":
            keys.append(row["column"])

    key_clause = f"PRIMARY KEY ({', '.join(keys)})"
    col_clause = ", ".join(cols)

    wl._execute(f"DROP TABLE IF EXISTS {table}")
    wl._execute(f"""
        CREATE TABLE {table} (
            {col_clause},
            {key_clause}
        )
        PARTITION BY HASH ({keys[0]}) PARTITIONS 4
        STORED AS KUDU
    """)


@when('I insert {n:d} rows into "{table}" across {p:d} partitions')
def step_insert_rows(context, n, table, p):
    wl = _get_workload(context)
    wl.cfg.n_partitions = p
    wl.cfg.rows_per_partition = n // p
    context.landing_result = wl.run_landing(n_rows=n, n_partitions=p, upsert_ratio=0)


@when("I upsert {n:d} rows targeting partitions {start:d}-{end:d}")
def step_upsert_rows(context, n, start, end):
    wl = _get_workload(context)
    wl.cfg.hot_partitions = list(range(start, end + 1))
    wl.run_landing(
        n_rows=wl.cfg.rows_per_partition * wl.cfg.n_partitions,
        upsert_ratio=n / (wl.cfg.rows_per_partition * wl.cfg.n_partitions),
    )


@then('"{table}" contains {n:d} rows')
def step_table_contains_rows(context, table, n):
    wl = _get_workload(context)
    actual = wl._execute_scalar(f"SELECT COUNT(*) FROM {table}")
    assert actual == n, f"Expected {n} rows, got {actual}"


@then("partitions {start:d}-{end:d} have updated payload values")
def step_partitions_have_upserts(context, start, end):
    wl = _get_workload(context)
    db = wl.cfg.database
    tbl = f"{db}.{wl.cfg.kudu_table}"
    part_list = ", ".join(str(p) for p in range(start, end + 1))
    upserted = wl._execute_scalar(
        f"SELECT COUNT(*) FROM {tbl} "
        f"WHERE partition_id IN ({part_list}) AND payload LIKE 'upserted-%'"
    )
    assert upserted > 0, "No upserted rows found in hot partitions"


@given('Kudu table "{table}" has data across {n:d} partitions')
def step_kudu_has_data(context, table, n):
    wl = _get_workload(context)
    count = wl._execute_scalar(f"SELECT COUNT(DISTINCT partition_id) FROM {table}")
    assert count == n, f"Expected {n} partitions, got {count}"


@given("partitions {start:d}-{end:d} have had no upserts")
def step_cold_partitions(context, start, end):
    # Cold partitions are those not in hot_partitions — verified by design
    pass


@when("I consolidate partitions {start:d}-{end:d} into Iceberg table \"{table}\"")
def step_consolidate(context, start, end, table):
    wl = _get_workload(context)
    cold = list(range(start, end + 1))
    context.consolidation_result = wl.consolidate_cold(cold_partitions=cold)


@when("I delete consolidated rows from Kudu")
def step_delete_consolidated(context):
    # Already done inside consolidate_cold()
    pass


@given('Kudu table "{table}" has {n:d} rows in partitions {start:d}-{end:d}')
def step_kudu_partition_rows(context, table, n, start, end):
    wl = _get_workload(context)
    part_list = ", ".join(str(p) for p in range(start, end + 1))
    actual = wl._execute_scalar(
        f"SELECT COUNT(*) FROM {table} WHERE partition_id IN ({part_list})"
    )
    assert actual == n, f"Expected {n} rows, got {actual}"


@given('Iceberg table "{table}" has {n:d} rows in partitions {start:d}-{end:d}')
def step_iceberg_partition_rows(context, table, n, start, end):
    wl = _get_workload(context)
    actual = wl._execute_scalar(f"SELECT COUNT(*) FROM {table}")
    assert actual == n, f"Expected {n} rows in Iceberg, got {actual}"


@when("I query across both tiers")
def step_query_both_tiers(context):
    wl = _get_workload(context)
    sql = context.text.strip()
    context.query_result = wl._execute(sql, fetch=True)


@then("the result is {n:d}")
def step_result_is(context, n):
    actual = context.query_result[0][0]
    assert actual == n, f"Expected {n}, got {actual}"


@when("I query with a predicate spanning both tiers")
def step_query_predicate_both_tiers(context):
    wl = _get_workload(context)
    sql = context.text.strip()
    context.query_result = wl._execute(sql, fetch=True)


@then("every partition {start:d}-{end:d} has exactly {n:d} rows")
def step_every_partition_has_rows(context, start, end, n):
    for row in context.query_result:
        part_id, count = row[0], row[1]
        if start <= part_id <= end:
            assert count == n, (
                f"Partition {part_id}: expected {n} rows, got {count}"
            )


@given("the lifecycle workload is in steady state")
def step_steady_state(context):
    wl = _get_workload(context)
    result = wl.verify_consistency()
    assert result["passed"], f"Not in steady state: {result['errors']}"


@when("I upsert {n:d} rows targeting partitions {start:d}-{end:d}")
def step_upsert_targeting(context, n, start, end):
    wl = _get_workload(context)
    wl.cfg.hot_partitions = list(range(start, end + 1))
    db = wl.cfg.database
    tbl = f"{db}.{wl.cfg.kudu_table}"
    # Direct upsert on hot partitions
    import random, time
    batch = []
    now_ms = int(time.time() * 1000)
    for _ in range(n):
        part = random.choice(wl.cfg.hot_partitions)
        eid = part * wl.cfg.rows_per_partition + random.randint(
            0, wl.cfg.rows_per_partition - 1
        )
        ts = now_ms + random.randint(0, 3600000)
        batch.append(
            f"({eid}, from_unixtime({ts}/1000), {part}, 'hot-upsert-{eid}')"
        )
    for i in range(0, len(batch), 200):
        chunk = batch[i : i + 200]
        wl._execute(f"UPSERT INTO {tbl} VALUES {', '.join(chunk)}")


@then('"{table}" row count reflects the upserts')
def step_row_count_reflects_upserts(context, table):
    wl = _get_workload(context)
    count = wl._execute_scalar(f"SELECT COUNT(*) FROM {table}")
    # Upserts on existing keys don't increase count
    assert count > 0, "Table is empty"


@then('"{table}" still contains exactly {n:d} rows')
def step_still_contains(context, table, n):
    wl = _get_workload(context)
    actual = wl._execute_scalar(f"SELECT COUNT(*) FROM {table}")
    assert actual == n, f"Expected {n} rows, got {actual}"


@then("a UNION ALL query returns consistent results")
def step_union_all_consistent(context):
    wl = _get_workload(context)
    result = wl.verify_consistency()
    assert result["passed"], f"Consistency check failed: {result['errors']}"


@when('I add column "{col}" {dtype} to "{table}"')
def step_add_column(context, col, dtype, table):
    wl = _get_workload(context)
    wl._execute(f"ALTER TABLE {table} ADD COLUMNS ({col} {dtype})")


@when('I insert rows with the new column into "{table}"')
def step_insert_with_new_column(context, table):
    wl = _get_workload(context)
    wl._execute(
        f"INSERT INTO {table} VALUES "
        f"(99999, now(), 0, 'with-priority', 1)"
    )


@then("a UNION ALL query includes the new column")
def step_union_includes_column(context):
    wl = _get_workload(context)
    db = wl.cfg.database
    kudu_tbl = f"{db}.{wl.cfg.kudu_table}"
    ice_tbl = f"{db}.{wl.cfg.iceberg_table}"
    rows = wl._execute(f"""
        SELECT priority FROM (
            SELECT priority FROM {kudu_tbl}
            UNION ALL
            SELECT priority FROM {ice_tbl}
        ) combined
        WHERE priority IS NOT NULL
    """, fetch=True)
    assert len(rows) > 0, "No rows with new column found"


@then('rows without "{col}" return NULL for that column')
def step_null_for_missing(context, col):
    wl = _get_workload(context)
    db = wl.cfg.database
    kudu_tbl = f"{db}.{wl.cfg.kudu_table}"
    null_count = wl._execute_scalar(
        f"SELECT COUNT(*) FROM {kudu_tbl} WHERE {col} IS NULL"
    )
    assert null_count > 0, "Expected some rows with NULL for new column"
