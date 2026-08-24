// CSV stdin → Kudu gpu_metrics_tier0. Columns:
// epoch_hour,ts_ns,gpu_index,power_w,util_pct,mem_used_mb,temp_c
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

#include "kudu/client/client.h"
#include "kudu/client/write_op.h"
#include "kudu/common/partial_row.h"
#include "kudu/util/status.h"

using kudu::KuduPartialRow;
using kudu::Status;
using kudu::client::KuduClient;
using kudu::client::KuduClientBuilder;
using kudu::client::KuduError;
using kudu::client::KuduSession;
using kudu::client::KuduTable;
using kudu::client::KuduUpsert;
using kudu::client::sp::shared_ptr;

static const char kTable[] = "impala::signals_dataproducts.gpu_metrics_tier0";

int main() {
  const char* masters = std::getenv("KUDU_MASTERS");
  if (!masters) masters = "tinybox.dev.vista.zndx.org:7051";
  shared_ptr<KuduClient> client;
  Status s = KuduClientBuilder()
                 .master_server_addrs(std::vector<std::string>{masters})
                 .Build(&client);
  if (!s.ok()) {
    std::cerr << "#SL.00000024.GPUINGEST connect: " << s.ToString() << "\n";
    return 1;
  }
  shared_ptr<KuduTable> table;
  s = client->OpenTable(kTable, &table);
  if (!s.ok()) {
    std::cerr << "#SL.00000024.GPUINGEST open: " << s.ToString() << "\n";
    return 1;
  }
  shared_ptr<KuduSession> session = client->NewSession();
  s = session->SetFlushMode(KuduSession::AUTO_FLUSH_BACKGROUND);
  if (!s.ok()) {
    std::cerr << "#SL.00000024.GPUINGEST session: " << s.ToString() << "\n";
    return 1;
  }
  session->SetTimeoutMillis(30000);

  int n = 0;
  int eh, gi;
  long long ts;
  float pw, ut, mem, tmp;
  while (std::scanf(" %d,%lld,%d,%f,%f,%f,%f", &eh, &ts, &gi, &pw, &ut, &mem, &tmp) == 7) {
    KuduUpsert* up = table->NewUpsert();
    KuduPartialRow* row = up->mutable_row();
    Status r = row->SetInt32("epoch_hour", eh);
    if (r.ok()) r = row->SetInt64("ts_ns", ts);
    if (r.ok()) r = row->SetInt32("gpu_index", gi);
    if (r.ok()) r = row->SetFloat("power_w", pw);
    if (r.ok()) r = row->SetFloat("util_pct", ut);
    if (r.ok()) r = row->SetFloat("mem_used_mb", mem);
    if (r.ok()) r = row->SetFloat("temp_c", tmp);
    if (r.ok()) r = session->Apply(up);
    if (!r.ok()) {
      std::cerr << "#SL.00000024.GPUINGEST row: " << r.ToString() << "\n";
      return 1;
    }
    ++n;
  }
  s = session->Flush();
  if (!s.ok()) {
    std::vector<KuduError*> errors;
    bool overflow = false;
    session->GetPendingErrors(&errors, &overflow);
    for (KuduError* e : errors) {
      std::cerr << e->status().ToString() << "\n";
      delete e;
    }
    std::cerr << "#SL.00000024.GPUINGEST flush: " << s.ToString() << "\n";
    return 1;
  }
  std::cout << "upserted " << n << "\n";
  return 0;
}
