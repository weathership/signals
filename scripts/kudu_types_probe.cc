// Create a one-row Kudu table covering every scalar type plus 1D INT64 ARRAY.
// Leaves the table in place for impala_fdw kudu_scan. Guru: #SL.00000026.KUDUARRAY
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

#include "kudu/client/client.h"
#include "kudu/client/schema.h"
#include "kudu/client/write_op.h"
#include "kudu/common/partial_row.h"
#include "kudu/util/int128.h"
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

static const char kTable[] = "impala::signals_dataproducts.kudu_types_probe";

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
  b.AddColumn("c_bool")->Type(KuduColumnSchema::BOOL);
  b.AddColumn("c_i8")->Type(KuduColumnSchema::INT8);
  b.AddColumn("c_i16")->Type(KuduColumnSchema::INT16);
  b.AddColumn("c_i32")->Type(KuduColumnSchema::INT32);
  b.AddColumn("c_i64")->Type(KuduColumnSchema::INT64);
  b.AddColumn("c_f")->Type(KuduColumnSchema::FLOAT);
  b.AddColumn("c_d")->Type(KuduColumnSchema::DOUBLE);
  b.AddColumn("c_str")->Type(KuduColumnSchema::STRING);
  b.AddColumn("c_bin")->Type(KuduColumnSchema::BINARY);
  b.AddColumn("c_ts")->Type(KuduColumnSchema::UNIXTIME_MICROS);
  b.AddColumn("c_date")->Type(KuduColumnSchema::DATE);
  b.AddColumn("c_dec")->Type(KuduColumnSchema::DECIMAL)->Precision(10)->Scale(2);
  b.AddColumn("c_vc")->Type(KuduColumnSchema::VARCHAR)->Length(16);
  const KuduColumnSchema::KuduArrayTypeDescriptor desc(KuduColumnSchema::INT64);
  b.AddColumn("c_arr")
      ->Type(KuduColumnSchema::NESTED)
      ->NestedType(KuduColumnSchema::KuduNestedTypeDescriptor(desc));
  KuduSchema schema;
  s = b.Build(&schema);
  if (!s.ok()) {
    std::cerr << "#SL.00000026.KUDUARRAY schema: " << s.ToString() << "\n";
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
  if (s.ok()) s = row->SetInt32("id", 1);
  if (s.ok()) s = row->SetBool("c_bool", true);
  if (s.ok()) s = row->SetInt8("c_i8", -8);
  if (s.ok()) s = row->SetInt16("c_i16", -16);
  if (s.ok()) s = row->SetInt32("c_i32", 32);
  if (s.ok()) s = row->SetInt64("c_i64", 64);
  if (s.ok()) s = row->SetFloat("c_f", 1.5f);
  if (s.ok()) s = row->SetDouble("c_d", 2.5);
  if (s.ok()) s = row->SetString("c_str", "hello");
  if (s.ok()) s = row->SetBinaryCopy("c_bin", "\xde\xad");
  if (s.ok()) s = row->SetUnixTimeMicros("c_ts", 1755990000000000LL);
  if (s.ok()) s = row->SetDate("c_date", 20689); /* 2026-08-24 */
  if (s.ok()) s = row->SetUnscaledDecimal("c_dec", 1234); /* 12.34 */
  if (s.ok()) s = row->SetVarchar("c_vc", "varchar");
  {
    std::vector<int64_t> vals{1, 2, 3};
    std::vector<bool> valid{true, true, true};
    if (s.ok()) s = row->SetArrayInt64("c_arr", vals, valid);
  }
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
      s = r.GetArrayInt64(14, &got, &val); /* c_arr is column 14 */
      if (!s.ok() || got.size() != 3 || got[2] != 3) {
        std::cerr << "#SL.00000026.KUDUARRAY array roundtrip failed: "
                  << s.ToString() << " n=" << got.size() << "\n";
        return 1;
      }
      ++n;
    }
  }
  std::cout << "KUDU_ALL_TYPES_OK rows=" << n
            << " table=" << kTable
            << " scalars=BOOL,INT8,INT16,INT32,INT64,FLOAT,DOUBLE,STRING,BINARY,"
               "UNIXTIME_MICROS,DATE,DECIMAL(10,2),VARCHAR(16) array=INT64[]\n";
  return n == 1 ? 0 : 1;
}
