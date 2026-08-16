# Engine unit, /readyz Status, federation promote

## /readyz name

Kept. Kubernetes/Google probe pair with `/healthz`: liveness vs readiness.
Not a product route. devenv, `signals-ready`, and peer-contract already use it.

## What landed

1. **Unit** — `infra/systemd/signals-engine.service` (oneshot, After=ready).
   `signals.target` Wants the engine. Installer foundation list includes it.
   devenv `processes.signals-engine` before signals-ui.
2. **REST leak** — `/applications` and `/api/engine/v1/applications` use
   `ListQueueApplications`. `/readyz` is `Engine/Status` with
   `capability=scheduler` healthy. `SIGNALS_UI_ALLOW_NO_YK=1` still skips
   Status for chrome-only lab.
3. **Promote** — `config/scheduler/federation-queues.yaml` is the sketched
   `root.{default,aegir,atelier,gaius,signals,hermes}` policy. Live pass
   (2026-08-14): write-scratch → dry-run (`yunikorn-configs` server dry-run)
   → apply `archive=federation-2026-08-14` `applied=True`. Live tree has
   all six leaves; six apps on `root.default`.

## Not this cut

CLI/MCP `GetDashboard`, leftover `/api/yk/ws/v1/*` cleanup, TLS.
