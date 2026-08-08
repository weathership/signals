# Impala catalogd JNI SEGV — root cause and fix

## Symptom
`catalogd` died ~0.7s after start with:
```
SIGSEGV in JNIHandles::resolve_impl / jni_GetStaticMethodID
# null jobject (or "Bad global or local ref" with -Xcheck:jni)
```

## Root cause chain
1. process-compose put `config/impala` on `CLASSPATH` (includes `log4j.properties`).
2. That log4j config uses `org.apache.impala.util.GlogAppender`.
3. `JniUtil::InitLibhdfs()` → `hdfsConnect("default",0)` → libhdfs `JNI_CreateJavaVM`.
4. During Hadoop `FileSystem` / log4j static init, log4j loads **GlogAppender before Impala native logging JNI is ready**.
5. Appender / class init throws; libhdfs `printExceptionAndFree` calls `ExceptionUtils.getRootCauseMessage` via JNI.
6. Exception formatting path hits `GetStaticMethodID` with a bad/null class ref → SEGV (unchecked JNI).

Minimal repro (standalone `hdfsConnect` with same CLASSPATH) reproduced the SEGV.
With log4j disabled / ConsoleAppender-only conf, `hdfsConnect` returned success.

## Secondary issues (still worth cleaning)
- **`LD_PRELOAD=libjsig` during shell setup** breaks child `/bin/sh` (Nix libdl vs host glibc).
  `GetJavaMajorVersion()` → `java -version` fails → defaults to Java 8 → skips `--add-opens`.
  Fix: set `IMPALA_LIBJSIG` during setup; export `LD_PRELOAD` only on final daemon `exec`.
  Residual: once catalogd itself has `LD_PRELOAD=jsig`, in-process `popen` still inherits it.
  Workable with `--java_weigher=sizeof`; full fix is bwrap-bind nix `sh` over `/bin/sh` or clear preload in `RunShellProcess`.

## Fix landed
1. `config/impala/hadoop-conf/` — site XMLs + **bootstrap** `log4j.properties` (ConsoleAppender only).
2. `devenv.nix` catalogd/impalad: `CLASSPATH=$PWD/config/impala/hadoop-conf:...` (not whole `config/impala`).
3. `LD_PRELOAD=libjsig` only on final `exec`, not during config/classpath shell phase.
4. Comment on root `config/impala/log4j.properties` (GlogAppender) explaining why it must stay off the early CP.

## Verification
```
CatalogService started on port: 26005
Webserver started
HMS-free mode: skipping HMS catalog reset
Finished resetMetadata request: INVALIDATE ALL
```

## Isolation notes
- No host multiarch / system JDK used as the fix.
- Headless jdk21 + package-classpath remain devenv-local.
