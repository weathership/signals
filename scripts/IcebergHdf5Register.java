import io.jhdf.HdfFile;
import io.jhdf.api.Attribute;
import io.jhdf.api.Node;
import java.io.File;
import java.nio.ByteBuffer;
import java.util.HashMap;
import java.util.Map;
import org.apache.hadoop.conf.Configuration;
import org.apache.iceberg.DataFile;
import org.apache.iceberg.DataFiles;
import org.apache.iceberg.FileFormat;
import org.apache.iceberg.Metrics;
import org.apache.iceberg.PartitionSpec;
import org.apache.iceberg.Schema;
import org.apache.iceberg.Table;
import org.apache.iceberg.catalog.Namespace;
import org.apache.iceberg.catalog.TableIdentifier;
import org.apache.iceberg.data.GenericRecord;
import org.apache.iceberg.expressions.Expressions;
import org.apache.iceberg.rest.RESTCatalog;
import org.apache.iceberg.types.Conversions;
import org.apache.iceberg.types.Types;

/**
 * Register an analog HDF5 object as an Iceberg data file via the Polaris REST
 * catalog. Guru: #SL.00000025.TIERUP
 *
 * <pre>
 *   IcebergHdf5Register &lt;table&gt; &lt;epoch_hour&gt; &lt;s3a-path&gt; &lt;size-bytes&gt; &lt;records&gt; [local-h5]
 * </pre>
 *
 * <p>Tables: {@code gpu_metrics_tier1} (legacy grain) and {@code signal_tier1}
 * (schema_version 2). For signal_tier1 the local HDF5 copy supplies manifest
 * metrics — lower/upper bounds of {@code epoch_hour}, {@code ts_ns} and
 * {@code series_id} — so Iceberg planning skips files before opening them.
 * Without bounds only partition pruning works and a {@code ts_ns} range cannot
 * skip a single file.
 */
public final class IcebergHdf5Register {
  private static final String NS = "signals_dataproducts";

  public static void main(String[] args) {
    // <table> --create-only : make the Iceberg table exist (so the catalog
    // registry row and the UNION view resolve) before its first settle.
    boolean createOnly = args.length == 2 && "--create-only".equals(args[1]);
    if (!createOnly && args.length < 5) {
      System.err.println(
          "usage: IcebergHdf5Register <table> <epoch_hour> <s3a-path> <size> <records> [local-h5]\n"
              + "       IcebergHdf5Register <table> --create-only");
      System.exit(2);
    }
    String tableName = args[0];
    if (createOnly) {
      RESTCatalog cat = catalog();
      Namespace ns = Namespace.of(NS);
      if (!cat.namespaceExists(ns)) {
        cat.createNamespace(ns);
      }
      TableIdentifier id = TableIdentifier.of(ns, tableName);
      if (cat.tableExists(id)) {
        System.out.println("exists " + id + " loc=" + cat.loadTable(id).location());
        return;
      }
      Schema schema = schemaFor(tableName);
      Map<String, String> tbl = new HashMap<>();
      tbl.put("write.format.default", "hdf5");
      tbl.put("signals.tier", "1");
      Table t = cat.buildTable(id, schema)
          .withPartitionSpec(PartitionSpec.builderFor(schema).identity("epoch_hour").build())
          .withProperties(tbl)
          .create();
      System.out.println("created " + id + " loc=" + t.location());
      return;
    }
    int hour = Integer.parseInt(args[1]);
    String path = args[2];
    long size = Long.parseLong(args[3]);
    long records = Long.parseLong(args[4]);
    String localH5 = args.length > 5 ? args[5] : null;

    RESTCatalog cat = catalog();
    Namespace ns = Namespace.of(NS);
    if (!cat.namespaceExists(ns)) {
      cat.createNamespace(ns);
      System.out.println("created namespace " + ns);
    }
    TableIdentifier id = TableIdentifier.of(ns, tableName);
    Schema schema = schemaFor(tableName);
    PartitionSpec spec = PartitionSpec.builderFor(schema).identity("epoch_hour").build();
    Table table;
    if (cat.tableExists(id)) {
      table = cat.loadTable(id);
      System.out.println("loaded " + id + " loc=" + table.location());
    } else {
      Map<String, String> tbl = new HashMap<>();
      tbl.put("write.format.default", "hdf5");
      tbl.put("signals.tier", "1");
      table = cat.buildTable(id, schema).withPartitionSpec(spec).withProperties(tbl).create();
      System.out.println("created " + id + " loc=" + table.location());
    }

    GenericRecord part = GenericRecord.create(table.spec().partitionType());
    part.set(0, hour);
    DataFiles.Builder b =
        DataFiles.builder(table.spec())
            .withPath(path)
            .withFormat(FileFormat.HDF5)
            .withFileSizeInBytes(size)
            .withRecordCount(records)
            .withPartition(part);
    if (localH5 != null && "signal_tier1".equals(tableName)) {
      b.withMetrics(signalMetrics(schema, new File(localH5), hour, records));
      System.out.println("metrics: epoch_hour/ts_ns/series_id bounds from " + localH5);
    }
    DataFile df = b.build();
    // Idempotent per epoch_hour: replace any existing data for this hour instead
    // of appending. A re-settle (an hour that registered but failed verify, or a
    // corrected rewrite) must not double the partition -- that would fail the
    // exact-count verify and strand the hour in Kudu forever. The table is
    // identity-partitioned on epoch_hour, so this filter is partition-aligned.
    table.newOverwrite()
        .overwriteByRowFilter(Expressions.equal("epoch_hour", hour))
        .addFile(df)
        .commit();
    System.out.println("registered " + path + " records=" + records + " format=" + FileFormat.HDF5);
  }

