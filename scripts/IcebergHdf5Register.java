import java.util.HashMap;
import java.util.Map;
import org.apache.iceberg.DataFile;
import org.apache.iceberg.DataFiles;
import org.apache.iceberg.FileFormat;
import org.apache.iceberg.PartitionSpec;
import org.apache.iceberg.Schema;
import org.apache.iceberg.Table;
import org.apache.iceberg.catalog.Namespace;
import org.apache.iceberg.catalog.TableIdentifier;
import org.apache.iceberg.data.GenericRecord;
import org.apache.iceberg.rest.RESTCatalog;
import org.apache.iceberg.types.Types;

/** Register analog HDF5 as Iceberg data file via Polarisfork REST. Guru: #SL.00000025.TIERUP */
public final class IcebergHdf5Register {
  public static void main(String[] args) {
    int hour = args.length > 0 ? Integer.parseInt(args[0]) : 496537;
    long size = args.length > 1 ? Long.parseLong(args[1]) : 124583L;
    long records = args.length > 2 ? Long.parseLong(args[2]) : 12156L;
    String path =
        "s3a://signals-dataproducts/iceberg/signals_dataproducts/gpu_metrics_tier1/data/epoch_hour="
            + hour
            + "/gpu_metrics_hour_"
            + hour
            + ".h5";

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

    org.apache.hadoop.conf.Configuration hconf = new org.apache.hadoop.conf.Configuration();
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

    Namespace ns = Namespace.of("signals_dataproducts");
    if (!cat.namespaceExists(ns)) {
      cat.createNamespace(ns);
      System.out.println("created namespace " + ns);
    }
    TableIdentifier id = TableIdentifier.of(ns, "gpu_metrics_tier1");
    if (Boolean.parseBoolean(System.getenv().getOrDefault("GPU_METRICS_ICEBERG_RECREATE", "false"))
        && cat.tableExists(id)) {
      cat.dropTable(id, false);
      System.out.println("dropped " + id);
    }
    Schema schema =
        new Schema(
            Types.NestedField.required(1, "epoch_hour", Types.IntegerType.get()),
            Types.NestedField.required(2, "ts_ns", Types.LongType.get()),
            Types.NestedField.required(3, "gpu_index", Types.IntegerType.get()),
            Types.NestedField.required(4, "power_w", Types.FloatType.get()),
            Types.NestedField.required(5, "util_pct", Types.FloatType.get()),
            Types.NestedField.required(6, "mem_used_mb", Types.FloatType.get()),
            Types.NestedField.required(7, "temp_c", Types.FloatType.get()));
    PartitionSpec spec = PartitionSpec.builderFor(schema).identity("epoch_hour").build();
    Table table;
    if (cat.tableExists(id)) {
      table = cat.loadTable(id);
      System.out.println("loaded " + id + " loc=" + table.location());
    } else {
      Map<String, String> tbl = new HashMap<>();
      tbl.put("write.format.default", "hdf5");
      tbl.put("signals.tier", "1");
      table =
          cat.buildTable(id, schema)
              .withPartitionSpec(spec)
              .withProperties(tbl)
              .create();
      System.out.println("created " + id + " loc=" + table.location());
    }

    GenericRecord part = GenericRecord.create(table.spec().partitionType());
    part.set(0, hour);
    DataFile df =
        DataFiles.builder(table.spec())
            .withPath(path)
            .withFormat(FileFormat.HDF5)
            .withFileSizeInBytes(size)
            .withRecordCount(records)
            .withPartition(part)
            .build();
    table.newAppend().appendFile(df).commit();
    System.out.println("appended " + path + " records=" + records + " format=" + FileFormat.HDF5);
  }
}
