# Java Kudu SASL FQDN on loopback (04:46Z)

HS2 `SELECT count(*) FROM signals_dataproducts.gpu_metrics_tier0` = **80240**
(hours 496537–496540). Standalone `KuduClient.openTable` `OPEN_OK`.

Cause: `ConnectToCluster` rewrote the master HostAndPort to
`addr.getHostAddress()` (127.0.0.1 from `/etc/hosts`). GSSAPI then
requested `kudu/127.0.0.1`. Patch keeps the configured FQDN; `ServerInfo`
skips reverse-DNS on local addresses; `Negotiator` creates SaslClient
inside `Subject.callAs` (KUDU-2121 / Java 21). Shaded client copied over
`kudu-client-879a8f9e2.jar`. `krb5.conf` `dns_canonicalize_hostname=false`.

`CREATE VIEW gpu_metrics AS UNION ALL` still hits HMS
`getCurrentNotificationEventId` (HMS-free catalog has no view type).
Ad-hoc HS2 `UNION ALL` subquery works (double-counts closed hours while
they remain in Kudu). Do not DROP RANGE yet — FDW `gpu_metrics` is still
`kudu_scan` of tier0. FDW `impala_sql` still lacks HS2 GSSAPI.
