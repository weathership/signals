-- signals-360 catalog registry
-- Replaces HMS as the "table of contents" for Kudu and Iceberg tables.
-- Iceberg metadata lives in Polaris; Kudu metadata lives in Kudu master.
-- This schema only stores the mapping: (database, table_name) -> (type, properties).

CREATE TABLE IF NOT EXISTS catalog_databases (
    name TEXT PRIMARY KEY,
    description TEXT,
    location TEXT,
    owner TEXT,
    parameters JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS catalog_tables (
    db_name TEXT NOT NULL REFERENCES catalog_databases(name),
    table_name TEXT NOT NULL,
    table_type TEXT NOT NULL CHECK (table_type IN ('KUDU', 'ICEBERG', 'VIEW')),
    parameters JSONB DEFAULT '{}'::jsonb,
    PRIMARY KEY (db_name, table_name)
);

INSERT INTO catalog_databases VALUES ('default', 'Default database', 's3a://signals-dataproducts/iceberg', NULL, '{}')
ON CONFLICT (name) DO UPDATE SET location = EXCLUDED.location;
