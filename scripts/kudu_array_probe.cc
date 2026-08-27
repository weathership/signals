// Runtime check: this Kudu 1.19 build's 1D NESTED array type.
// Guru: #SL.00000026.KUDUARRAY
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

#include "kudu/client/client.h"
#include "kudu/client/schema.h"
#include "kudu/client/write_op.h"
#include "kudu/common/partial_row.h"
#include "kudu/util/status.h"

using kudu::KuduPartialRow;
using kudu::Status;
using kudu::client::KuduClient;
using kudu::client::KuduClientBuilder;
using kudu::client::KuduColumnSchema;
using kudu::client::KuduInsert;
using kudu::client::KuduScanBatch;
using kudu::client::KuduScanner;
using kudu::client::KuduSchema;
using kudu::client::KuduSchemaBuilder;
using kudu::client::KuduSession;
using kudu::client::KuduTable;
using kudu::client::KuduTableCreator;
using kudu::client::sp::shared_ptr;

static const char kTable[] = "impala::signals_dataproducts.array_probe";

int main() {
  const char* masters = std::getenv("KUDU_MASTERS");
  if (!masters) masters = "tinybox.dev.vista.zndx.org:7051";
  shared_ptr<KuduClient> client;
  Status s = KuduClientBuilder()
                 .master_server_addrs(std::vector<std::string>{masters})
                 .Build(&client);
  if (!s.ok()) {
    std::cerr << "#SL.00000026.KUDUARRAY connect: " << s.ToString() << "\n";
    return 1;
  }
  bool exists = false;
  s = client->TableExists(kTable, &exists);
  if (s.ok() && exists) {
    s = client->DeleteTable(kTable);
    if (!s.ok()) {
      std::cerr << "#SL.00000026.KUDUARRAY drop: " << s.ToString() << "\n";
      return 1;
    }
  }

  KuduSchemaBuilder b;
  b.AddColumn("id")->Type(KuduColumnSchema::INT32)->NotNull()->PrimaryKey();
  const KuduColumnSchema::KuduArrayTypeDescriptor desc(KuduColumnSchema::INT64);
  b.AddColumn("arr_int64")
      ->Type(KuduColumnSchema::NESTED)
      ->NestedType(KuduColumnSchema::KuduNestedTypeDescriptor(desc));
  KuduSchema schema;
  s = b.Build(&schema);
  if (!s.ok()) {
    std::cerr << "#SL.00000026.KUDUARRAY schema: " << s.ToString() << "\n";
    return 1;
  }
  const KuduColumnSchema arr_col = schema.Column(1);
  if (arr_col.type() != KuduColumnSchema::NESTED || arr_col.nested_type() == nullptr ||
      !arr_col.nested_type()->is_array()) {
    std::cerr << "#SL.00000026.KUDUARRAY schema is not 1D array\n";
    return 1;
  }

  KuduTableCreator* c = client->NewTableCreator();
  s = c->table_name(kTable)
           .schema(&schema)
           .num_replicas(1)
           .add_hash_partitions(std::vector<std::string>{"id"}, 2)
           .Create();
  delete c;
  if (!s.ok()) {
    std::cerr << "#SL.00000026.KUDUARRAY create: " << s.ToString() << "\n";
    return 1;
  }

  shared_ptr<KuduTable> table;
  s = client->OpenTable(kTable, &table);
  if (!s.ok()) {
    std::cerr << "#SL.00000026.KUDUARRAY open: " << s.ToString() << "\n";
    return 1;
  }
  shared_ptr<KuduSession> session = client->NewSession();
  s = session->SetFlushMode(KuduSession::MANUAL_FLUSH);
  if (!s.ok()) {
    std::cerr << "#SL.00000026.KUDUARRAY session: " << s.ToString() << "\n";
    return 1;
  }
  KuduInsert* ins = table->NewInsert();
  KuduPartialRow* row = ins->mutable_row();
  s = row->SetInt32("id", 1);
  std::vector<int64_t> vals{1, 2, 3};
  std::vector<bool> valid{true, true, true};
  if (s.ok()) s = row->SetArrayInt64("arr_int64", vals, valid);
  if (s.ok()) s = session->Apply(ins);
  if (s.ok()) s = session->Flush();
  if (!s.ok()) {
    std::cerr << "#SL.00000026.KUDUARRAY insert: " << s.ToString() << "\n";
    return 1;
  }

  KuduScanner scanner(table.get());
  s = scanner.Open();
  if (!s.ok()) {
    std::cerr << "#SL.00000026.KUDUARRAY scan: " << s.ToString() << "\n";
    return 1;
  }
  KuduScanBatch batch;
  int n = 0;
  while (scanner.HasMoreRows()) {
    s = scanner.NextBatch(&batch);
    if (!s.ok()) {
      std::cerr << "#SL.00000026.KUDUARRAY batch: " << s.ToString() << "\n";
      return 1;
    }
    for (KuduScanBatch::RowPtr r : batch) {
      std::vector<int64_t> got;
      std::vector<bool> val;
      s = r.GetArrayInt64(1, &got, &val);
      if (!s.ok() || got.size() != 3 || got[2] != 3) {
        std::cerr << "#SL.00000026.KUDUARRAY roundtrip failed: " << s.ToString()
                  << " n=" << got.size() << "\n";
        return 1;
      }
      ++n;
    }
  }
  s = client->DeleteTable(kTable);
  if (!s.ok()) {
    std::cerr << "#SL.00000026.KUDUARRAY cleanup: " << s.ToString() << "\n";
    return 1;
  }
  std::cout << "KUDU_1D_ARRAY_OK rows=" << n
            << " version=1.19.0-SNAPSHOT element=INT64\n";
  return n == 1 ? 0 : 1;
}
