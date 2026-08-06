# Impala BE rebuild against jdk21_headless

## Done
- `impala:build` pins `pkgs.jdk21_headless` before cmake/link
- Reconfigure when CMakeCache had full GUI OpenJDK `JAVA_JVM_LIBRARY`
- Rebuild succeeded; impalad RUNPATH:

```
[openjdk-headless-21.0.10+7/.../lib/server : toolchain kudu debug/lib]
```

- CMakeCache: `JAVA_JVM_LIBRARY=.../openjdk-headless-21.0.10+7/.../libjvm.so`

## Runtime still failing
hs_err: SIGSEGV in `JNIHandles::resolve_impl` / `jni_GetStaticMethodID` with **null jobject**
(~0.7s after start, after OpenSSL init + JVM boot).

Likely null `jclass` from failed FindClass (classpath / libhdfs InitLibhdfs order),
not missing libjvm path. Headless + rebuild fixed linking; remaining is JNI class load
during `JniUtil::InitLibhdfs()` / `JniUtil::Init()`.

## Next
1. Capture ExceptionDescribe on FindClass failure (or run with `-Xcheck:jni`)
2. Ensure `CLASSPATH` from `set-classpath.sh` is visible to CreateJavaVM (libhdfs)
3. HMS-free: evaluate whether libhdfs init can be deferred/skipped
4. bwrap bind nix bash over `/bin/sh` for `java -version` shell-outs (glibc pollution via LD_PRELOAD jsig)