  static Schema schemaFor(String table) {
    switch (table) {
      case "gpu_metrics_tier1":
        return new Schema(
            Types.NestedField.required(1, "epoch_hour", Types.IntegerType.get()),
            Types.NestedField.required(2, "ts_ns", Types.LongType.get()),
            Types.NestedField.required(3, "gpu_index", Types.IntegerType.get()),
            Types.NestedField.required(4, "power_w", Types.FloatType.get()),
            Types.NestedField.required(5, "util_pct", Types.FloatType.get()),
            Types.NestedField.required(6, "mem_used_mb", Types.FloatType.get()),
            Types.NestedField.required(7, "temp_c", Types.FloatType.get()));
      case "signal_tier1":
        // Mirrors signal_tier0 exactly so the UNION view is schema-identical.
        return new Schema(
            Types.NestedField.required(1, "epoch_hour", Types.IntegerType.get()),
            Types.NestedField.required(2, "ts_ns", Types.LongType.get()),
            Types.NestedField.required(3, "series_id", Types.LongType.get()),
            Types.NestedField.required(4, "src", Types.IntegerType.get()),
            Types.NestedField.optional(5, "gpu", Types.IntegerType.get()),
            Types.NestedField.optional(6, "inst", Types.IntegerType.get()),
            Types.NestedField.optional(7, "val_i", Types.LongType.get()),
            Types.NestedField.optional(8, "val_d", Types.DecimalType.of(18, 6)));
      default:
        throw new IllegalArgumentException("#SL.00000025.TIERUP unknown table " + table);
    }
  }

