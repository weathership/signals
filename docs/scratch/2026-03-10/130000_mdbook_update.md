# mdbook Documentation Update

Updated the full mdbook documentation to cover infrastructure scaffold and BDD scenarios.

## Changes

### New Sections
- **Scenarios** (8 pages) — overview, S01-S06 scenario docs, test infrastructure
- **Infrastructure** (6 pages) — overview, OpenTofu, Ansible, Zarf, Tilt, OPA policies

### Updated Pages
- **SUMMARY.md** — reorganized with Scenarios and Infrastructure sections; removed AWS/Air-Gap subpages under Architecture (consolidated into Deployment Modes)
- **introduction.md** — added scenario table and documentation structure links
- **architecture/overview.md** — added architecture layers diagram and design principles
- **architecture/grpc-engine.md** — added responsibilities, service architecture, health checks, deployment modes
- **architecture/wasm-terminal.md** — added design rationale, WASM toolchain table, layout diagram
- **architecture/visualization.md** — added agent-mediated flow, resolution autoscaling, persona table, MLOps
- **architecture/data-flow.md** — added instruction/response path diagrams, data source tables
- **architecture/deployment.md** — complete rewrite: 4 deployment modes with commands, air-gap variant
- **operations/overview.md** — added quick reference commands
- **operations/devenv.md** — added k8s:* and aws:* task references, tooling table, BDD testing
- **reference/roadmap.md** — added current state and tier table

### Removed Pages
- `architecture/aws.md` — consolidated into deployment.md
- `architecture/airgap.md` — consolidated into deployment.md

## Stats
- 40 HTML pages generated
- Clean build, no errors or warnings
- All internal links verified
