# Impala follow-ups: bwrap + jsig + Java 21 add-opens

## Landed
1. **`impala_run` helper** in `devenv.nix`: bubblewrap binds Nix `bash` over `/bin/sh` and `/bin/bash`, then runs `ld-linux --library-path` + daemon.
2. **`LD_PRELOAD=libjsig`** only inside `impala_run` (not shell setup).
3. **Pre-seed Java 21 `--add-opens`** via `impalaJdk21AddOpens` on catalogd/impalad `JAVA_TOOL_OPTIONS`.
4. **Schema init** uses `psql -h 127.0.0.1 -p 5455` (TCP; no unix-socket race).

## Verified
- No more `sh: GLIBC_2.36 not found` on catalogd ERROR.
- No `Unable to determine Java version (default to 8)` — GetJavaMajorVersion works under bwrap.
- Impala itself appends full sizeof add-opens (proves version ≥ 9 detection).
- catalogd / impalad / HS2 / statestore / ranger / kudu ready under process-compose.

## Residual (harmless)
- Impala's own add-opens list still includes `jdk.internal.util.jar` (not in java.base on this OpenJDK) → one WARNING line.
- Bootstrap log4j remains ConsoleAppender; GlogAppender stays off early CP (post-JNI native logger is a later optional).