  /** Manifest bounds for the three predicate columns, read from /signal attrs. */
  static Metrics signalMetrics(Schema schema, File h5, int hour, long records) {
    long tsMin;
    long tsMax;
    long sMin;
    long sMax;
    try (HdfFile f = new HdfFile(h5)) {
      Node sig = f.getByPath("/signal");
      tsMin = attrLong(sig, "ts_min");
      tsMax = attrLong(sig, "ts_max");
      sMin = attrLong(sig, "series_min");
      sMax = attrLong(sig, "series_max");
    }
    Map<Integer, ByteBuffer> lower = new HashMap<>();
    Map<Integer, ByteBuffer> upper = new HashMap<>();
    Map<Integer, Long> counts = new HashMap<>();
    Map<Integer, Long> nulls = new HashMap<>();
    int fEh = schema.findField("epoch_hour").fieldId();
    int fTs = schema.findField("ts_ns").fieldId();
    int fSid = schema.findField("series_id").fieldId();
    lower.put(fEh, Conversions.toByteBuffer(Types.IntegerType.get(), hour));
    upper.put(fEh, Conversions.toByteBuffer(Types.IntegerType.get(), hour));
    lower.put(fTs, Conversions.toByteBuffer(Types.LongType.get(), tsMin));
    upper.put(fTs, Conversions.toByteBuffer(Types.LongType.get(), tsMax));
    lower.put(fSid, Conversions.toByteBuffer(Types.LongType.get(), sMin));
    upper.put(fSid, Conversions.toByteBuffer(Types.LongType.get(), sMax));
    for (int id : new int[] {fEh, fTs, fSid}) {
      counts.put(id, records);
      nulls.put(id, 0L);
    }
    return new Metrics(records, null, counts, nulls, null, lower, upper);
  }

  static long attrLong(Node n, String name) {
    Attribute a = n.getAttribute(name);
    if (a == null) {
      throw new IllegalStateException("#SL.00000029.HDF5SIGNAL missing /signal@" + name);
    }
    Object v = a.getData();
    if (v instanceof Number) {
      return ((Number) v).longValue();
    }
    if (v instanceof long[]) {
      return ((long[]) v)[0];
    }
    if (v instanceof int[]) {
      return ((int[]) v)[0];
    }
    throw new IllegalStateException("#SL.00000029.HDF5SIGNAL attr " + name + " type " + v.getClass());
  }

  static RESTCatalog catalog() {
    Map<String, String> props = new HashMap<>();
    props.put("uri", "http://127.0.0.1:8181/api/catalog");
    props.put("warehouse", "signals");
    props.put("credential", "admin:admin");
    props.put("oauth2-server-uri", "http://127.0.0.1:8181/api/catalog/v1/oauth/tokens");
    props.put("scope", "PRINCIPAL_ROLE:ALL");
    props.put("s3.endpoint", "http://127.0.0.1:9010");
    props.put("s3.path-style-access", "true");
    props.put("s3.access-key-id", "rustfsadmin");
    props.put("s3.secret-access-key", "rustfsadmin");
    props.put("client.region", "us-east-1");
    // Polarisfork locations are s3://; Hadoop only knows s3a unless mapped.
    props.put("hadoop.fs.s3.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem");
    props.put("hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem");
    props.put("hadoop.fs.s3a.endpoint", "http://127.0.0.1:9010");
    props.put("hadoop.fs.s3a.path.style.access", "true");
    props.put("hadoop.fs.s3a.connection.ssl.enabled", "false");
    props.put("hadoop.fs.s3a.access.key", "rustfsadmin");
    props.put("hadoop.fs.s3a.secret.key", "rustfsadmin");
    props.put(
        "hadoop.fs.s3a.aws.credentials.provider",
        "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider");
    Configuration hconf = new Configuration();
    hconf.set("fs.s3.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem");
    hconf.set("fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem");
    hconf.set("fs.s3a.endpoint", "http://127.0.0.1:9010");
    hconf.set("fs.s3a.path.style.access", "true");
    hconf.set("fs.s3a.connection.ssl.enabled", "false");
    hconf.set("fs.s3a.access.key", "rustfsadmin");
    hconf.set("fs.s3a.secret.key", "rustfsadmin");
    hconf.set(
        "fs.s3a.aws.credentials.provider",
        "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider");
    RESTCatalog cat = new RESTCatalog();
    cat.setConf(hconf);
    cat.initialize("signals", props);
    return cat;
  }
}
