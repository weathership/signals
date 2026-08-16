# NiFi

Apache NiFi provides data flow routing, transformation, and system mediation.

**Federation C2 is not NiFi.** The sentinel yield loop is a Signals-owned
C2 HTTP server plus `Engine/Yield` gRPC. NiFi+canvas is an optional later
K8s fielding for OTel wiring — not folded into signals-ui, not required
for YK to end a sentinel Application. See
[Sentinel Applications and Yield](../architecture/sentinel-yield.md).
