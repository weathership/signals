# Impala kinit is one shot

`scripts/impala_krb_renew.sh` now exits after a single `signals_impala_kinit`.
Airflow DAG `gaius_impala_krb_renew` is the schedule. `processes.impala-krb-renew`
is gone. The user unit `signals-impala-krb-renew.service` is stopped; it was
a loop with no place in the lab schedule.
