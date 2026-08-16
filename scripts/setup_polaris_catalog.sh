#!/usr/bin/env bash
# Create the Signals Iceberg catalog on Polaris with warehouse on RustFS.
#
# Catalog metadata (namespaces, table pointers) may live in the admin Postgres
# `polaris` database. Product rows do not — those are Iceberg on RustFS only.
set -euo pipefail

CATALOG_NAME="${POLARIS_CATALOG_NAME:-signals}"
S3_ENDPOINT="${S3_ENDPOINT:-http://127.0.0.1:9010}"
S3_BUCKET="${S3_BUCKET:-signals-dataproducts}"
S3_REGION="${S3_REGION:-us-east-1}"
S3_ACCESS_KEY="${S3_ACCESS_KEY:-${RUSTFS_ACCESS_KEY:-rustfsadmin}}"
S3_SECRET_KEY="${S3_SECRET_KEY:-${RUSTFS_SECRET_KEY:-rustfsadmin}}"
WAREHOUSE="${POLARIS_WAREHOUSE:-s3://${S3_BUCKET}/iceberg}"
POLARIS_HTTP="${POLARIS_HTTP:-http://127.0.0.1:8181}"
POLARIS_ADMIN="${POLARIS_ADMIN:-http://127.0.0.1:8182}"

echo "=== Polaris catalog (Signals / RustFS) ==="
echo "  catalog:   $CATALOG_NAME"
echo "  warehouse: $WAREHOUSE"
echo "  s3:        $S3_ENDPOINT  bucket=$S3_BUCKET"

echo "Waiting for RustFS at $S3_ENDPOINT ..."
for i in $(seq 1 30); do
  if timeout 2 bash -c 'echo >/dev/tcp/127.0.0.1/9010' 2>/dev/null; then
    echo "RustFS TCP :9010 is up"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "ERROR: RustFS not reachable at $S3_ENDPOINT" >&2
    exit 1
  fi
  sleep 2
done

echo "Waiting for Polaris admin $POLARIS_ADMIN ..."
for i in $(seq 1 60); do
  if curl -sf "$POLARIS_ADMIN/q/health/ready" >/dev/null 2>&1; then
    echo "Polaris is ready"
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "ERROR: Polaris not ready at $POLARIS_ADMIN" >&2
    exit 1
  fi
  sleep 2
done

TOKEN=$(curl -sf -X POST "$POLARIS_HTTP/api/catalog/v1/oauth/tokens" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=admin&client_secret=admin&scope=PRINCIPAL_ROLE:ALL" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null || true)

if [ -z "${TOKEN:-}" ]; then
  echo "Warning: no OAuth token; trying Basic admin:admin"
  AUTH_HEADER="Authorization: Basic YWRtaW46YWRtaW4="
else
  AUTH_HEADER="Authorization: Bearer $TOKEN"
fi

if [ -n "${TOKEN:-}" ]; then
  EXISTING=$(curl -sf -H "Authorization: Bearer $TOKEN" \
    "$POLARIS_HTTP/api/management/v1/catalogs" 2>/dev/null || true)
  if echo "$EXISTING" | grep -q "\"name\":\"${CATALOG_NAME}\""; then
    echo "Catalog '${CATALOG_NAME}' already exists — skip create"
    exit 0
  fi
fi

HTTP_CODE=$(curl -s -o /tmp/polaris-catalog-create.json -w "%{http_code}" \
  -X POST "$POLARIS_HTTP/api/management/v1/catalogs" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{
    \"catalog\": {
      \"name\": \"${CATALOG_NAME}\",
      \"type\": \"INTERNAL\",
      \"storageConfigInfo\": {
        \"storageType\": \"S3\",
        \"endpoint\": \"${S3_ENDPOINT}\",
        \"pathStyleAccess\": true,
        \"region\": \"${S3_REGION}\",
        \"stsUnavailable\": true,
        \"allowedLocations\": [
          \"s3://${S3_BUCKET}\",
          \"${WAREHOUSE}\"
        ]
      },
      \"properties\": {
        \"default-base-location\": \"${WAREHOUSE}\"
      }
    }
  }")

echo "Create catalog HTTP $HTTP_CODE"
cat /tmp/polaris-catalog-create.json 2>/dev/null || true
echo

if [ "$HTTP_CODE" != "201" ] && [ "$HTTP_CODE" != "200" ]; then
  if [ "$HTTP_CODE" = "409" ] || grep -qi 'already exists\|Conflict' /tmp/polaris-catalog-create.json 2>/dev/null; then
    echo "Catalog already present (HTTP $HTTP_CODE)"
  else
    echo "ERROR: catalog create failed" >&2
    exit 1
  fi
fi

if [ -n "${TOKEN:-}" ]; then
  curl -sf -X POST "$POLARIS_HTTP/api/management/v1/catalogs/${CATALOG_NAME}/catalog-roles" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"catalogRole":{"name":"data_access","properties":{}}}' >/dev/null || true
  for privilege in CATALOG_MANAGE_CONTENT CATALOG_MANAGE_ACCESS TABLE_READ_DATA TABLE_WRITE_DATA NAMESPACE_FULL_METADATA TABLE_FULL_METADATA; do
    curl -sf -X PUT "$POLARIS_HTTP/api/management/v1/catalogs/${CATALOG_NAME}/catalog-roles/data_access/grants" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"grant\":{\"type\":\"catalog\",\"privilege\":\"${privilege}\"}}" >/dev/null || true
  done
  curl -sf -X PUT "$POLARIS_HTTP/api/management/v1/principal-roles/service_admin/catalog-roles/${CATALOG_NAME}" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"catalogRole":{"name":"data_access"}}' >/dev/null || true
fi

echo "=== Setup complete ==="
echo "Catalog: $CATALOG_NAME"
echo "Base location: $WAREHOUSE (RustFS; not pglite)"
