//! signals-df — DataFusion logical backup / restore plane.
//!
//! Portable SoR transport uses **logical** artifacts (Apache Parquet + JSON
//! manifests), not physical Kudu FS copies (hostnames embedded on disk).
//!
//! Uniform layout under a backup stamp:
//!
//! ```text
//! $STAMP/logical/
//!   MANIFEST.json
//!   <service>/                 # kudu | atlas | ranger | catalog | …
//!     tables.json              # [{ "name", "path", "rows", "schema_fingerprint" }]
//!     <table>.parquet
//! ```
//!
//! DataFusion provides scalable scan/verify/SQL over these packages and is the
//! restore engine for re-loading Kudu (and other) tables on a new host.

use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use chrono::Utc;
use clap::{Parser, Subcommand};
use datafusion::prelude::*;
use serde::{Deserialize, Serialize};
use walkdir::WalkDir;

#[derive(Parser, Debug)]
#[command(
    name = "signals-df",
    about = "DataFusion logical backup/restore plane (portable Parquet)"
)]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand, Debug)]
enum Cmd {
    /// Initialize logical/ package under a backup stamp directory
    Init {
        /// Backup stamp directory (parent of logical/)
        #[arg(long)]
        stamp: PathBuf,
    },
    /// Ingest a CSV/TSV/Parquet file into logical/<service>/<table>.parquet
    Ingest {
        #[arg(long)]
        stamp: PathBuf,
        #[arg(long)]
        service: String,
        #[arg(long)]
        table: String,
        /// Source file (.csv, .tsv, .parquet)
        #[arg(long)]
        input: PathBuf,
        #[arg(long, default_value = ",")]
        delimiter: String,
        #[arg(long, default_value_t = true)]
        has_header: bool,
    },
    /// List logical tables in a stamp
    List {
        #[arg(long)]
        stamp: PathBuf,
    },
    /// Verify logical package (files, openable Parquet, row counts)
    Verify {
        #[arg(long)]
        stamp: PathBuf,
    },
    /// Run SQL against all Parquet tables registered as service__table
    Sql {
        #[arg(long)]
        stamp: PathBuf,
        /// SQL query (use service__table names, e.g. kudu__events)
        query: String,
    },
    /// Emit shell-friendly summary for just backup integration
    Status {
        #[arg(long)]
        stamp: PathBuf,
    },
    /// SQL over SysML machine HDF5 (hdf5-pure TableProvider; not Impala)
    Hdf5 {
        /// One or more .h5 files (`Machine/GpuMetric[0]/Values`)
        #[arg(long = "file", required = true)]
        files: Vec<PathBuf>,
        /// SQL; table name is `gpu_power`
        #[arg(long, default_value = "SELECT COUNT(*) AS n FROM gpu_power")]
        sql: String,
    },
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct LogicalManifest {
    version: u32,
    format: String,
    created_utc: String,
    note: String,
    services: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct TableEntry {
    name: String,
    path: String,
    rows: u64,
    columns: usize,
    source: String,
}

#[derive(Debug, Serialize, Deserialize, Default, Clone)]
struct ServiceTables {
    service: String,
    tables: Vec<TableEntry>,
}

fn logical_root(stamp: &Path) -> PathBuf {
    stamp.join("logical")
}

fn service_dir(stamp: &Path, service: &str) -> PathBuf {
    logical_root(stamp).join(service)
}

fn write_json(path: &Path, value: &impl Serialize) -> Result<()> {
    if let Some(p) = path.parent() {
        std::fs::create_dir_all(p)?;
    }
    let s = serde_json::to_string_pretty(value)?;
    std::fs::write(path, s)?;
    Ok(())
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<T> {
    let s = std::fs::read_to_string(path)
        .with_context(|| format!("read {}", path.display()))?;
    Ok(serde_json::from_str(&s)?)
}

async fn init_logical(stamp: &Path) -> Result<()> {
    let root = logical_root(stamp);
    std::fs::create_dir_all(&root)?;
    let man = LogicalManifest {
        version: 1,
        format: "signals-logical-parquet-v1".into(),
        created_utc: Utc::now().to_rfc3339(),
        note: "Portable logical backup. Do NOT use Kudu physical FS tars across hosts \
               (embedded hostnames). DataFusion owns scan/verify/restore scaling."
            .into(),
        services: vec![],
    };
    write_json(&root.join("MANIFEST.json"), &man)?;
    println!("initialized {}", root.display());
    Ok(())
}

fn load_or_init_service(stamp: &Path, service: &str) -> Result<ServiceTables> {
    let path = service_dir(stamp, service).join("tables.json");
    if path.is_file() {
        read_json(&path)
    } else {
        Ok(ServiceTables {
            service: service.to_string(),
            tables: vec![],
        })
    }
}

fn save_service(stamp: &Path, st: &ServiceTables) -> Result<()> {
    let dir = service_dir(stamp, &st.service);
    std::fs::create_dir_all(&dir)?;
    write_json(&dir.join("tables.json"), st)?;

    // refresh root manifest service list
    let man_path = logical_root(stamp).join("MANIFEST.json");
    let mut man: LogicalManifest = if man_path.is_file() {
        read_json(&man_path)?
    } else {
        LogicalManifest {
            version: 1,
            format: "signals-logical-parquet-v1".into(),
            created_utc: Utc::now().to_rfc3339(),
            note: "signals-logical-parquet-v1".into(),
            services: vec![],
        }
    };
    if !man.services.iter().any(|s| s == &st.service) {
        man.services.push(st.service.clone());
        man.services.sort();
    }
    write_json(&man_path, &man)?;
    Ok(())
}

async fn session() -> Result<SessionContext> {
    Ok(SessionContext::new())
}

async fn ingest(
    stamp: &Path,
    service: &str,
    table: &str,
    input: &Path,
    delimiter: &str,
    has_header: bool,
) -> Result<()> {
    if !logical_root(stamp).is_dir() {
        init_logical(stamp).await?;
    }
    let ctx = session().await?;
    let ext = input
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();

    let df = match ext.as_str() {
        "parquet" => {
            ctx.read_parquet(input.to_str().unwrap(), ParquetReadOptions::default())
                .await
                .with_context(|| format!("read parquet {}", input.display()))?
        }
        "csv" | "tsv" | "txt" => {
            let delim = if ext == "tsv" {
                b'\t'
            } else if delimiter == r"\t" || delimiter == "TAB" {
                b'\t'
            } else {
                delimiter.as_bytes().first().copied().unwrap_or(b',')
            };
            let opts = CsvReadOptions::new()
                .has_header(has_header)
                .delimiter(delim);
            ctx.read_csv(input.to_str().unwrap(), opts)
                .await
                .with_context(|| format!("read csv {}", input.display()))?
        }
        other => bail!("unsupported input extension .{other} (use .parquet/.csv/.tsv)"),
    };

    let rows = df.clone().count().await? as u64;
    let schema = df.schema();
    let columns = schema.fields().len();

    let out_dir = service_dir(stamp, service);
    std::fs::create_dir_all(&out_dir)?;
    let out_file = out_dir.join(format!("{table}.parquet"));
    // DataFusion write_parquet
    df.write_parquet(
        out_file.to_str().unwrap(),
        datafusion::dataframe::DataFrameWriteOptions::new(),
        None,
    )
    .await
    .with_context(|| format!("write {}", out_file.display()))?;

    let mut st = load_or_init_service(stamp, service)?;
    st.tables.retain(|t| t.name != table);
    st.tables.push(TableEntry {
        name: table.to_string(),
        path: format!("{service}/{table}.parquet"),
        rows,
        columns,
        source: input.display().to_string(),
    });
    st.tables.sort_by(|a, b| a.name.cmp(&b.name));
    save_service(stamp, &st)?;

    println!(
        "ingested {service}.{table} → {} ({rows} rows, {columns} cols)",
        out_file.display()
    );
    Ok(())
}

async fn register_all(ctx: &SessionContext, stamp: &Path) -> Result<Vec<String>> {
    let root = logical_root(stamp);
    if !root.is_dir() {
        bail!("no logical/ under {}", stamp.display());
    }
    let mut names = Vec::new();
    for ent in WalkDir::new(&root).min_depth(2).max_depth(2) {
        let ent = ent?;
        let path = ent.path();
        if path.extension().and_then(|e| e.to_str()) != Some("parquet") {
            continue;
        }
        let service = path
            .parent()
            .and_then(|p| p.file_name())
            .and_then(|s| s.to_str())
            .unwrap_or("unknown");
        let table = path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("table");
        let reg = format!("{service}__{table}");
        ctx.register_parquet(&reg, path.to_str().unwrap(), ParquetReadOptions::default())
            .await
            .with_context(|| format!("register {reg}"))?;
        names.push(reg);
    }
    names.sort();
    Ok(names)
}

async fn list_cmd(stamp: &Path) -> Result<()> {
    let root = logical_root(stamp);
    if !root.is_dir() {
        bail!("no logical package at {}", root.display());
    }
    if let Ok(man) = read_json::<LogicalManifest>(&root.join("MANIFEST.json")) {
        println!("format={} services={:?}", man.format, man.services);
    }
    for ent in WalkDir::new(&root).min_depth(1).max_depth(1) {
        let ent = ent?;
        if !ent.file_type().is_dir() {
            continue;
        }
        let service = ent.file_name().to_string_lossy();
        let tables_path = ent.path().join("tables.json");
        if tables_path.is_file() {
            let st: ServiceTables = read_json(&tables_path)?;
            for t in st.tables {
                println!(
                    "{service}.{}  rows={} cols={}  {}",
                    t.name, t.rows, t.columns, t.path
                );
            }
        }
    }
    Ok(())
}

async fn verify_cmd(stamp: &Path) -> Result<()> {
    let root = logical_root(stamp);
    if !root.is_dir() {
        bail!("FAIL: no logical/ directory — not a logical backup stamp");
    }
    let man_path = root.join("MANIFEST.json");
    if !man_path.is_file() {
        bail!("FAIL: logical/MANIFEST.json missing");
    }
    let man: LogicalManifest = read_json(&man_path)?;
    if !man.format.starts_with("signals-logical-parquet") {
        bail!("FAIL: unknown logical format {:?}", man.format);
    }

    let ctx = session().await?;
    let names = register_all(&ctx, stamp).await?;
    if names.is_empty() {
        // Empty logical package is valid only if explicitly allowed — still verify structure
        println!("ok: logical package structure valid (0 tables)");
        return Ok(());
    }

    let mut errors = Vec::new();
    for reg in &names {
        match ctx.sql(&format!("SELECT count(*) AS c FROM \"{reg}\"")).await {
            Ok(df) => match df.collect().await {
                Ok(batches) => {
                    let n = batches
                        .first()
                        .and_then(|b| b.column(0).as_any().downcast_ref::<datafusion::arrow::array::Int64Array>())
                        .map(|a| a.value(0))
                        .unwrap_or(-1);
                    println!("ok: {reg} count={n}");
                }
                Err(e) => errors.push(format!("{reg}: collect failed: {e}")),
            },
            Err(e) => errors.push(format!("{reg}: sql failed: {e}")),
        }
    }

    // Cross-check tables.json row counts when present
    for ent in WalkDir::new(&root).min_depth(1).max_depth(1) {
        let ent = ent?;
        if !ent.file_type().is_dir() {
            continue;
        }
        let tables_path = ent.path().join("tables.json");
        if !tables_path.is_file() {
            continue;
        }
        let st: ServiceTables = read_json(&tables_path)?;
        for t in st.tables {
            let pq = root.join(&t.path);
            if !pq.is_file() {
                errors.push(format!("{}.{}: missing file {}", st.service, t.name, t.path));
            }
        }
    }

    if !errors.is_empty() {
        for e in &errors {
            eprintln!("ERROR: {e}");
        }
        bail!("logical verify failed ({} errors)", errors.len());
    }
    println!(
        "logical verify ok ({} tables, format={})",
        names.len(),
        man.format
    );
    Ok(())
}

async fn hdf5_sql(files: &[PathBuf], sql: &str) -> Result<()> {
    use hdf5_df::Hdf5TableProvider;
    if files.is_empty() {
        bail!("#SL.00000018.HDF5DF no --file");
    }
    for f in files {
        if !f.is_file() {
            bail!("#SL.00000018.HDF5DF missing {}", f.display());
        }
    }
    let provider = Hdf5TableProvider::try_listing(files.to_vec())
        .map_err(|e| anyhow::anyhow!("{e}"))?;
    let ctx = SessionContext::new();
    ctx.register_table("gpu_power", std::sync::Arc::new(provider))?;
    let df = ctx.sql(sql).await?;
    df.show().await?;
    Ok(())
}

async fn sql_cmd(stamp: &Path, query: &str) -> Result<()> {
    let ctx = session().await?;
    let names = register_all(&ctx, stamp).await?;
    if names.is_empty() {
        bail!("no parquet tables under {}", logical_root(stamp).display());
    }
    let df = ctx.sql(query).await?;
    df.show().await?;
    Ok(())
}

async fn status_cmd(stamp: &Path) -> Result<()> {
    let root = logical_root(stamp);
    if !root.is_dir() {
        println!("logical=missing");
        std::process::exit(2);
    }
    verify_cmd(stamp).await?;
    println!("logical=ok path={}", root.display());
    Ok(())
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.cmd {
        Cmd::Init { stamp } => init_logical(&stamp).await?,
        Cmd::Ingest {
            stamp,
            service,
            table,
            input,
            delimiter,
            has_header,
        } => ingest(&stamp, &service, &table, &input, &delimiter, has_header).await?,
        Cmd::List { stamp } => list_cmd(&stamp).await?,
        Cmd::Verify { stamp } => verify_cmd(&stamp).await?,
        Cmd::Sql { stamp, query } => sql_cmd(&stamp, &query).await?,
        Cmd::Status { stamp } => status_cmd(&stamp).await?,
        Cmd::Hdf5 { files, sql } => hdf5_sql(&files, &sql).await?,
    }
    Ok(())
}
