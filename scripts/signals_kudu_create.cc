// Create the signals tier0 + reference tables via the C++ Kudu client.
// Guru: #SL.00000027.SCHEMA2
//
// HS2 `CREATE ... STORED AS KUDU` SIGSEGV'd the tablet server 415 times on
// 2026-08-24 (17:38 -> 18:57). Table creation goes through this binary and
// never through Impala DDL. See docs/scratch/2026-08-25/214236_schema-final-e2e.md
//
// Usage:  signals_kudu_create [--all | <table>] [epoch_hour]
//
// Idempotent: an existing table only gets its missing range partitions added,
// so this is safe to run from a process supervisor ahead of the write head.
#include <cstdlib>
#include <cstring>
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
using kudu::client::KuduColumnSpec;
using kudu::client::KuduColumnStorageAttributes;
using kudu::client::KuduSchema;
using kudu::client::KuduSchemaBuilder;
using kudu::client::KuduTable;
using kudu::client::KuduTableAlterer;
using kudu::client::KuduTableCreator;
using kudu::client::sp::shared_ptr;

namespace {

const char kGuru[] = "#SL.00000027.SCHEMA2";
const char kPrefix[] = "impala::signals_dataproducts.";

using Enc = KuduColumnStorageAttributes::EncodingType;
using Cmp = KuduColumnStorageAttributes::CompressionType;

/* Hot window in days. Kudu drops a whole day once its 24 HDF5 objects have
 * settled; tier1 object width stays hourly and is deliberately decoupled. */
const int kHotDays = 3;
const int kHoursPerDay = 24;

KuduColumnSpec* Col(KuduSchemaBuilder* b, const char* name,
                    KuduColumnSchema::DataType t, bool not_null, Enc e) {
  KuduColumnSpec* c = b->AddColumn(name)->Type(t)->Encoding(e)->Compression(Cmp::LZ4);
  if (not_null) {
    c->NotNull();
  } else {
    c->Nullable();
  }
  return c;
}

/* 1D array. No Encoding(): array cells are BINARY-physical and the element
 * encodings do not apply. LZ4 still helps on float payloads. */
void ArrCol(KuduSchemaBuilder* b, const char* name,
            KuduColumnSchema::DataType elem, bool not_null) {
  const KuduColumnSchema::KuduArrayTypeDescriptor d(elem);
  KuduColumnSpec* c = b->AddColumn(name)
                          ->Type(KuduColumnSchema::NESTED)
                          ->NestedType(KuduColumnSchema::KuduNestedTypeDescriptor(d))
                          ->Compression(Cmp::LZ4);
  if (not_null) {
    c->NotNull();
  } else {
    c->Nullable();
  }
}

struct TableSpec {
  const char* name;
  void (*build)(KuduSchemaBuilder*);
  std::vector<std::string> pk;
  std::vector<std::string> hash_cols;
  int hash_buckets;
  bool ranged; /* day-wide RANGE(epoch_hour) */
};

/* ---- signal_series: series registry. Declares each series' storage type and
 * canonical unit; the ingest parser routes val_i vs val_d on vtype. ---- */
void BuildSignalSeries(KuduSchemaBuilder* b) {
  Col(b, "series_id", KuduColumnSchema::INT64, true, Enc::BIT_SHUFFLE);
  Col(b, "name", KuduColumnSchema::STRING, true, Enc::DICT_ENCODING);
  Col(b, "vtype", KuduColumnSchema::INT8, true, Enc::RLE);
  Col(b, "unit", KuduColumnSchema::STRING, true, Enc::DICT_ENCODING);
  Col(b, "src", KuduColumnSchema::INT8, true, Enc::RLE);
  Col(b, "dcgm_field", KuduColumnSchema::STRING, false, Enc::DICT_ENCODING);
  Col(b, "description", KuduColumnSchema::STRING, false, Enc::PLAIN_ENCODING);
}

/* ---- signal_tier0: every scalar sample. val_i carries integer-native
 * sources (16 of 17 DCGM families, plus power as mW); val_d carries genuine
 * floats (vLLM ratios, latency histograms). Exactly one is non-NULL. ---- */
void BuildSignalTier0(KuduSchemaBuilder* b) {
  Col(b, "epoch_hour", KuduColumnSchema::INT32, true, Enc::RLE);
  Col(b, "ts_ns", KuduColumnSchema::INT64, true, Enc::BIT_SHUFFLE);
  Col(b, "series_id", KuduColumnSchema::INT64, true, Enc::BIT_SHUFFLE);
  Col(b, "src", KuduColumnSchema::INT8, true, Enc::RLE);
  Col(b, "gpu", KuduColumnSchema::INT8, false, Enc::RLE);
  Col(b, "inst", KuduColumnSchema::INT16, false, Enc::RLE);
  Col(b, "val_i", KuduColumnSchema::INT64, false, Enc::BIT_SHUFFLE);
  Col(b, "val_d", KuduColumnSchema::DECIMAL, false, Enc::BIT_SHUFFLE)
      ->Precision(18)
      ->Scale(6);
}

/* ---- latent_tier0: LatentMAS thoughts (2048-d) and transferred KV
 * (1024-d per GQA side per layer). seq is the row ordinal within the instant,
 * so a KV step emits seq=0..27 carrying layer=0..27 without widening the PK.
 * Requires --array_cell_max_elem_num >= 4096 (default 1024). ---- */
void BuildLatentTier0(KuduSchemaBuilder* b) {
  Col(b, "epoch_hour", KuduColumnSchema::INT32, true, Enc::RLE);
  Col(b, "ts_ns", KuduColumnSchema::INT64, true, Enc::BIT_SHUFFLE);
  Col(b, "stream_id", KuduColumnSchema::INT64, true, Enc::BIT_SHUFFLE);
  Col(b, "seq", KuduColumnSchema::INT32, true, Enc::RLE);
  Col(b, "kind", KuduColumnSchema::INT8, true, Enc::RLE);
  Col(b, "step", KuduColumnSchema::INT32, true, Enc::RLE);
  Col(b, "layer", KuduColumnSchema::INT16, false, Enc::RLE);
  Col(b, "norm", KuduColumnSchema::FLOAT, false, Enc::BIT_SHUFFLE);
  Col(b, "agent", KuduColumnSchema::STRING, true, Enc::DICT_ENCODING);
  Col(b, "model", KuduColumnSchema::STRING, true, Enc::DICT_ENCODING);
  Col(b, "ref", KuduColumnSchema::STRING, false, Enc::DICT_ENCODING);
  ArrCol(b, "vec", KuduColumnSchema::FLOAT, false);
  ArrCol(b, "k_vec", KuduColumnSchema::FLOAT, false);
  ArrCol(b, "v_vec", KuduColumnSchema::FLOAT, false);
}

/* ---- clt_feature: stable identity + top_logits signature. Written once per
 * CLT model; 28 x 20480 rows. Never tiers. ---- */
void BuildCltFeature(KuduSchemaBuilder* b) {
  Col(b, "model_id", KuduColumnSchema::INT32, true, Enc::RLE);
  Col(b, "layer", KuduColumnSchema::INT16, true, Enc::RLE);
  Col(b, "feature_idx", KuduColumnSchema::INT32, true, Enc::BIT_SHUFFLE);
  ArrCol(b, "top_token_id", KuduColumnSchema::INT32, true);
  ArrCol(b, "top_logit", KuduColumnSchema::FLOAT, true);
  Col(b, "decoder_norm", KuduColumnSchema::FLOAT, false, Enc::BIT_SHUFFLE);
}

/* ---- clt_label: append-only bitemporal. valid_from_ns is IN THE PK so a
 * re-label is a new row and can never overwrite the history this table exists
 * to hold. INSERT only -- there is no UPDATE path. ---- */
void BuildCltLabel(KuduSchemaBuilder* b) {
  Col(b, "model_id", KuduColumnSchema::INT32, true, Enc::RLE);
  Col(b, "layer", KuduColumnSchema::INT16, true, Enc::RLE);
  Col(b, "feature_idx", KuduColumnSchema::INT32, true, Enc::BIT_SHUFFLE);
  Col(b, "valid_from_ns", KuduColumnSchema::INT64, true, Enc::BIT_SHUFFLE);
  Col(b, "label", KuduColumnSchema::STRING, true, Enc::DICT_ENCODING);
  Col(b, "agent", KuduColumnSchema::STRING, true, Enc::DICT_ENCODING);
  Col(b, "confidence", KuduColumnSchema::FLOAT, false, Enc::BIT_SHUFFLE);
  Col(b, "evidence_ref", KuduColumnSchema::STRING, false, Enc::DICT_ENCODING);
  Col(b, "supersedes_ns", KuduColumnSchema::INT64, false, Enc::BIT_SHUFFLE);
}

/* ---- clt_activation_tier0: the text->feature firing event. Sparse top-k
 * pairs (~115) are 230 elements / ~920 B, inside both caps at their defaults;
 * the dense alternative is 20480 floats = 80 KB, over the 64 KB cell cap. ---- */
void BuildCltActivationTier0(KuduSchemaBuilder* b) {
  Col(b, "epoch_hour", KuduColumnSchema::INT32, true, Enc::RLE);
  Col(b, "ts_ns", KuduColumnSchema::INT64, true, Enc::BIT_SHUFFLE);
  Col(b, "text_id", KuduColumnSchema::INT64, true, Enc::BIT_SHUFFLE);
  Col(b, "pos", KuduColumnSchema::INT32, true, Enc::RLE);
  Col(b, "layer", KuduColumnSchema::INT16, true, Enc::RLE);
  ArrCol(b, "feat_idx", KuduColumnSchema::INT32, true);
  ArrCol(b, "feat_val", KuduColumnSchema::FLOAT, true);
  Col(b, "nnz", KuduColumnSchema::INT32, true, Enc::BIT_SHUFFLE);
  Col(b, "agent", KuduColumnSchema::STRING, false, Enc::DICT_ENCODING);
  Col(b, "ref", KuduColumnSchema::STRING, false, Enc::DICT_ENCODING);
}

const std::vector<TableSpec>& Specs() {
  static const std::vector<TableSpec> kSpecs = {
      {"signal_series", BuildSignalSeries, {"series_id"}, {"series_id"}, 2, false},
      {"signal_tier0", BuildSignalTier0,
       {"epoch_hour", "ts_ns", "series_id"}, {"series_id"}, 4, true},
      {"latent_tier0", BuildLatentTier0,
       {"epoch_hour", "ts_ns", "stream_id", "seq"}, {"stream_id"}, 2, true},
      {"clt_feature", BuildCltFeature,
       {"model_id", "layer", "feature_idx"}, {"feature_idx"}, 2, false},
      {"clt_label", BuildCltLabel,
       {"model_id", "layer", "feature_idx", "valid_from_ns"}, {"feature_idx"}, 2, false},
      {"clt_activation_tier0", BuildCltActivationTier0,
       {"epoch_hour", "ts_ns", "text_id", "pos", "layer"}, {"text_id"}, 4, true},
  };
  return kSpecs;
}

/* Day-aligned lower bound of the day containing 'hour'. */
int DayFloor(int hour) { return (hour / kHoursPerDay) * kHoursPerDay; }

bool BenignRangeError(const Status& s) {
  const std::string t = s.ToString();
  return t.find("already") != std::string::npos ||
         t.find("Already present") != std::string::npos ||
         t.find("overlap") != std::string::npos;
}

/* Provision [today-1day, today+2days) so the writer never stalls at a
 * boundary. Adding an existing range is benign. */
Status AddDayRanges(KuduClient* client, const std::string& table,
                    const KuduSchema& schema, int hour) {
  const int day0 = DayFloor(hour);
  for (int i = -1; i < kHotDays - 1; ++i) {
    KuduPartialRow* lo = schema.NewRow();
    KuduPartialRow* hi = schema.NewRow();
    Status rs = lo->SetInt32("epoch_hour", day0 + i * kHoursPerDay);
    if (rs.ok()) rs = hi->SetInt32("epoch_hour", day0 + (i + 1) * kHoursPerDay);
    if (!rs.ok()) return rs;
    KuduTableAlterer* alt = client->NewTableAlterer(table);
    Status s = alt->AddRangePartition(lo, hi)->Alter();
    delete alt;
    if (!s.ok() && !BenignRangeError(s)) return s;
  }
  return Status::OK();
}

int CreateOne(KuduClient* client, const TableSpec& spec, int hour) {
  const std::string full = std::string(kPrefix) + spec.name;

  bool exists = false;
  Status s = client->TableExists(full, &exists);
  if (!s.ok()) {
    std::cerr << kGuru << " exists " << spec.name << ": " << s.ToString() << "\n";
    return 1;
  }
  if (exists) {
    if (!spec.ranged) {
      std::cout << "exists " << spec.name << " (reference, no ranges)\n";
      return 0;
    }
    shared_ptr<KuduTable> table;
    s = client->OpenTable(full, &table);
    if (!s.ok()) {
      std::cerr << kGuru << " open " << spec.name << ": " << s.ToString() << "\n";
      return 1;
    }
    s = AddDayRanges(client, full, table->schema(), hour);
    if (!s.ok()) {
      std::cerr << kGuru << " add-range " << spec.name << ": " << s.ToString() << "\n";
      return 1;
    }
    std::cout << "exists " << spec.name << " ranges day=" << DayFloor(hour) << "\n";
    return 0;
  }

  KuduSchemaBuilder b;
  spec.build(&b);
  b.SetPrimaryKey(spec.pk);
  KuduSchema schema;
  s = b.Build(&schema);
  if (!s.ok()) {
    std::cerr << kGuru << " schema " << spec.name << ": " << s.ToString() << "\n";
    return 1;
  }

  KuduTableCreator* c = client->NewTableCreator();
  c->table_name(full).schema(&schema).num_replicas(1);
  c->add_hash_partitions(spec.hash_cols, spec.hash_buckets);
  int tablets = spec.hash_buckets;
  if (spec.ranged) {
    c->set_range_partition_columns(std::vector<std::string>{"epoch_hour"});
    const int day0 = DayFloor(hour);
    for (int i = -1; i < kHotDays - 1; ++i) {
      KuduPartialRow* lo = schema.NewRow();
      KuduPartialRow* hi = schema.NewRow();
      /* A silently-failed bound would create a partition over the wrong
       * range, so surface it rather than discarding the Status. */
      Status rs = lo->SetInt32("epoch_hour", day0 + i * kHoursPerDay);
      if (rs.ok()) rs = hi->SetInt32("epoch_hour", day0 + (i + 1) * kHoursPerDay);
      if (!rs.ok()) {
        std::cerr << kGuru << " range-bound " << spec.name << ": "
                  << rs.ToString() << "\n";
        delete c;
        return 1;
      }
      c->add_range_partition(lo, hi);
    }
    tablets *= kHotDays;
  }
  s = c->Create();
  delete c;
  if (!s.ok()) {
    std::cerr << kGuru << " create " << spec.name << ": " << s.ToString() << "\n";
    return 1;
  }
  std::cout << "created " << spec.name << " tablets=" << tablets
            << (spec.ranged ? " ranged" : " reference") << "\n";
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  const char* masters = std::getenv("KUDU_MASTERS");
  if (!masters) masters = "tinybox.dev.vista.zndx.org:7051";

  std::string which = argc > 1 ? argv[1] : "--all";
  int hour = argc > 2 ? std::atoi(argv[2])
                      : static_cast<int>(time(nullptr) / 3600);

  shared_ptr<KuduClient> client;
  Status s = KuduClientBuilder()
                 .master_server_addrs(std::vector<std::string>{masters})
                 .Build(&client);
  if (!s.ok()) {
    std::cerr << kGuru << " connect: " << s.ToString() << "\n";
    return 1;
  }

  int rc = 0;
  bool matched = false;
  for (const TableSpec& spec : Specs()) {
    if (which != "--all" && which != spec.name) continue;
    matched = true;
    int one = CreateOne(client.get(), spec, hour);
    if (one != 0) rc = one;
  }
  if (!matched) {
    std::cerr << kGuru << " unknown table: " << which << "\n  known:";
    for (const TableSpec& spec : Specs()) std::cerr << " " << spec.name;
    std::cerr << "\n";
    return 2;
  }
  return rc;
}
