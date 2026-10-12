# signals.target recycle

Complete recycle through `scripts/systemd_target_refresh.sh` on
2026-10-12 00:49–00:52 UTC. The foundation reached `inactive` before
`systemctl start signals.target`. All 11 enabled members took a new
ActiveEnterTimestamp. The refresh verify passed: every member active,
Airflow :30800, YuniKorn :30080, Metaflow :30180, Engine/Status for
signals, aegir, atelier, gaius, hermes, and metabase, Hermes
dashboard :9119, Gaius UI :9890, and a fresh warehouse ingest.

A second `signals-ready` against Postgres :5455 was READY (fails=0
warns=0). `lattice-ci` passed 7 peers and skipped synth, which is not
a target member. Semantica answered Status and was not part of this
target.

Thinking is healthy (`Qwen/Qwen3.8-27B` on :8081, GPUs 0–3). GPUs 4
and 5 are free and `/tmp/zndx-gpu-leases/` is empty. The Hermes moshi
supervisor is up on :5081 and imports signals-plugins `540600a`. The
moshi worker was not placed. Loaded trees: Gaius `8744576`, Signals
`b7bdbd9`, signals-engine `b5afeba`.

The recycle stopped Metaflow run 13713 task 61593 and the CLT worker
that had been on GPU 4. Decisions replicas were not started.
