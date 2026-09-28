# Impala Kudu ticket, 2026-09-28

The warehouse flush was not a network fault. catalogd and impalad have been up
since 2026-09-19. Their Kudu Java client re-reads `/tmp/krb5cc_impala` and does
not log in from the keytab. That cache was issued at process start, expired
2026-09-20 14:27, and its renew window closed 2026-09-26. The `signals@` ticket
was valid the whole time and is the wrong credential.

`kinit -kt` of `impala/tinybox.dev.vista.zndx.org` into that cache was enough.
impalad logged `Successfully refreshed Kerberos credentials from ticket cache`
at 07:09:41 UTC. No daemon was restarted. The voice engine was not touched.

Today's `signal_tier0` range (`497376 <= VALUES < 497400`, 2026-09-28) had
never been added, because the ALTER could not authenticate at midnight. ALTER
after the refresh did add `497376–497400` and `497400–497424`. Impala then
reported failure while reloading the table through Hive Metastore, which is
not running in this HMS-free lab. The ranges are present; SHOW confirmed them.
Warehouse ingest resumed (ticks climbing, six GPUs) at 07:16 UTC.

`scripts/impala_krb_renew.sh` re-kinits the cache every 8h. A user unit
`signals-impala-krb-renew.service` is running now. `processes.impala-krb-renew`
picks the same script up on the next signals devenv start. The running daemon
does not know about that process until then.
