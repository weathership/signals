// Create gpu_metrics_tier0 via C++ Kudu client (Kerberos ticket cache).
// Guru: #SL.00000024.GPUINGEST
#include <cstdlib>
#include <ctime>
#include <iostream>
#include <string>
#include <vector>

#include "kudu/client/client.h"
#include "kudu/client/schema.h"
#include "kudu/common/partial_row.h"
#include "kudu/util/status.h"

using kudu::KuduPartialRow;
using kudu::Status;
using kudu::client::KuduClient;
using kudu::client::KuduClientBuilder;
using kudu::client::KuduColumnSchema;
using kudu::client::KuduSchema;
using kudu::client::KuduSchemaBuilder;
using kudu::client::KuduTable;
using kudu::client::KuduTableAlterer;
using kudu::client::KuduTableCreator;
using kudu::client::sp::shared_ptr;

static const char kTable[] = "impala::signals_dataproducts.gpu_metrics_tier0";

static Status AddHourRanges(KuduClient* client, const KuduSchema& schema, int hour) {
  // HASH×RANGE: add each UTC hour for [-1, +4) so the 1 Hz writer does not
  // stall at the hour boundary (table-create used to be a no-op if exists).
  for (int i = -1; i < 4; ++i) {
    KuduPartialRow* lo = schema.NewRow();
    KuduPartialRow* hi = schema.NewRow();
    Status rs = lo->SetInt32("epoch_hour", hour + i);
    if (rs.ok()) rs = hi->SetInt32("epoch_hour", hour + i + 1);
    if (!rs.ok()) return rs;
    KuduTableAlterer* alt = client->NewTableAlterer(kTable);
    Status s = alt->AddRangePartition(lo, hi)->Alter();
    delete alt;
    if (!s.ok() && s.ToString().find("already") == std::string::npos &&
        s.ToString().find("overlap") == std::string::npos &&
        s.ToString().find("Already present") == std::string::npos) {
      return s;
    }
  }
  return Status::OK();
}

int main(int argc, char** argv) {
  const char* masters = std::getenv("KUDU_MASTERS");
  if (!masters) masters = "tinybox.dev.vista.zndx.org:7051";
  int hour = argc > 1 ? std::atoi(argv[1]) : static_cast<int>(time(nullptr) / 3600);

  shared_ptr<KuduClient> client;
  Status s = KuduClientBuilder()
                 .master_server_addrs(std::vector<std::string>{masters})
                 .Build(&client);
  if (!s.ok()) {
    std::cerr << "#SL.00000024.GPUINGEST connect: " << s.ToString() << "\n";
    return 1;
  }

  bool exists = false;
  s = client->TableExists(kTable, &exists);
  if (!s.ok()) {
    std::cerr << "#SL.00000024.GPUINGEST exists: " << s.ToString() << "\n";
    return 1;
  }
  if (exists) {
    shared_ptr<KuduTable> table;
    s = client->OpenTable(kTable, &table);
    if (!s.ok()) {
      std::cerr << "#SL.00000024.GPUINGEST open: " << s.ToString() << "\n";
      return 1;
    }
    s = AddHourRanges(client.get(), table->schema(), hour);
    if (!s.ok()) {
      std::cerr << "#SL.00000024.GPUINGEST add-range: " << s.ToString() << "\n";
      return 1;
    }
    std::cout << "exists " << kTable << " ranges hour=" << hour << "\n";
    return 0;
  }

  KuduSchemaBuilder b;
  b.AddColumn("epoch_hour")->Type(KuduColumnSchema::INT32)->NotNull();
  b.AddColumn("ts_ns")->Type(KuduColumnSchema::INT64)->NotNull();
  b.AddColumn("gpu_index")->Type(KuduColumnSchema::INT32)->NotNull();
  b.AddColumn("power_w")->Type(KuduColumnSchema::FLOAT)->NotNull();
  b.AddColumn("util_pct")->Type(KuduColumnSchema::FLOAT)->NotNull();
  b.AddColumn("mem_used_mb")->Type(KuduColumnSchema::FLOAT)->NotNull();
  b.AddColumn("temp_c")->Type(KuduColumnSchema::FLOAT)->NotNull();
  b.SetPrimaryKey({"epoch_hour", "ts_ns", "gpu_index"});
  KuduSchema schema;
  s = b.Build(&schema);
  if (!s.ok()) {
    std::cerr << "#SL.00000024.GPUINGEST schema: " << s.ToString() << "\n";
    return 1;
  }

  KuduTableCreator* c = client->NewTableCreator();
  c->table_name(kTable).schema(&schema).num_replicas(1);
  c->add_hash_partitions(std::vector<std::string>{"gpu_index"}, 2);
  c->set_range_partition_columns(std::vector<std::string>{"epoch_hour"});
  for (int i = -1; i < 4; ++i) {
    KuduPartialRow* lo = schema.NewRow();
    KuduPartialRow* hi = schema.NewRow();
    lo->SetInt32("epoch_hour", hour + i);
    hi->SetInt32("epoch_hour", hour + i + 1);
    c->add_range_partition(lo, hi);
  }
  s = c->Create();
  delete c;
  if (!s.ok()) {
    std::cerr << "#SL.00000024.GPUINGEST create: " << s.ToString() << "\n";
    return 1;
  }
  std::cout << "created " << kTable << " hour=" << hour << "\n";
  return 0;
}
