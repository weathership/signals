# just redeploy

K8s product refresh so YK `provided` can place work on resource-class
queues. Not `signals.target` (host). Not Metabase `just rebuild`.

Always: Metaflow, Airflow (`root.platform`), Eventing sink
(`yunikorn-eventing-platform`), sentinel ksvc (`root.internal.compute`).
Scale to 0 (and wait pods gone) → wait YK `applicationState` Completed /
404 (Completing still blocks; same `app-id` would reattach) → bootstrap.
Timeout fails the recipe.

Substrate (YK / Knative Serving / Eventing core): only if missing or
manifest hashes changed. Queue policy stays engine promote, not zarf
`queues.yaml`. No force/skip flags — `just redeploy` is the whole command.

```bash
just redeploy
```
