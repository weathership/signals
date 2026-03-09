# Services

## PostgreSQL 16

Managed by devenv's `services.postgres`, starts automatically with `devenv up`.

- **Database:** `signals` (created automatically)
- **Extensions:** Apache AGE (graph queries), pg_cron (scheduled jobs)
- **shared_preload_libraries:** `age,pg_cron`

```bash
psql -d signals
```

### Apache AGE

Graph query support via the AGE extension:

```sql
SELECT * FROM ag_catalog.cypher('my_graph', $$ MATCH (n) RETURN n $$) AS (n agtype);
```

### pg_cron

Scheduled job support:

```sql
SELECT cron.schedule('nightly-job', '0 3 * * *', 'CALL my_procedure()');
```
