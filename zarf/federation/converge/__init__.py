"""signals-federation converge FSM (cybersec-pattern).

detect → remediate → re-detect → fixpoint over a tiered invariant catalog.
Layer A = transported artifacts (never auto-deleted).
Layer B = cluster deployment (rebuild from A).

Full engine port from cldr/cybersec zarf/converge/ as invariants are filled in.
"""

__version__ = "0.1.0-dev"
