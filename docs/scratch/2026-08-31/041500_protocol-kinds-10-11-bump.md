# signals-protocol bump: kinds COGNITION(10) + CONTRIBUTIONS(11)

Submodule aeb8f6e -> 112a01b (pushed to origin/trunk by the gaius
session; both peers now pin the same head). Stubs regenerated per
scripts/gen_zndx_engine_py.sh into both trees.

- kind=COGNITION (10): a peer's cognition overview (CognitionHint).
  Signals has no cognition unit — unset hint is honest (documented in
  local_response; conformance-tested).
- kind=CONTRIBUTIONS (11): a peer's contributions by source and workflow
  (ContributionsHint, items stamped with their system of record).
  Signals answering is PENDING: Atlas+OpenLineage (Marquez sources —
  currently 0, fix planned), Metaflow, and Airflow will answer as each
  system of record comes online. Until then the unset hint is honest,
  never an error — gaius's collectors treat it as absence.

Live conformance: the RUNNING engine (pre-bump stubs) already answers
unknown kinds with project-only responses, so the lattice was conformant
before any restart; the bump makes the kinds nameable in code and tests.
test_engine_s2s: 13/13.

Note: gen_zndx_engine_py.sh runs `uv run`, which re-synced the project
.venv (dev venv). The LIVE engine runs from .devenv/state/venv and was
untouched — but the script deserves a venv-pinned invocation someday.
