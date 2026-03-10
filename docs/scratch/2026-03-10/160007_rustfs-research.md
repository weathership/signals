# RustFS Research: S3-Compatible Object Storage Alternative to MinIO

Date: 2026-03-10

## What is RustFS?

RustFS is an open-source, S3-compatible, high-performance distributed object storage system
written in Rust. It positions itself as a direct replacement for MinIO, combining MinIO's
simplicity with Rust's memory safety and zero-GC performance model. It uses Tokio for async
I/O, multiplexing thousands of concurrent requests as lightweight tasks without OS thread
overhead.

- **Repository:** <https://github.com/rustfs/rustfs>
- **Website:** <https://rustfs.com/>
- **Documentation:** <https://docs.rustfs.com/>
- **License:** Apache 2.0
- **Language:** Rust
- **GitHub Stars:** ~23,000
- **Current Version:** 1.0.0-alpha (latest alpha.83+)
- **Development started:** December 2023
- **Open-sourced:** July 2, 2025
- **Docker image:** `rustfs/rustfs` (amd64 + arm64)

## Why Consider RustFS Over MinIO?

### MinIO's Deterioration

MinIO has made a series of trust-destroying moves:

1. **License change** (2019-2021): Switched from Apache 2.0 to AGPL-3.0
2. **Feature stripping** (early 2025): Removed the admin console/management GUI from the
   community edition (PR #3509), restricting it to the commercial AIStor product ($96K+/year)
3. **Maintenance mode**: MinIO's GitHub README now states the open-source project is in
   maintenance mode with no further feature additions
4. **Aggressive legal enforcement**: Built detection mechanisms into code to identify
   non-compliance; pursued legal action against users of earlier versions

### RustFS Advantages

| Aspect | MinIO | RustFS |
|--------|-------|--------|
| License | AGPL-3.0 | Apache 2.0 |
| Language | Go (GC) | Rust (no GC, ownership model) |
| Project status | Maintenance mode | Active development |
| Admin UI | Stripped from community edition | Included |
| Small object perf | Baseline | 2.3x faster (4KB payloads) |
| Architecture | Decentralized metadata | Decentralized metadata |
| Ease of use | High | High |

## S3 Compatibility

RustFS implements the S3 API and supports:
- Bucket operations (create, delete, list, versioning)
- Object operations (PUT, GET, DELETE, multipart upload)
- Server-side encryption
- Object versioning
- WORM compliance / object lock
- Lifecycle management
- Bucket replication
- Erasure coding
- Read-after-write consistency

### Known S3 Compatibility Gaps

Several issues remain open:
- **ETag handling**: Strict RFC enforcement breaks compatibility with AWS S3 clients that
  send unquoted ETags (issue #1458)
- **Object Lock when disabled**: GetObjectLockConfiguration causes lag when Object Lock is
  not enabled on a bucket (issue #771)
- **ACL support incomplete**: Uploads with ACL headers (e.g., `public-read`) return
  InvalidArgument; removing ACL makes uploads succeed (issue #928)

## Performance

- **Small objects (4KB):** RustFS is 2.3x faster than MinIO
- **Large objects (20MB, 4-node cluster):** MinIO still leads at ~53 Gbps throughput with
  24ms TTFB vs RustFS at ~23 Gbps with 260ms TTFB
- **Write performance:** Comparable between both systems
- **Claimed maximums:** Up to 323 GB/s read, 183 GB/s write (from RustFS docs)

## Kubernetes Deployment

- **Helm chart:** Available at `rustfs/helm` GitHub repo and on ArtifactHub
- **Deployment modes:** Standalone (single pod) and Distributed (4x4 PVC or 16x1 PVC)
- **Values config:** `helm/rustfs/values.yaml` controls mode selection
- **Container:** Runs as non-root user `rustfs` (UID 10001)
- **Observability:** Docker Compose profiles for Grafana, Prometheus, Jaeger

## Air-Gap Suitability Assessment

### Favorable

- **Single static binary** (Rust) -- no runtime dependencies, no GC pauses
- **Apache 2.0 license** -- no AGPL compliance concerns for disconnected/modified deployments
- **OCI images on Docker Hub and GHCR** -- can be mirrored to internal registries
- **Helm chart available** -- standard K8s deployment mechanism compatible with Zarf
- **Multi-arch** (amd64 + arm64) -- covers common air-gap hardware targets

### Concerns

- **Alpha status**: Still at 1.0.0-alpha; distributed mode not yet officially released
- **S3 API gaps**: Known compatibility issues with standard S3 clients may affect tooling
  that expects full S3 behavior
- **Limited production track record**: Independent evaluations (e.g., Milvus team) recommend
  non-production use only at this stage
- **Operational maturity**: Backup/restore, cross-region replication, and rolling upgrades
  may be incomplete
- **No specific air-gap documentation** exists in the RustFS docs

## Recommendation

RustFS is a promising Apache 2.0 alternative to MinIO, especially given MinIO's shift to
maintenance mode and aggressive commercialization. For the signals-360 project:

- **Development/testing:** RustFS is suitable today as a local S3 backend for dev workflows
- **Production air-gap:** Not yet recommended. Wait for a stable 1.0 release and resolution
  of the known S3 compatibility issues. Plan for a proof-of-concept with explicit rollback
  to MinIO (or SeaweedFS/Garage as other alternatives)
- **Zarf packaging:** The Helm chart + OCI image approach is compatible with Zarf's air-gap
  packaging model, so integration should be straightforward once RustFS stabilizes

Track the project at <https://github.com/rustfs/rustfs/releases> for GA readiness.
