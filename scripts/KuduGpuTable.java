import java.security.PrivilegedExceptionAction;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import javax.security.auth.Subject;
import javax.security.auth.login.AppConfigurationEntry;
import javax.security.auth.login.Configuration;
import javax.security.auth.login.LoginContext;
import org.apache.kudu.ColumnSchema;
import org.apache.kudu.Schema;
import org.apache.kudu.Type;
import org.apache.kudu.client.AlterTableOptions;
import org.apache.kudu.client.CreateTableOptions;
import org.apache.kudu.client.KuduClient;
import org.apache.kudu.client.KuduException;
import org.apache.kudu.client.KuduSession;
import org.apache.kudu.client.KuduTable;
import org.apache.kudu.client.PartialRow;
import org.apache.kudu.client.RangePartitionBound;
import org.apache.kudu.client.SessionConfiguration;
import org.apache.kudu.client.Upsert;

/**
 * Create/upsert gpu_metrics_tier0 without Impala catalog Java SASL.
 * Uses the process ticket cache (kinit signals@). Guru: #SL.00000024.GPUINGEST
 */
public final class KuduGpuTable {
  public static final String TABLE = "impala::signals_dataproducts.gpu_metrics_tier0";

  public static void main(String[] args) throws Exception {
    String krb5 = System.getenv("KRB5_CONFIG");
    if (krb5 != null) {
      System.setProperty("java.security.krb5.conf", krb5);
    }
    String cc = System.getenv("KRB5CCNAME");
    if (cc != null) {
      System.setProperty("kudu.krb5ccname", cc);
    }
    System.setProperty("kudu.jaas.debug", "true");
    System.setProperty("javax.security.auth.useSubjectCredsOnly", "false");
    run(args);
  }

  static LoginContext jaasLogin() throws Exception {
    String keytab = System.getenv().getOrDefault(
        "SIGNALS_KRB_USER_KEYTAB",
        System.getProperty("user.home") + "/local/src/wxs/signals/.devenv/kdc/signals.keytab");
    String principal = System.getenv().getOrDefault(
        "SIGNALS_USER_PRINCIPAL", "signals@DEV.VISTA.ZNDX.ORG");
    Configuration.setConfiguration(new Configuration() {
      @Override
      public AppConfigurationEntry[] getAppConfigurationEntry(String name) {
        Map<String, String> opts = new HashMap<>();
        opts.put("useKeyTab", "true");
        opts.put("keyTab", keytab);
        opts.put("principal", principal);
        opts.put("storeKey", "true");
        opts.put("doNotPrompt", "true");
        opts.put("isInitiator", "true");
        opts.put("refreshKrb5Config", "true");
        return new AppConfigurationEntry[] {
          new AppConfigurationEntry(
              "com.sun.security.auth.module.Krb5LoginModule",
              AppConfigurationEntry.LoginModuleControlFlag.REQUIRED,
              opts)
        };
      }
    });
    LoginContext lc = new LoginContext("KuduGpu");
    lc.login();
    System.out.println("jaas login " + principal);
    return lc;
  }

  static void run(String[] args) throws Exception {
    String masters = System.getenv().getOrDefault(
        "KUDU_MASTERS", "tinybox.dev.vista.zndx.org:7051");
    int hour = args.length > 0 ? Integer.parseInt(args[0])
        : (int) (System.currentTimeMillis() / 1000L / 3600L);
    try (KuduClient client = new KuduClient.KuduClientBuilder(masters).build()) {
      if (!client.tableExists(TABLE)) {
        create(client, hour);
        System.out.println("created " + TABLE);
      } else {
        System.out.println("exists " + TABLE);
      }
      ensureRange(client, hour);
      if (args.length > 1 && "list".equals(args[1])) {
        System.out.println("open ok " + client.openTable(TABLE).getName());
      }
    }
  }

  static void create(KuduClient client, int hour) throws KuduException {
    List<ColumnSchema> cols = new ArrayList<>();
    cols.add(new ColumnSchema.ColumnSchemaBuilder("epoch_hour", Type.INT32).key(true).build());
    cols.add(new ColumnSchema.ColumnSchemaBuilder("ts_ns", Type.INT64).key(true).build());
    cols.add(new ColumnSchema.ColumnSchemaBuilder("gpu_index", Type.INT32).key(true).build());
    cols.add(new ColumnSchema.ColumnSchemaBuilder("power_w", Type.FLOAT).build());
    cols.add(new ColumnSchema.ColumnSchemaBuilder("util_pct", Type.FLOAT).build());
    cols.add(new ColumnSchema.ColumnSchemaBuilder("mem_used_mb", Type.FLOAT).build());
    cols.add(new ColumnSchema.ColumnSchemaBuilder("temp_c", Type.FLOAT).build());
    Schema schema = new Schema(cols);
    CreateTableOptions opts = new CreateTableOptions()
        .setNumReplicas(1)
        .setRangePartitionColumns(java.util.Collections.singletonList("epoch_hour"))
        .addHashPartitions(java.util.Collections.singletonList("gpu_index"), 2);
    for (int i = -1; i < 4; i++) {
      PartialRow lo = schema.newPartialRow();
      PartialRow hi = schema.newPartialRow();
      lo.addInt("epoch_hour", hour + i);
      hi.addInt("epoch_hour", hour + i + 1);
      opts.addRangePartition(lo, hi,
          RangePartitionBound.INCLUSIVE_BOUND, RangePartitionBound.EXCLUSIVE_BOUND);
    }
    client.createTable(TABLE, schema, opts);
  }

  static void ensureRange(KuduClient client, int hour) throws KuduException {
    KuduTable table = client.openTable(TABLE);
    for (int i = -1; i < 4; i++) {
      PartialRow lo = table.getSchema().newPartialRow();
      PartialRow hi = table.getSchema().newPartialRow();
      lo.addInt("epoch_hour", hour + i);
      hi.addInt("epoch_hour", hour + i + 1);
      try {
        AlterTableOptions alter = new AlterTableOptions();
        alter.addRangePartition(lo, hi,
            RangePartitionBound.INCLUSIVE_BOUND, RangePartitionBound.EXCLUSIVE_BOUND);
        client.alterTable(TABLE, alter);
      } catch (KuduException e) {
        String m = e.getMessage() == null ? "" : e.getMessage();
        if (!m.toLowerCase().contains("already") && !m.toLowerCase().contains("overlap")) {
          throw e;
        }
      }
    }
  }

  public static void upsert(
      KuduClient client, int epochHour, long tsNs, int gpu,
      float power, float util, float mem, float temp) throws KuduException {
    KuduTable table = client.openTable(TABLE);
    KuduSession session = client.newSession();
    session.setFlushMode(SessionConfiguration.FlushMode.AUTO_FLUSH_SYNC);
    Upsert up = table.newUpsert();
    PartialRow row = up.getRow();
    row.addInt("epoch_hour", epochHour);
    row.addLong("ts_ns", tsNs);
    row.addInt("gpu_index", gpu);
    row.addFloat("power_w", power);
    row.addFloat("util_pct", util);
    row.addFloat("mem_used_mb", mem);
    row.addFloat("temp_c", temp);
    session.apply(up);
    session.close();
  }
}
