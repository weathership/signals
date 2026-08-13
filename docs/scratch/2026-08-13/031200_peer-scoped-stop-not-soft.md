# Peer-scoped stop (not "soft stop")

**Date:** 2026-08-13

"Soft stop" was misleading: the intent was co-tenant-safe full unit shutdown
(this peer's engine + workers), never host-wide teardown that kills siblings.

Preferred terms: peer-scoped stop, unit stop, lease-safe stop.

See peer-integration.md § Unit stop: peer-scoped, not "soft".
