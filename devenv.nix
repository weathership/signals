{ pkgs, lib, config, inputs, ... }:

let
  # Shared native-lib path for Impala processes (Linux only).
  # Exec via: ld-linux --library-path "$IMPALA_LIBPATH" <daemon>
  # WITHOUT exporting LD_LIBRARY_PATH (child /bin/sh must not see Nix libc).
  #
  # Isolation rules (no host multiarch, no system JDK):
  # - glibc/openssl/krb5/sasl from pkgs
  # - JAVA_HOME from languages.java / pkgs.jdk21 (pinned before impala-config)
  # - JDK RUNPATH dirs pulled from the java binary (fontconfig, cups, …)
  # - Toolchain Kudu client still needs libsasl2.so.2; provide a devenv-local
  #   soname shim → Nix libsasl2.so.3 under .devenv/impala/lib (not /lib/…)
  # - Toolchain gcc lib64 for libstdc++ after security libs (libcrypto order)
  # Darwin: never forced (mkIf isLinux on processes).
  # Headless: ~8 NEEDED on libjvm vs ~15 for full JDK (no gtk/cups/X11).
  # Full GUI jdk pulls host-incompatible transitive deps into catalogd JNI.
  # Build and runtime must share this — BE RUNPATH is baked at link time.
  impalaJdkHome =
    if pkgs.stdenv.isLinux then "${pkgs.jdk21_headless.home}" else "";

  # Pin JAVA_HOME for Impala build + process-compose (same store path).
  impalaJdkEnv = ''
    export JAVA_HOME="${impalaJdkHome}"
    if [ -x "$JAVA_HOME/lib/openjdk/bin/java" ]; then
      export JAVA_HOME="$JAVA_HOME/lib/openjdk"
    fi
    if [ ! -x "$JAVA_HOME/bin/java" ] || [ ! -x "$JAVA_HOME/bin/javac" ]; then
      echo "ERROR: Impala requires jdk21_headless (java+javac): $JAVA_HOME"
      exit 1
    fi
    export PATH="$JAVA_HOME/bin:$PATH"
    export JAVA="$JAVA_HOME/bin/java"
    echo "Impala JAVA_HOME=$JAVA_HOME (jdk21_headless)"
    java -version 2>&1 | head -1
  '';

  # Nix libstdc++ for both BE and JVM (never pull toolchain/kudu's bundled one).
  impalaStdcxxLib = "${pkgs.stdenv.cc.cc.lib}/lib";

  impalaLdLibraryPath = ''
    NIX_GLIBC="${pkgs.glibc}/lib"
    NIX_KRB5="${pkgs.krb5.lib}/lib"
    NIX_SASL="${pkgs.cyrus_sasl.out}/lib"
    NIX_SSL="${pkgs.openssl.out}/lib"
    NIX_STDCXX="${impalaStdcxxLib}"
    KUDU_LIB_SRC="$IMPALA_TOOLCHAIN_PACKAGES_HOME/kudu-''${IMPALA_KUDU_VERSION:-879a8f9e2}/debug/lib"
    if [ ! -d "$KUDU_LIB_SRC" ]; then
      KUDU_LIB_SRC="$IMPALA_TOOLCHAIN_PACKAGES_HOME/kudu-''${IMPALA_KUDU_VERSION:-879a8f9e2}/release/lib"
    fi

    # Pin headless devenv JDK (override host detection in impala-config.sh)
    ${impalaJdkEnv}

    # .devenv shims only (no host /lib): sasl so.2 for toolchain kudu + kudu client
    # alone (do NOT add whole kudu/lib — it ships a conflicting libstdc++.so.6).
    SIG_IMPALA_LIB="$PWD/.devenv/impala/lib"
    mkdir -p "$SIG_IMPALA_LIB"
    ln -sfn "$NIX_SASL/libsasl2.so.3" "$SIG_IMPALA_LIB/libsasl2.so.2"
    for _k in libkudu_client.so libkudu_client.so.0 libkudu_client.so.0.1.0; do
      if [ -e "$KUDU_LIB_SRC/$_k" ]; then
        ln -sfn "$KUDU_LIB_SRC/$_k" "$SIG_IMPALA_LIB/$_k"
      fi
    done

    # libjsig path only — do NOT export LD_PRELOAD here.
    # Exporting libjsig during shell setup breaks child /bin/sh (Nix libdl vs host
    # glibc: GLIBC_2.36 / GLIBC_ABI_DT_RELR), which makes GetJavaMajorVersion fail
    # and skips Java 21 --add-opens. Apply LD_PRELOAD only on the final exec line.
    export IMPALA_LIBJSIG=$(find "$JAVA_HOME" -name libjsig.so 2>/dev/null | head -1 || true)
    unset LD_PRELOAD

    JAVA_RP=""
    if command -v readelf >/dev/null 2>&1; then
      JAVA_RP=$(readelf -d "$JAVA_HOME/bin/java" 2>/dev/null \
        | sed -n 's/.*Library r\(un\)\?path: \[\(.*\)\]/\2/p' | tr -d '\n')
    fi
    JAVA_LIB="$JAVA_HOME/lib/server:$JAVA_HOME/lib"
    [ -d "$JAVA_HOME/lib/jli" ] && JAVA_LIB="$JAVA_LIB:$JAVA_HOME/lib/jli"

    # BE shared natives for JNI System.load fallback (NativeLibUtil):
    # libloggingsupport.so (GlogAppender → NativeLogger) and libfesupport.so.
    # Primary path is RegisterNatives in InitJvmLoggingSupport; this covers
    # UnsatisfiedLinkError reload and keeps java.library.path complete.
    IMPALA_BE_UTIL="$IMPALA_HOME/be/build/latest/util"
    IMPALA_BE_SVC="$IMPALA_HOME/be/build/latest/service"
    HADOOP_NATIVE=$(ls -d "$IMPALA_HOME"/toolchain/cdp_components-*/hadoop-*/lib/native 2>/dev/null | head -1 || true)
    export IMPALA_JAVA_LIBRARY_PATH="$IMPALA_BE_UTIL:$IMPALA_BE_SVC''${HADOOP_NATIVE:+:$HADOOP_NATIVE}"

    # Order: glibc → security → nix libstdc++ → shims → be natives → jdk → jdk runpath
    # (never toolchain gcc lib64 first: its libcrypto breaks OPENSSL_3.4)
    export IMPALA_LIBPATH="$NIX_GLIBC:$NIX_SSL:$NIX_KRB5:$NIX_SASL:$NIX_STDCXX:$SIG_IMPALA_LIB:$IMPALA_BE_UTIL:$IMPALA_BE_SVC:$JAVA_LIB''${JAVA_RP:+:$JAVA_RP}"
    unset LD_LIBRARY_PATH
    export IMPALA_LD_LINUX="${pkgs.glibc}/lib/ld-linux-x86-64.so.2"
  '';

  # JVM flags for HMS-free catalog mode
  hmsFreeJavaOpts = builtins.concatStringsSep " " [
    "-Dsignals.hms_free_mode=true"
    "-Dsignals.catalog.jdbc_url=jdbc:postgresql://localhost:5455/signals_catalog"
    "-Dsignals.kudu.master_addresses=127.0.0.1:7051"
  ];

  # Java 21 --add-opens Impala would set when GetJavaMajorVersion works (sizeof weigher).
  # Pre-seed so a failed java -version shell-out cannot skip module opens.
  # Omits jdk.internal.util.jar (not in java.base on this OpenJDK → warning-only).
  impalaJdk21AddOpens = builtins.concatStringsSep " " [
    "--add-opens=java.base/java.lang=ALL-UNNAMED"
    "--add-opens=java.base/java.nio=ALL-UNNAMED"
    "--add-opens=java.base/java.util.regex=ALL-UNNAMED"
    "--add-opens=java.base/sun.nio.ch=ALL-UNNAMED"
    "--add-opens=java.base/java.io=ALL-UNNAMED"
    "--add-opens=java.base/java.lang.invoke=ALL-UNNAMED"
    "--add-opens=java.base/java.lang.module=ALL-UNNAMED"
    "--add-opens=java.base/java.lang.ref=ALL-UNNAMED"
    "--add-opens=java.base/java.lang.reflect=ALL-UNNAMED"
    "--add-opens=java.base/java.net=ALL-UNNAMED"
    "--add-opens=java.base/java.nio.charset=ALL-UNNAMED"
    "--add-opens=java.base/java.nio.file.attribute=ALL-UNNAMED"
    "--add-opens=java.base/java.security=ALL-UNNAMED"
    "--add-opens=java.base/java.util.concurrent.locks=ALL-UNNAMED"
    "--add-opens=java.base/java.util.concurrent=ALL-UNNAMED"
    "--add-opens=java.base/java.util.jar=ALL-UNNAMED"
    "--add-opens=java.base/java.util.zip=ALL-UNNAMED"
    "--add-opens=java.base/java.util=ALL-UNNAMED"
    "--add-opens=java.base/jdk.internal.loader=ALL-UNNAMED"
    "--add-opens=java.base/jdk.internal.math=ALL-UNNAMED"
    "--add-opens=java.base/jdk.internal.module=ALL-UNNAMED"
    "--add-opens=java.base/jdk.internal.perf=ALL-UNNAMED"
    "--add-opens=java.base/jdk.internal.platform=ALL-UNNAMED"
    "--add-opens=java.base/jdk.internal.ref=ALL-UNNAMED"
    "--add-opens=java.base/jdk.internal.reflect=ALL-UNNAMED"
    "--add-opens=java.base/sun.net.www.protocol.jar=ALL-UNNAMED"
    "--add-opens=java.base/sun.nio.fs=ALL-UNNAMED"
    "--add-opens=jdk.dynalink/jdk.dynalink.beans=ALL-UNNAMED"
    "--add-opens=jdk.dynalink/jdk.dynalink.linker.support=ALL-UNNAMED"
    "--add-opens=jdk.dynalink/jdk.dynalink.linker=ALL-UNNAMED"
    "--add-opens=jdk.dynalink/jdk.dynalink.support=ALL-UNNAMED"
    "--add-opens=jdk.dynalink/jdk.dynalink=ALL-UNNAMED"
    "--add-opens=jdk.management.jfr/jdk.management.jfr=ALL-UNNAMED"
    "--add-opens=jdk.management/com.sun.management.internal=ALL-UNNAMED"
  ];

  # Helper for final Impala daemon launch (Linux).
  # bwrap overlays Nix bash on /bin/sh so popen("java -version") children inherit
  # LD_PRELOAD=libjsig without mixing Nix libdl into host glibc /bin/sh.
  # ld-linux --library-path keeps LD_LIBRARY_PATH unset for the process tree.
  # Usage: impala_run /path/to/catalogd --flag ...
  impalaRunFn = ''
    impala_run() {
      local _bin="$1"
      shift
      local _bwrap="${pkgs.bubblewrap}/bin/bwrap"
      local _nix_sh="${pkgs.bashInteractive}/bin/bash"
      if [ ! -x "$_bwrap" ]; then
        echo "ERROR: bubblewrap missing (devenv packages): $_bwrap"; exit 1
      fi
      if [ ! -x "$_nix_sh" ]; then
        echo "ERROR: nix bash missing: $_nix_sh"; exit 1
      fi
      if [ ! -x "$_bin" ]; then
        echo "ERROR: Impala binary missing: $_bin"; exit 1
      fi
      if [ -n "''${IMPALA_LIBJSIG:-}" ]; then
        export LD_PRELOAD="$IMPALA_LIBJSIG"
      fi
      exec "$_bwrap" \
        --bind / / \
        --dev-bind /dev /dev \
        --proc /proc \
        --share-net \
        --die-with-parent \
        --ro-bind "$_nix_sh" /bin/sh \
        --ro-bind "$_nix_sh" /bin/bash \
        -- \
        "$IMPALA_LD_LINUX" --library-path "$IMPALA_LIBPATH" \
        "$_bin" "$@"
    }
  '';

  # Portable Kerberos/SASL/OpenSSL paths for ASF C++ links under Nix (Impala, Kudu).
  # FindKerberos registers full-path gssapi_krb5; this still supplies -L / find_library.
  asfNativeLinkEnv = ''
    export SIG_KRB5_LIB="${pkgs.krb5.lib}/lib"
    export SIG_KRB5_INC="${pkgs.krb5.dev}/include"
    export SIG_SASL_LIB="${pkgs.cyrus_sasl.out}/lib"
    export SIG_SASL_INC="${pkgs.cyrus_sasl.dev}/include"
    export SIG_SSL_LIB="${pkgs.openssl.out}/lib"
    export SIG_SSL_INC="${pkgs.openssl.dev}/include"
    # shellcheck source=/dev/null
    . "$PWD/config/asf/native-link-env.sh"
  '';
in
{
  dotenv.enable = true;

  # ── Packages ───────────────────────────────────────────────────────────────
  packages = with pkgs; [
    # Core
    git
    gh
    jq
    just

    # Kerberos / Security
    krb5
    cyrus_sasl
    openssl

    # ASF build dependencies (Kudu, Impala, Ranger) — prefer these over system packages
    cmake
    ninja
    gcc
    gnumake
    autoconf
    automake
    libtool
    pkg-config
    protobuf
    flatbuffers
    zlib  # needed by numpy C extensions in pip wheels
    curl
    python3
    jdk11  # Ranger only (interim Nashorn); plan: ditch Nashorn → modern JDKs
    jdk17  # Kudu Java / Gradle wrapper (not system)
    jdk21_headless  # Impala catalogd/impalad JNI (no gtk/cups; devenv-only)
    bubblewrap  # optional: bind nix sh over /bin/sh for Impala child processes
    # Kudu thirdparty / common
    bison
    flex
    krb5.dev
    openssl.dev
    zlib.dev
    snappy
    cyrus_sasl.dev
    libxcrypt  # crypt.h for LLVM 11 compiler-rt (sanitizer_platform_limits_posix)
    # Kubernetes / Orchestration
    kubectl
    kubernetes-helm
    tilt
    k9s
    k3d
    podman

    # Infrastructure / Deployment
    awscli2
    opentofu
    ansible
    zarf
    conftest
    cloudflared

    # gRPC
    grpcurl

    # WASM (Ghostty terminal component)
    wasmtime
    wasm-pack
    wasm-bindgen-cli
    binaryen

    # Database
    dbmate
    # NOTE: do NOT add pkgs.thrift / pkgs.boost here. They pollute
    # CMAKE_INCLUDE_PATH / PKG_CONFIG_PATH and Impala BE then compiles against
    # Nix thrift/boost instead of the Impala toolchain. impala_fdw:build pins
    # ${pkgs.thrift} and ${pkgs.boost.dev} explicitly for that extension only.
    # Documentation
    mdbook
    mdbook-d2
    mdbook-katex
    mdbook-mermaid
    d2
    graphviz

    # Utilities
    presenterm
    imagemagick
    wget
  ];

  # ── Languages ──────────────────────────────────────────────────────────────
  languages.rust.enable = true;

  languages.python = {
    enable = true;
    package = pkgs.python312;
    uv.enable = true;
  };

  languages.java = {
    enable = true;
    jdk.package = pkgs.jdk21;
    maven.enable = true;
  };

  languages.javascript = { enable = true; };
  languages.typescript = { enable = true; };

  # ── Environment ────────────────────────────────────────────────────────────
  # Kerberos: realm includes env segment — DEV.VISTA.ZNDX.ORG
  # ({ENV}.{LOCATION}.ZNDX.ORG). Host FQDN tinybox.dev.vista.zndx.org.
  # User principal signals@DEV.VISTA.ZNDX.ORG → PG role "signals".
  # KDC stays on loopback :8848.
  env = {
    KRB5_REALM = "DEV.VISTA.ZNDX.ORG";
    KRB5_KDC_PORT = "8848";
    SIGNALS_KRB_ENV = "dev";
    SIGNALS_KRB_LOCATION = "vista";
    SIGNALS_KRB_HOST = "tinybox.dev.vista.zndx.org";
  };

  # ── PostgreSQL ─────────────────────────────────────────────────────────────
  services.postgres = {
    enable = true;
    package = pkgs.postgresql_16;
    extensions = extensions: [
      extensions.age
      extensions.pg_cron
    ];
    port = 5455;
    settings = {
      listen_addresses = lib.mkForce "127.0.0.1";
      shared_preload_libraries = "age,pg_cron";
      "cron.database_name" = "signals";
    };
    initialDatabases = [
      {
        name = "signals";
        initialSQL = ''
          CREATE EXTENSION IF NOT EXISTS age;
          LOAD 'age';
          SET search_path = ag_catalog, "$user", public;
          CREATE EXTENSION IF NOT EXISTS pg_cron;
          CREATE EXTENSION IF NOT EXISTS pg_trgm;
        '';
      }
      { name = "polaris"; }
      { name = "signals_catalog"; }
      { name = "ranger"; }
    ];
  };

  # ── KDC Process ────────────────────────────────────────────────────────────
  processes.kdc = {
    exec = ''
      # Initialize KDC if needed
      bash scripts/kdc-init.sh

      KDC_DIR="$PWD/.devenv/kdc"

      echo "Starting KDC on 127.0.0.1:''${KRB5_KDC_PORT:-8848}..."
      exec env \
        KRB5_CONFIG="$KDC_DIR/krb5.conf" \
        KRB5_KDC_PROFILE="$KDC_DIR/kdc.conf" \
        krb5kdc -n
    '';
    process-compose = {
      readiness_probe = {
        exec.command = "ss -uln | grep -q 8848";
        initial_delay_seconds = 1;
        period_seconds = 5;
        timeout_seconds = 2;
        success_threshold = 1;
        failure_threshold = 10;
      };
    };
  };

  # ── Atlas Process (AGE backend on signals PG; HTTP :21010 to coexist with aegir :21000) ──
  processes.atlas = {
    exec = ''
      ATLAS_DIR="$PWD/components/atlas"
      ATLAS_WEBAPP="$ATLAS_DIR/webapp/target/atlas-webapp-3.0.0-SNAPSHOT"
      ATLAS_CONF_SRC="$PWD/config/atlas"
      ATLAS_HOME="$PWD/.devenv/atlas"
      PGPORT="''${PGPORT:-5455}"

      mkdir -p "$ATLAS_HOME/data" "$ATLAS_HOME/logs" "$ATLAS_HOME/conf"

      # Symlink models so AtlasTypeDefStoreInitializer finds bootstrap type definitions
      ln -sfn "$ATLAS_DIR/addons/models" "$ATLAS_HOME/models"

      # Materialize conf with live PG port + app role (Atlas does not interpolate env reliably)
      sed -e "s|localhost:[0-9]*/signals|localhost:$PGPORT/signals|" \
          -e "s|atlas.age.jdbc.user=.*|atlas.age.jdbc.user=signals|" \
          -e "s|atlas.age.jdbc.password=.*|atlas.age.jdbc.password=signals|" \
        "$ATLAS_CONF_SRC/atlas-application.properties" > "$ATLAS_HOME/conf/atlas-application.properties"
      cp -f "$ATLAS_CONF_SRC/users-credentials.properties" "$ATLAS_HOME/conf/" 2>/dev/null || true
      cp -f "$ATLAS_CONF_SRC/atlas-simple-authz-policy.json" "$ATLAS_HOME/conf/" 2>/dev/null || true

      if [ ! -d "$ATLAS_WEBAPP/WEB-INF" ]; then
        echo "Atlas webapp not built. Run: devenv tasks run atlas:build"
        exit 1
      fi

      # Hikari fail-fasts without retry — wait for Postgres
      for _i in $(seq 1 90); do
        pg_isready -h localhost -p "$PGPORT" -q && break
        sleep 1
      done

      echo "Starting Atlas on http://localhost:21010 (AGE -> signals DB, pg :$PGPORT)..."
      exec java \
        -Datlas.home="$ATLAS_HOME" \
        -Datlas.conf="$ATLAS_HOME/conf" \
        -Datlas.log.dir="$ATLAS_HOME/logs" \
        -Datlas.log.file=application \
        -Datlas.data="$ATLAS_HOME/data" \
        -Dlogback.configurationFile="$ATLAS_DIR/distro/src/conf/atlas-logback.xml" \
        -Datlas.graphdb.backend=org.apache.atlas.repository.graphdb.age.AtlasAgeGraphDatabase \
        -Djava.net.preferIPv4Stack=true \
        --add-opens java.base/java.lang=ALL-UNNAMED \
        --add-opens java.base/java.lang.reflect=ALL-UNNAMED \
        --add-opens java.base/java.io=ALL-UNNAMED \
        --add-opens java.base/java.net=ALL-UNNAMED \
        --add-opens java.base/java.util=ALL-UNNAMED \
        --add-opens java.base/java.util.concurrent=ALL-UNNAMED \
        --add-opens java.base/sun.nio.ch=ALL-UNNAMED \
        --add-opens java.base/sun.security.action=ALL-UNNAMED \
        --add-opens java.security.jgss/sun.security.krb5=ALL-UNNAMED \
        -server -Xmx1024m \
        -cp "$ATLAS_HOME/conf:$ATLAS_WEBAPP/WEB-INF/classes:$ATLAS_WEBAPP/WEB-INF/lib/*" \
        org.apache.atlas.Atlas \
        -app "$ATLAS_WEBAPP" \
        -port 21010
    '';
    process-compose = {
      depends_on = {
        postgres = { condition = "process_healthy"; };
      };
      readiness_probe = {
        exec.command = "curl -sf http://127.0.0.1:21010/api/atlas/admin/status";
        initial_delay_seconds = 10;
        period_seconds = 10;
        timeout_seconds = 5;
        success_threshold = 1;
        failure_threshold = 15;
      };
    };
  };

  # ── Ranger Admin (Postgres :5455/ranger; HTTP :6080) ─────────────────────
  # Requires: devenv tasks run ranger:install && ranger:setup (or process self-setup).
  processes.ranger-admin = {
    exec = ''
      RANGER_HOME="$PWD/.devenv/ranger"
      RANGER_ADMIN="$RANGER_HOME/admin"
      EWS="$RANGER_ADMIN/ews"
      PGPORT="''${PGPORT:-5455}"

      if [ ! -f "$EWS/ranger-admin-services.sh" ]; then
        echo "Ranger admin not installed under .devenv/ranger/admin."
        echo "Run: devenv tasks run ranger:install && devenv tasks run ranger:setup"
        exit 1
      fi

      # Wait for Postgres
      for _i in $(seq 1 90); do
        pg_isready -h localhost -p "$PGPORT" -q && break
        sleep 1
      done

      # JDK 11 for Ranger (interim Nashorn-era tree)
      export JAVA_HOME="${pkgs.jdk11}"
      if [ ! -x "$JAVA_HOME/bin/java" ] && [ -x "$JAVA_HOME/lib/openjdk/bin/java" ]; then
        export JAVA_HOME="$JAVA_HOME/lib/openjdk"
      fi
      export PATH="$JAVA_HOME/bin:$PATH"

      mkdir -p "$RANGER_HOME/logs" "$RANGER_HOME/run"
      export RANGER_ADMIN_LOG_DIR="$RANGER_HOME/logs"
      export RANGER_PID_DIR_PATH="$RANGER_HOME/run"

      # One-shot setup if conf not materialised
      if [ ! -f "$EWS/webapp/WEB-INF/classes/conf/ranger-admin-site.xml" ]; then
        echo "Ranger not set up yet; run: devenv tasks run ranger:setup"
        exit 1
      fi

      # Ensure JDBC driver on classpath (setup puts it in WEB-INF/lib)
      if [ -f "$RANGER_HOME/lib/postgresql.jar" ]; then
        cp -f "$RANGER_HOME/lib/postgresql.jar" "$EWS/webapp/WEB-INF/lib/" 2>/dev/null || true
      fi

      echo "Starting Ranger Admin on http://localhost:6080 (Postgres ranger DB, pg :$PGPORT)..."
      cd "$EWS"
      # Foreground EmbeddedServer (process-compose owns the process; not nohup)
      exec java -Dproc_rangeradmin \
        -XX:MetaspaceSize=100m -XX:MaxMetaspaceSize=200m -Xmx1g -Xms512m \
        -Duser.timezone=UTC \
        -Dlogback.configurationFile=file:$EWS/webapp/WEB-INF/classes/conf/logback.xml \
        -Dservername=rangeradmin \
        -Dlogdir="$RANGER_ADMIN_LOG_DIR" \
        -Dcatalina.base="$EWS" \
        -cp "$EWS/webapp/WEB-INF/classes/conf:$EWS/lib/*:$EWS/webapp/WEB-INF/lib/*:$EWS/ranger_jaas/*:$JAVA_HOME/lib/*" \
        org.apache.ranger.server.tomcat.EmbeddedServer
    '';
    process-compose = {
      depends_on = {
        postgres = { condition = "process_healthy"; };
      };
      readiness_probe = {
        exec.command = "curl -sf -o /dev/null -w '%{http_code}' http://127.0.0.1:6080/ | grep -qE '200|302|401|403'";
        initial_delay_seconds = 15;
        period_seconds = 10;
        timeout_seconds = 5;
        success_threshold = 1;
        failure_threshold = 18;
      };
    };
  };

  # ── Kudu Master Process ──────────────────────────────────────────────────
  # Kerberos (PR-K5a): set SIGNALS_KUDU_KERBEROS=1 to require RPC auth.
  # Needs scripts/kdc-init.sh (kudu/$SIGNALS_KRB_HOST keytab). Default off so
  # nosasl Impala/FDW keep working until K5b wires libkudu_client GSS.
  processes.kudu-master = {
    exec = ''
      KUDU_HOME="$PWD/.devenv/kudu"
      # Prefer submodule build; allow KUDU_BUILD override for emergency external trees
      KUDU_BUILD="''${KUDU_BUILD:-$PWD/components/kudu/build/latest}"
      KDC_DIR="$PWD/.devenv/kdc"
      KRB_HOST="''${SIGNALS_KRB_HOST:-tinybox.dev.vista.zndx.org}"
      KUDU_KEYTAB="''${SIGNALS_KUDU_KEYTAB:-$KDC_DIR/kudu.keytab}"

      if [ ! -f "$KUDU_BUILD/bin/kudu-master" ]; then
        echo "Kudu not built. Run: devenv tasks run kudu:build-cpp"
        exit 1
      fi

      mkdir -p "$KUDU_HOME/master/data" "$KUDU_HOME/master/wal" "$KUDU_HOME/master/logs"

      # Shared Kerberos args (empty when disabled)
      KUDU_AUTH_ARGS=()
      if [ "''${SIGNALS_KUDU_KERBEROS:-0}" = "1" ]; then
        if [ ! -f "$KUDU_KEYTAB" ]; then
          echo "ERROR: SIGNALS_KUDU_KERBEROS=1 but keytab missing: $KUDU_KEYTAB"
          echo "Run: devenv tasks run signals:kdc-init"
          exit 1
        fi
        if [ -f "$KDC_DIR/krb5.conf" ]; then
          export KRB5_CONFIG="$KDC_DIR/krb5.conf"
        fi
        # Lab: encrypt optional (loopback); auth required rejects anonymous clients.
        KUDU_RPC_AUTH="''${SIGNALS_KUDU_RPC_AUTH:-required}"
        KUDU_RPC_ENC="''${SIGNALS_KUDU_RPC_ENCRYPTION:-optional}"
        # Explicit SPN — do not use kudu/_HOST (expands to uname -n, often tinybox.lan)
        KUDU_SPN="kudu/$KRB_HOST"
        # Advertise hostname so clients request kudu/$KRB_HOST, not kudu/127.0.0.1
        # (bind stays loopback; $KRB_HOST must resolve to 127.0.0.1 in lab hosts)
        KUDU_RPC_BIND="127.0.0.1:7051"
        KUDU_RPC_ADVERTISE="$KRB_HOST:7051"
        KUDU_AUTH_ARGS=(
          --keytab_file="$KUDU_KEYTAB"
          --principal="$KUDU_SPN"
          --rpc_authentication="$KUDU_RPC_AUTH"
          --rpc_encryption="$KUDU_RPC_ENC"
          --allow_world_readable_credentials=true
          --rpc_advertised_addresses="$KUDU_RPC_ADVERTISE"
        )
        echo "Kudu Master Kerberos ON (auth=$KUDU_RPC_AUTH enc=$KUDU_RPC_ENC keytab=$KUDU_KEYTAB)"
        echo "  principal $KUDU_SPN bind=$KUDU_RPC_BIND advertise=$KUDU_RPC_ADVERTISE"
      else
        echo "Kudu Master Kerberos OFF (SIGNALS_KUDU_KERBEROS!=1) — nosasl clients OK"
        KUDU_RPC_BIND="127.0.0.1:7051"
      fi

      echo "Starting Kudu Master on $KUDU_RPC_BIND..."
      exec "$KUDU_BUILD/bin/kudu-master" \
        --fs_data_dirs="$KUDU_HOME/master/data" \
        --fs_wal_dir="$KUDU_HOME/master/wal" \
        --log_dir="$KUDU_HOME/master/logs" \
        --webserver_port=8051 \
        --rpc_bind_addresses="$KUDU_RPC_BIND" \
        --unlock_unsafe_flags \
        --default_num_replicas=1 \
        "''${KUDU_AUTH_ARGS[@]}"
    '';
    process-compose = {
      readiness_probe = {
        http_get = {
          host = "127.0.0.1";
          port = 8051;
          path = "/";
        };
        initial_delay_seconds = 2;
        period_seconds = 5;
        timeout_seconds = 5;
        success_threshold = 1;
        failure_threshold = 10;
      };
    };
  };

  # ── Kudu Tablet Server Process ───────────────────────────────────────────
  processes.kudu-tserver = {
    exec = ''
      KUDU_HOME="$PWD/.devenv/kudu"
      KUDU_BUILD="''${KUDU_BUILD:-$PWD/components/kudu/build/latest}"
      KDC_DIR="$PWD/.devenv/kdc"
      KRB_HOST="''${SIGNALS_KRB_HOST:-tinybox.dev.vista.zndx.org}"
      KUDU_KEYTAB="''${SIGNALS_KUDU_KEYTAB:-$KDC_DIR/kudu.keytab}"

      if [ ! -f "$KUDU_BUILD/bin/kudu-tserver" ]; then
        echo "Kudu not built. Run: devenv tasks run kudu:build-cpp"
        exit 1
      fi

      mkdir -p "$KUDU_HOME/tserver/data" "$KUDU_HOME/tserver/wal" "$KUDU_HOME/tserver/logs"

      KUDU_AUTH_ARGS=()
      # Master addrs for tserver: use SPN host when Kerberos so registration is consistent
      KUDU_MASTER_ADDRS="127.0.0.1:7051"
      KUDU_RPC_BIND="127.0.0.1:7050"
      if [ "''${SIGNALS_KUDU_KERBEROS:-0}" = "1" ]; then
        if [ ! -f "$KUDU_KEYTAB" ]; then
          echo "ERROR: SIGNALS_KUDU_KERBEROS=1 but keytab missing: $KUDU_KEYTAB"
          echo "Run: devenv tasks run signals:kdc-init"
          exit 1
        fi
        if [ -f "$KDC_DIR/krb5.conf" ]; then
          export KRB5_CONFIG="$KDC_DIR/krb5.conf"
        fi
        KUDU_RPC_AUTH="''${SIGNALS_KUDU_RPC_AUTH:-required}"
        KUDU_RPC_ENC="''${SIGNALS_KUDU_RPC_ENCRYPTION:-optional}"
        KUDU_SPN="kudu/$KRB_HOST"
        KUDU_MASTER_ADDRS="$KRB_HOST:7051"
        KUDU_RPC_ADVERTISE="$KRB_HOST:7050"
        KUDU_AUTH_ARGS=(
          --keytab_file="$KUDU_KEYTAB"
          --principal="$KUDU_SPN"
          --rpc_authentication="$KUDU_RPC_AUTH"
          --rpc_encryption="$KUDU_RPC_ENC"
          --allow_world_readable_credentials=true
          --rpc_advertised_addresses="$KUDU_RPC_ADVERTISE"
        )
        echo "Kudu TServer Kerberos ON (auth=$KUDU_RPC_AUTH principal=$KUDU_SPN advertise=$KUDU_RPC_ADVERTISE)"
      else
        echo "Kudu TServer Kerberos OFF (SIGNALS_KUDU_KERBEROS!=1)"
      fi

      echo "Starting Kudu Tablet Server..."
      exec "$KUDU_BUILD/bin/kudu-tserver" \
        --fs_data_dirs="$KUDU_HOME/tserver/data" \
        --fs_wal_dir="$KUDU_HOME/tserver/wal" \
        --log_dir="$KUDU_HOME/tserver/logs" \
        --tserver_master_addrs="$KUDU_MASTER_ADDRS" \
        --webserver_port=8050 \
        --rpc_bind_addresses="$KUDU_RPC_BIND" \
        --unlock_unsafe_flags \
        "''${KUDU_AUTH_ARGS[@]}"
    '';
    process-compose = {
      depends_on = {
        kudu-master = { condition = "process_healthy"; };
      };
      readiness_probe = {
        http_get = {
          host = "127.0.0.1";
          port = 8050;
          path = "/";
        };
        initial_delay_seconds = 2;
        period_seconds = 5;
        timeout_seconds = 5;
        success_threshold = 1;
        failure_threshold = 10;
      };
    };
  };

  # ── Impala Runtime Environment ────────────────────────────────────────
  # Impala binaries were built with toolchain GCC 10.4.0 but link against
  # Nix-provided SASL (glibc 2.42) and JVM. We use Nix's ld-linux as the
  # explicit interpreter so that Nix libraries (which need glibc 2.42) work
  # alongside system libraries (which only need glibc ≤2.35, backward-
  # compatible with 2.42). LD_LIBRARY_PATH ordering is critical: Nix glibc
  # must come FIRST so libc.so.6 resolves to glibc 2.42.
  #
  # The three impala-* processes are gated on isLinux: pkgs.glibc is
  # unavailable on Darwin, and Impala itself only runs on Linux x86_64.
  # mkIf with a false condition drops the entire submodule before its
  # contents (including ${pkgs.glibc} interpolations) are forced.

  # ── Impala Statestore Process ───────────────────────────────────────────
  processes.impala-statestore = lib.mkIf pkgs.stdenv.isLinux {
    exec = ''
      IMPALA_HOME="$PWD/components/impala"
      if [ ! -f "$IMPALA_HOME/be/build/latest/service/statestored" ]; then
        echo "Impala not built. Run: devenv tasks run impala:build"; exit 1
      fi
      cp -f "$PWD/config/impala/impala-config-local.sh" "$IMPALA_HOME/bin/impala-config-local.sh"
      # Pin JDK before impala-config (avoid host/system java detection)
      ${impalaLdLibraryPath}
      # shellcheck source=/dev/null
      source "$IMPALA_HOME/bin/impala-config.sh"
      # Re-apply libpath after config (impala-config may mutate env)
      ${impalaLdLibraryPath}

      mkdir -p "$PWD/.devenv/impala/statestore/logs"

      echo "Starting Impala Statestore on port 24000..."
      exec "$IMPALA_LD_LINUX" --library-path "$IMPALA_LIBPATH" \
        "$IMPALA_HOME/be/build/latest/service/statestored" \
        --state_store_port=24000 \
        --webserver_port=25010 \
        --log_dir="$PWD/.devenv/impala/statestore/logs" \
        --hostname=localhost
    '';
    process-compose = {
      readiness_probe = {
        http_get = {
          host = "127.0.0.1";
          port = 25010;
          path = "/";
        };
        initial_delay_seconds = 3;
        period_seconds = 5;
        timeout_seconds = 5;
        success_threshold = 1;
        failure_threshold = 10;
      };
    };
  };

  # ── Impala Catalog Server Process (HMS-free) ────────────────────────────
  processes.impala-catalogd = lib.mkIf pkgs.stdenv.isLinux {
    exec = ''
      IMPALA_HOME="$PWD/components/impala"
      if [ ! -f "$IMPALA_HOME/be/build/latest/service/catalogd" ]; then
        echo "Impala not built. Run: devenv tasks run impala:build"; exit 1
      fi
      cp -f "$PWD/config/impala/impala-config-local.sh" "$IMPALA_HOME/bin/impala-config-local.sh"
      # Pin devenv JDK + libpath before config/classpath
      ${impalaLdLibraryPath}
      # shellcheck source=/dev/null
      source "$IMPALA_HOME/bin/impala-config.sh"
      if [ ! -s "$IMPALA_HOME/java/impala-package/target/package-classpath.txt" ]; then
        echo "Impala FE package classpath missing. Run: devenv tasks run impala:build-fe"
        echo "(or full: devenv tasks run impala:build)"
        exit 1
      fi
      # shellcheck source=/dev/null
      . "$IMPALA_HOME/bin/set-classpath.sh"
      ${impalaLdLibraryPath}

      # Hadoop/Hive site XMLs + bootstrap log4j (ConsoleAppender).
      # Do not put config/impala/log4j.properties (GlogAppender) on the early
      # classpath: libhdfs CreateJavaVM loads log4j before Impala JNI natives
      # exist, and GlogAppender failure cascades into GetStaticMethodID SEGV.
      export CLASSPATH="$PWD/config/impala/hadoop-conf:$CLASSPATH"

      # Initialize catalog schema (idempotent). Use TCP host so we do not depend
      # on the devenv unix-socket path being present in $PGHOST / runtime dir.
      psql -h 127.0.0.1 -p 5455 -d signals_catalog -f "$PWD/config/impala/catalog_schema.sql"

      # HMS-free props + Java 21 module opens (pre-seed; Impala may append more).
      # Merge BE util/service into java.library.path for NativeLogger fallback load.
      export LIBHDFS_OPTS="''${LIBHDFS_OPTS:-} -Djava.library.path=$IMPALA_JAVA_LIBRARY_PATH"
      export JAVA_TOOL_OPTIONS="''${JAVA_TOOL_OPTIONS:-} ${hmsFreeJavaOpts} ${impalaJdk21AddOpens}"

      mkdir -p "$PWD/.devenv/impala/catalogd/logs"

      echo "Starting Impala Catalog Server on port 26000 (HMS-free)..."
      echo "JAVA_HOME=$JAVA_HOME LIBJSIG=''${IMPALA_LIBJSIG:-} JAVA_LIBRARY_PATH=$IMPALA_JAVA_LIBRARY_PATH"
      ${impalaRunFn}
      impala_run "$IMPALA_HOME/be/build/latest/service/catalogd" \
        --catalog_service_port=26000 \
        --state_store_subscriber_port=23020 \
        --state_store_host=localhost \
        --state_store_port=24000 \
        --webserver_port=25020 \
        --log_dir="$PWD/.devenv/impala/catalogd/logs" \
        --hostname=localhost \
        --kudu_master_hosts=127.0.0.1:7051 \
        --abort_on_config_error=false \
        --hms_event_polling_interval_s=0 \
        --java_weigher=sizeof
    '';
    process-compose = {
      depends_on = {
        impala-statestore = { condition = "process_healthy"; };
        kudu-tserver = { condition = "process_healthy"; };
        postgres = { condition = "process_healthy"; };
      };
      readiness_probe = {
        http_get = {
          host = "127.0.0.1";
          port = 25020;
          path = "/";
        };
        initial_delay_seconds = 5;
        period_seconds = 5;
        timeout_seconds = 5;
        success_threshold = 1;
        failure_threshold = 15;
      };
    };
  };

  # ── Impala Daemon Process (HMS-free) ────────────────────────────────────
  processes.impala-impalad = lib.mkIf pkgs.stdenv.isLinux {
    exec = ''
      IMPALA_HOME="$PWD/components/impala"
      if [ ! -f "$IMPALA_HOME/be/build/latest/service/impalad" ]; then
        echo "Impala not built. Run: devenv tasks run impala:build"; exit 1
      fi
      cp -f "$PWD/config/impala/impala-config-local.sh" "$IMPALA_HOME/bin/impala-config-local.sh"
      ${impalaLdLibraryPath}
      # shellcheck source=/dev/null
      source "$IMPALA_HOME/bin/impala-config.sh"
      if [ ! -s "$IMPALA_HOME/java/impala-package/target/package-classpath.txt" ]; then
        echo "Impala FE package classpath missing. Run: devenv tasks run impala:build-fe"
        echo "(or full: devenv tasks run impala:build)"
        exit 1
      fi
      # shellcheck source=/dev/null
      . "$IMPALA_HOME/bin/set-classpath.sh"
      ${impalaLdLibraryPath}

      # Same early-classpath rules as catalogd (hadoop-conf, not GlogAppender log4j)
      export CLASSPATH="$PWD/config/impala/hadoop-conf:$CLASSPATH"

      export LIBHDFS_OPTS="''${LIBHDFS_OPTS:-} -Djava.library.path=$IMPALA_JAVA_LIBRARY_PATH"
      export JAVA_TOOL_OPTIONS="''${JAVA_TOOL_OPTIONS:-} ${hmsFreeJavaOpts} ${impalaJdk21AddOpens}"

      mkdir -p "$PWD/.devenv/impala/impalad/logs"

      echo "Starting Impala Daemon on hs2://localhost:21050..."
      ${impalaRunFn}
      impala_run "$IMPALA_HOME/be/build/latest/service/impalad" \
        --hs2_port=21050 \
        --beeswax_port=21001 \
        --state_store_subscriber_port=23000 \
        --state_store_host=localhost \
        --state_store_port=24000 \
        --catalog_service_host=localhost \
        --catalog_service_port=26000 \
        --webserver_port=25000 \
        --krpc_port=27000 \
        --log_dir="$PWD/.devenv/impala/impalad/logs" \
        --hostname=localhost \
        --kudu_master_hosts=127.0.0.1:7051 \
        --use_local_catalog=true \
        --abort_on_config_error=false \
        --hms_event_polling_interval_s=0 \
        --java_weigher=sizeof
    '';
    process-compose = {
      depends_on = {
        impala-catalogd = { condition = "process_healthy"; };
      };
      readiness_probe = {
        http_get = {
          host = "127.0.0.1";
          port = 25000;
          path = "/";
        };
        initial_delay_seconds = 5;
        period_seconds = 5;
        timeout_seconds = 5;
        success_threshold = 1;
        failure_threshold = 15;
      };
    };
  };

  # ── Tasks ──────────────────────────────────────────────────────────────────
  tasks = {
    "signals:kdc-init" = {
      exec = ''
        bash scripts/kdc-init.sh
      '';
      description = "Initialize or verify KDC database and principals";
    };

    "signals:kdc-reset" = {
      exec = ''
        bash scripts/kdc-init.sh --reset
      '';
      description = "Reset KDC database (destroys all principals and keytabs)";
    };

    # PR-K5a: verify Kudu keytab + optional secured-cluster probes
    "signals:kudu-kerberos-smoke" = {
      exec = ''
        bash scripts/kudu_kerberos_smoke.sh
      '';
      description = "PR-K5a: verify kudu keytab/principals; probe auth when SIGNALS_KUDU_KERBEROS=1";
    };

    "sigint:resolve-config" = {
      exec = ''
        uv run python -c "from sigint.config import load_config, materialize_config; materialize_config(load_config(), 'build/config/sigint.env')"
        echo "Resolved config -> build/config/sigint.env"
      '';
      description = "Resolve HOCON config + env vars to build/config/sigint.env";
    };

    "sigint:cache-models" = {
      exec = ''
        set -euo pipefail
        # Reuse host/RAID HF layout — never force a second copy under build/models
        # when HF_HOME / HF_HUB_CACHE / SENTENCE_TRANSFORMERS_HOME already resolve.
        if [ -z "''${SENTENCE_TRANSFORMERS_HOME:-}" ]; then
          if [ -d /raid/cache/sentence-transformers ]; then
            export SENTENCE_TRANSFORMERS_HOME=/raid/cache/sentence-transformers
          elif [ -n "''${HF_HOME:-}" ]; then
            export SENTENCE_TRANSFORMERS_HOME="$HF_HOME"
          else
            export SENTENCE_TRANSFORMERS_HOME="$PWD/build/models"
            mkdir -p "$SENTENCE_TRANSFORMERS_HOME"
          fi
        fi
        export SIGINT_EMBEDDING_CACHE_DIR="''${SIGINT_EMBEDDING_CACHE_DIR:-$SENTENCE_TRANSFORMERS_HOME}"
        echo "SENTENCE_TRANSFORMERS_HOME=$SENTENCE_TRANSFORMERS_HOME"
        echo "HF_HOME=''${HF_HOME:-<unset>}  HF_HUB_CACHE=''${HF_HUB_CACHE:-<unset>}"
        # If MiniLM already on disk under any known cache, skip download
        if find "$SENTENCE_TRANSFORMERS_HOME" ''${HF_HUB_CACHE:+"$HF_HUB_CACHE"} ''${HF_HOME:+"$HF_HOME"} \
             -type d -name 'models--sentence-transformers--all-MiniLM-L6-v2' 2>/dev/null | head -1 | grep -q .; then
          echo "all-MiniLM-L6-v2 already present in HF/ST cache — no download."
          exit 0
        fi
        echo "Loading all-MiniLM-L6-v2 into SENTENCE_TRANSFORMERS_HOME (online once)..."
        HF_HUB_OFFLINE=0 uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
        echo "Model cached. Pipeline uses HF_HUB_OFFLINE=1 + existing cache env vars."
      '';
      description = "Ensure MiniLM is available via HF_HOME/ST cache (prefer RAID; no tree-local dupe)";
    };

    "signals:catalog-init" = {
      exec = ''
        # Ensure app role exists (devenv postgres only creates OS-user role by default)
        psql -p 5455 -d postgres -v ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'signals') THEN
    CREATE ROLE signals LOGIN SUPERUSER PASSWORD 'signals';
  END IF;
END$$;
SQL
        for db in signals signals_catalog ranger polaris; do
          psql -p 5455 -d postgres -c "ALTER DATABASE $db OWNER TO signals;" 2>/dev/null || true
        done
        psql -p 5455 -d signals_catalog -f config/impala/catalog_schema.sql
      '';
      description = "Initialize the signals catalog registry schema in PostgreSQL";
    };

    "docs:build" = {
      exec = ''
        mdbook build docs/current
      '';
      description = "Build mdbook documentation";
    };

    "docs:serve" = {
      exec = ''
        mdbook serve docs/current --open
      '';
      description = "Serve mdbook documentation with live reload";
    };

    "atlas:build" = {
      exec = ''
        # Resolve project-local Maven *before* cd (never components/*/.devenv/m2, never ~/.m2)
        _sig_root="$PWD"
        export SIG_MAVEN_REPO="''${SIG_MAVEN_REPO:-$_sig_root/.devenv/m2}"
        mkdir -p "$SIG_MAVEN_REPO"
        cd components/atlas
        # Create empty apidocs dir so WAR plugin succeeds when enunciate is skipped
        mkdir -p webapp/target/api/v2/apidocs/ui
        # mockito.version is referenced by test-jar deps but not defined in root pom;
        # pin it so remote-resources can resolve without hitting expired java.net certs.
        mvn -Dmaven.repo.local="$SIG_MAVEN_REPO" package -pl webapp -am \
          -Dmaven.test.skip=true -DskipUTs=true \
          -DGRAPH-PROVIDER=age -Dcheckstyle.skip=true -DskipEnunciate=true \
          -Dmockito.version=3.5.10 \
          --no-transfer-progress
      '';
      description = "Build Atlas webapp with AGE backend into .devenv/m2";
    };

    "ranger:build" = {
      exec = ''
        if [ ! -f components/ranger/pom.xml ]; then
          echo "components/ranger not initialized. Run: git submodule update --init components/ranger"
          exit 1
        fi
        # Interim: JDK 11 for Nashorn (removed post-JDK 14). Not the long-term target —
        # when ready, ditch Nashorn on rch/devenv and build on modern JDKs (see docs/components/ranger.md).
        export JAVA_HOME="${pkgs.jdk11}"
        if [ ! -x "$JAVA_HOME/bin/javac" ] && [ -x "$JAVA_HOME/lib/openjdk/bin/javac" ]; then
          export JAVA_HOME="$JAVA_HOME/lib/openjdk"
        fi
        export PATH="$JAVA_HOME/bin:$PATH"
        echo "ranger:build using JAVA_HOME=$JAVA_HOME (devenv jdk11, interim Nashorn)"
        java -version 2>&1 | head -1
        # Project-local Maven only (.devenv/m2 at host root) — set before cd
        _sig_root="$PWD"
        export SIG_MAVEN_REPO="''${SIG_MAVEN_REPO:-$_sig_root/.devenv/m2}"
        mkdir -p "$SIG_MAVEN_REPO"
        cd components/ranger
        rm -f core.* hs_err_pid*.log 2>/dev/null || true
        mvn -pl security-admin,tagsync,distro,agents-audit -am install -DskipTests -Drat.skip=true \
          -Dmaven.repo.local="$SIG_MAVEN_REPO" \
          -Dmaven.compiler.fork=true \
          -Dmaven.compiler.executable="$JAVA_HOME/bin/javac" \
          --no-transfer-progress
        # Impala FE still depends on ranger-plugins-audit:jar, but Ranger 3.0 split that
        # into a pom aggregator + ranger-audit-core. Publish a jar shim for Impala.
        _ver=3.0.0-SNAPSHOT
        _core="$SIG_MAVEN_REPO/org/apache/ranger/ranger-audit-core/$_ver/ranger-audit-core-$_ver.jar"
        _shim_dir="$SIG_MAVEN_REPO/org/apache/ranger/ranger-plugins-audit/$_ver"
        if [ -f "$_core" ]; then
          mkdir -p "$_shim_dir"
          cp -f "$_core" "$_shim_dir/ranger-plugins-audit-$_ver.jar"
          cat > "$_shim_dir/ranger-plugins-audit-$_ver.pom" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>org.apache.ranger</groupId>
  <artifactId>ranger-plugins-audit</artifactId>
  <version>$_ver</version>
  <packaging>jar</packaging>
  <name>Ranger Plugins Audit (compat shim → ranger-audit-core)</name>
</project>
EOF
          echo "Installed ranger-plugins-audit jar shim from ranger-audit-core → $_shim_dir"
        else
          echo "WARNING: $_core missing; Impala FE may fail to resolve ranger-plugins-audit"
        fi
        echo "Ranger modules installed to $SIG_MAVEN_REPO (typically 3.0.0-SNAPSHOT)"
        ls -1 distro/target/ranger-*-admin.tar.gz 2>/dev/null || true
      '';
      description = "Build Ranger into .devenv/m2 (interim jdk11/Nashorn; for Impala FE)";
    };

    "ranger:install" = {
      exec = ''
        # Prefer distro admin tarball (3.0.0-SNAPSHOT from ranger:build) over CDP leftovers
        # or source-tree scripts. Destination: .devenv/ranger/admin (Impala RANGER_HOME_OVERRIDE).
        TAR=$(ls -1t components/ranger/target/ranger-*-admin.tar.gz \
                   components/ranger/distro/target/ranger-*-admin.tar.gz 2>/dev/null | head -1 || true)
        if [ -z "$TAR" ]; then
          TAR=$(find components/ranger -name 'ranger-*-admin.tar.gz' 2>/dev/null | head -1 || true)
        fi
        ADMIN_SRC=""
        if [ -n "$TAR" ] && [ -f "$TAR" ]; then
          echo "Unpacking $TAR → .devenv/ranger/unpack"
          mkdir -p .devenv/ranger/unpack
          rm -rf .devenv/ranger/unpack/*
          tar -xzf "$TAR" -C .devenv/ranger/unpack
          ADMIN_SRC=$(find .devenv/ranger/unpack -name setup.sh | head -1 | xargs -r dirname)
        fi
        if [ -z "$ADMIN_SRC" ]; then
          # Fallback: assembled admin under target (not source scripts/)
          ADMIN_SRC=$(find components/ranger -path '*/target/*-admin' -name setup.sh 2>/dev/null \
            | head -1 | xargs -r dirname || true)
        fi
        if [ -z "$ADMIN_SRC" ] || [ ! -f "$ADMIN_SRC/setup.sh" ]; then
          echo "No ranger-admin package found. Run: devenv tasks run ranger:build"
          exit 1
        fi
        bash -c 'devenv tasks run ranger:db-setup'
        rm -rf .devenv/ranger/admin
        mkdir -p .devenv/ranger/admin
        cp -a "$ADMIN_SRC"/. .devenv/ranger/admin/
        # Drop any CDP-named leftover admin trees under .devenv/ranger/
        for _old in .devenv/ranger/ranger-*-admin; do
          [ -e "$_old" ] || continue
          echo "Removing leftover $_old (use .devenv/ranger/admin only)"
          rm -rf "$_old"
        done
        cp -f .devenv/ranger/conf/install.properties .devenv/ranger/admin/install.properties
        mkdir -p .devenv/ranger/admin/ews/webapp/WEB-INF/lib 2>/dev/null || true
        cp -f .devenv/ranger/lib/postgresql.jar .devenv/ranger/admin/ews/webapp/WEB-INF/lib/ 2>/dev/null \
          || cp -f .devenv/ranger/lib/postgresql.jar .devenv/ranger/admin/ || true
        echo "Ranger admin tree: $PWD/.devenv/ranger/admin"
        echo "Impala: RANGER_HOME_OVERRIDE points here via config/impala/impala-config-local.sh"
        echo "Next: devenv tasks run ranger:setup   (or start process ranger-admin after setup)"
      '';
      description = "Install local Ranger admin package under .devenv/ranger/admin";
    };

    "ranger:setup" = {
      exec = ''
        set -euo pipefail
        if [ ! -f .devenv/ranger/admin/setup.sh ]; then
          echo "Run: devenv tasks run ranger:install first"
          exit 1
        fi
        bash -c 'devenv tasks run ranger:db-setup'
        # Full install.properties: stock template + signals overrides (Postgres :5455)
        python3 - <<'PY'
from pathlib import Path
import os
root = Path(".").resolve()
stock_p = root / "components/ranger/security-admin/scripts/install.properties"
ours_p = root / "config/ranger/install.properties"
out_p = root / ".devenv/ranger/conf/install.properties"
stock = stock_p.read_text().splitlines()
ours = {}
for line in ours_p.read_text().splitlines():
    s = line.strip()
    if not s or s.startswith("#") or "=" not in s:
        continue
    k, v = s.split("=", 1)
    ours[k.strip()] = v
ours.update({
    "LOGFILE": str(root / ".devenv/ranger/logs/setup.log"),
    "LOGFILES": str(root / ".devenv/ranger/logs/setup.log"),
    "TMPFILE": str(root / ".devenv/ranger/logs/setup.tmp"),
    "RANGER_ADMIN_LOG_DIR": str(root / ".devenv/ranger/logs"),
    "RANGER_PID_DIR_PATH": str(root / ".devenv/ranger/run"),
    "JAVA_VERSION_REQUIRED": "1.8",
    "SQL_CONNECTOR_JAR": str(root / ".devenv/ranger/lib/postgresql.jar"),
    "hadoop_conf": str(root / "config/impala"),
    "unix_user": os.environ.get("USER", "rch"),
    "unix_group": os.popen("id -gn").read().strip() or "rch",
    "db_host": "localhost:5455",
    "db_root_user": "signals",
    "db_root_password": "signals",
    "db_name": "ranger",
    "db_user": "rangeradmin",
    "db_password": "rangeradmin1",
    "DB_FLAVOR": "POSTGRES",
    "audit_store": "none",
    "audit_solr_bootstrap_enabled": "false",
    "authentication_method": "NONE",
    "policymgr_external_url": "http://localhost:6080",
    "policymgr_supportedcomponents": "impala",
    "rangerAdmin_password": "Admin123",
    "rangerTagsync_password": "Admin123",
    "rangerUsersync_password": "Admin123",
    "keyadmin_password": "Admin123",
    "PYTHON_COMMAND_INVOKER": "python3",
    "CONNECTION_STRING_ADDITIONAL_PARAMS": "",
    "sso_enabled": "false",
    "setup_mode": "",
})
out, seen = [], set()
for line in stock:
    if not line.strip() or line.strip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    k = line.split("=", 1)[0].strip()
    if k in ours:
        out.append(f"{k}={ours[k]}")
        seen.add(k)
    else:
        out.append(line)
for k, v in ours.items():
    if k not in seen:
        out.append(f"{k}={v}")
out_p.parent.mkdir(parents=True, exist_ok=True)
out_p.write_text("\n".join(out) + "\n")
print("Wrote", out_p)
PY
        mkdir -p .devenv/ranger/logs .devenv/ranger/run
        cp -f .devenv/ranger/conf/install.properties .devenv/ranger/admin/install.properties
        if [ ! -f .devenv/ranger/lib/postgresql.jar ]; then
          curl -fsSL -o .devenv/ranger/lib/postgresql.jar \
            "https://jdbc.postgresql.org/download/postgresql-42.7.4.jar"
        fi
        mkdir -p .devenv/ranger/admin/ews/webapp/WEB-INF/lib
        cp -f .devenv/ranger/lib/postgresql.jar .devenv/ranger/admin/ews/webapp/WEB-INF/lib/
        export JAVA_HOME="${pkgs.jdk11}"
        if [ ! -x "$JAVA_HOME/bin/java" ] && [ -x "$JAVA_HOME/lib/openjdk/bin/java" ]; then
          export JAVA_HOME="$JAVA_HOME/lib/openjdk"
        fi
        export PATH="$JAVA_HOME/bin:$PATH"
        (cd .devenv/ranger/admin && ./setup.sh)
        touch .devenv/ranger/admin/.setup-done
        echo "Ranger setup complete. Start with: devenv up (process ranger-admin)"
      '';
      description = "Materialize install.properties + run Ranger setup.sh against Postgres :5455";
    };

    "ranger:db-setup" = {
      exec = ''
        RANGER_HOME="$PWD/.devenv/ranger"
        mkdir -p "$RANGER_HOME/lib" "$RANGER_HOME/conf" "$RANGER_HOME/logs"
        # Materialize install.properties with absolute paths
        sed -e "s|SIG_RANGER_HOME|$RANGER_HOME|g" \
            -e "s|SIG_PROJECT_ROOT|$PWD|g" \
          "$PWD/config/ranger/install.properties" > "$RANGER_HOME/conf/install.properties"
        # PostgreSQL JDBC: project-local Maven only, else download into .devenv (never ~/.m2)
        SIG_MAVEN_REPO="''${SIG_MAVEN_REPO:-$PWD/.devenv/m2}"
        PGJAR=$(ls -1 "$SIG_MAVEN_REPO"/org/postgresql/postgresql/*/postgresql-*.jar 2>/dev/null \
          | grep -v 'sources\|javadoc' | sort -V | tail -1 || true)
        if [ -z "$PGJAR" ] || [ ! -f "$PGJAR" ]; then
          echo "Downloading PostgreSQL JDBC driver into .devenv/ranger/lib..."
          curl -fsSL -o "$RANGER_HOME/lib/postgresql.jar" \
            "https://jdbc.postgresql.org/download/postgresql-42.7.4.jar"
        else
          cp -f "$PGJAR" "$RANGER_HOME/lib/postgresql.jar"
        fi
        # Ensure DB role + grants
        psql -p 5455 -d postgres -v ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rangeradmin') THEN
    CREATE ROLE rangeradmin LOGIN PASSWORD 'rangeradmin1';
  END IF;
END$$;
GRANT ALL PRIVILEGES ON DATABASE ranger TO rangeradmin;
SQL
        # schema privileges for future objects
        psql -p 5455 -d ranger -c "GRANT ALL ON SCHEMA public TO rangeradmin;" 2>/dev/null || true
        echo "Ranger install.properties → $RANGER_HOME/conf/install.properties"
        echo "JDBC jar → $RANGER_HOME/lib/postgresql.jar"
        echo "Next: unpack ranger-admin from Maven target and run setup.sh with this install.properties"
      '';
      description = "Materialize Ranger install.properties + Postgres role/JDBC";
    };

    "impala-fdw:build" = {
      exec = ''
        if [ ! -f components/impala_fdw/Makefile ]; then
          echo "components/impala_fdw not initialized. Run: git submodule update --init components/impala_fdw"
          exit 1
        fi
        # Thrift + boost from devenv packages (task-local; not global PATH pollution)
        export THRIFT_HOME="${pkgs.thrift}"
        export BOOST_HOME="${pkgs.boost.dev}"
        # PG 16 matching services.postgres (not host /usr/bin/pg_config → 14)
        # nixpkgs multi-output often has no pg_config binary; synthesize one from
        # postgresql_16.{dev,lib,out} so PGXS resolves include/server correctly.
        PG_DEV="${pkgs.postgresql_16.dev}"
        PG_OUT="${pkgs.postgresql_16}"
        PG_LIB="${pkgs.postgresql_16.lib}"
        mkdir -p "$PWD/.devenv/pg-ext/bin" "$PWD/.devenv/pg-ext/lib" "$PWD/.devenv/pg-ext/share"
        cat > "$PWD/.devenv/pg-ext/bin/pg_config" <<EOF
#!/usr/bin/env bash
# Synthetic pg_config for devenv PG16 extension builds (nix store is read-only).
case "\$1" in
  --version) echo "PostgreSQL 16.12";;
  --pgxs) echo "$PG_DEV/lib/pgxs/src/makefiles/pgxs.mk";;
  --includedir|--pkgincludedir) echo "$PG_DEV/include";;
  --includedir-server) echo "$PG_DEV/include/server";;
  --libdir) echo "$PG_LIB/lib";;
  --pkglibdir) echo "$PWD/.devenv/pg-ext/lib";;
  --sharedir) echo "$PWD/.devenv/pg-ext/share";;
  --bindir) echo "$PG_OUT/bin";;
  --sysconfdir) echo "/etc/postgresql";;
  --mandir|--docdir|--localedir|--htmldir) echo "$PWD/.devenv/pg-ext/share";;
  --cc) echo "cc";;
  --cppflags) echo "-I$PG_DEV/include";;
  --cflags) echo "-fPIC -O2";;
  --cflags_sl) echo "-fPIC";;
  --ldflags) echo "-L$PG_LIB/lib";;
  --ldflags_ex|--ldflags_sl) echo "";;
  --libs) echo "";;
  --configure) echo "";;
  *) echo "";;  # PGXS probes many optional switches; empty is fine
esac
EOF
        chmod +x "$PWD/.devenv/pg-ext/bin/pg_config"
        export PG_CONFIG="$PWD/.devenv/pg-ext/bin/pg_config"
        echo "Using PG_CONFIG=$PG_CONFIG ($($PG_CONFIG --version))"
        test -f "$($PG_CONFIG --includedir-server)/postgres.h" \
          || test -f "$($PG_CONFIG --pkgincludedir)/server/postgres.h" \
          || { echo "ERROR: postgres.h not found via pg_config"; exit 1; }
        cd components/impala_fdw
        make clean 2>/dev/null || true
        # PGXS Makefile.global bakes clang-only -W flags; override for a plain
        # gcc/g++ (or clang++) build with libstdc++ for thrift C++.
        export CC="${pkgs.stdenv.cc}/bin/cc"
        export CXX="${pkgs.stdenv.cc}/bin/c++"
        SAFE_CFLAGS="-O2 -fPIC -fno-strict-aliasing -fwrapv -Wall"

        # libkudu_client (PR-K0+): lib from .devenv symlink farm; headers from
        # Impala toolchain (NOT under .devenv/impala — no include tree there).
        REPO_ROOT="$(cd ../.. && pwd)"
        export IMPALA_KUDU_VERSION="''${IMPALA_KUDU_VERSION:-879a8f9e2}"
        if [ -z "''${IMPALA_TOOLCHAIN_PACKAGES_HOME:-}" ]; then
          # Match enterShell / Impala toolchain layout
          _tc=$(ls -d "$REPO_ROOT/components/impala/toolchain/toolchain-packages-"* 2>/dev/null | head -1 || true)
          [ -n "$_tc" ] && export IMPALA_TOOLCHAIN_PACKAGES_HOME="$_tc"
        fi
        KUDU_CLIENT_LIBDIR=""
        KUDU_CLIENT_INCDIR=""
        IMPALA_FDW_WITH_KUDU=""
        if [ -f "$REPO_ROOT/.devenv/impala/lib/libkudu_client.so" ]; then
          KUDU_CLIENT_LIBDIR="$REPO_ROOT/.devenv/impala/lib"
        elif [ -n "''${IMPALA_TOOLCHAIN_PACKAGES_HOME:-}" ]; then
          for _v in debug release; do
            if [ -f "$IMPALA_TOOLCHAIN_PACKAGES_HOME/kudu-$IMPALA_KUDU_VERSION/$_v/lib/libkudu_client.so" ]; then
              KUDU_CLIENT_LIBDIR="$IMPALA_TOOLCHAIN_PACKAGES_HOME/kudu-$IMPALA_KUDU_VERSION/$_v/lib"
              break
            fi
          done
        fi
        if [ -n "''${IMPALA_TOOLCHAIN_PACKAGES_HOME:-}" ]; then
          for _v in debug release; do
            if [ -f "$IMPALA_TOOLCHAIN_PACKAGES_HOME/kudu-$IMPALA_KUDU_VERSION/$_v/include/kudu/client/client.h" ]; then
              KUDU_CLIENT_INCDIR="$IMPALA_TOOLCHAIN_PACKAGES_HOME/kudu-$IMPALA_KUDU_VERSION/$_v/include"
              break
            fi
          done
        fi
        if [ -z "$KUDU_CLIENT_INCDIR" ] && [ -f "$REPO_ROOT/components/kudu/src/kudu/client/client.h" ]; then
          KUDU_CLIENT_INCDIR="$REPO_ROOT/components/kudu/src"
        fi
        if [ -n "$KUDU_CLIENT_LIBDIR" ] && [ -n "$KUDU_CLIENT_INCDIR" ]; then
          IMPALA_FDW_WITH_KUDU=1
          echo "impala_fdw: kudu_scan build ON"
          echo "  KUDU_CLIENT_LIBDIR=$KUDU_CLIENT_LIBDIR"
          echo "  KUDU_CLIENT_INCDIR=$KUDU_CLIENT_INCDIR"
        else
          echo "impala_fdw: kudu_scan build OFF (HS2-only; missing lib and/or headers)"
          echo "  LIBDIR=''${KUDU_CLIENT_LIBDIR:-unset} INCDIR=''${KUDU_CLIENT_INCDIR:-unset}"
        fi

        # PR-K5b: libkrb5 for optional keytab→ccache kinit in exec_kudu
        export SIG_KRB5_INC="''${SIG_KRB5_INC:-${pkgs.krb5.dev}/include}"
        export SIG_KRB5_LIB="''${SIG_KRB5_LIB:-${pkgs.krb5.lib}/lib}"
        make with_llvm=no \
          PG_CONFIG="$PG_CONFIG" \
          CC="$CC" \
          CXX="$CXX" \
          CFLAGS="$SAFE_CFLAGS" \
          CXXFLAGS="$SAFE_CFLAGS -std=c++17" \
          THRIFT_HOME="$THRIFT_HOME" \
          BOOST_HOME="$BOOST_HOME" \
          SIG_KRB5_INC="$SIG_KRB5_INC" \
          SIG_KRB5_LIB="$SIG_KRB5_LIB" \
          KUDU_CLIENT_LIBDIR="$KUDU_CLIENT_LIBDIR" \
          KUDU_CLIENT_INCDIR="$KUDU_CLIENT_INCDIR" \
          IMPALA_FDW_WITH_KUDU="''${IMPALA_FDW_WITH_KUDU}" \
          PG_CPPFLAGS="-I$BOOST_HOME/include -I$THRIFT_HOME/include -Isrc -Igen-cpp -I$SIG_KRB5_INC''${KUDU_CLIENT_INCDIR:+ -I$KUDU_CLIENT_INCDIR}''${IMPALA_FDW_WITH_KUDU:+ -DIMPALA_FDW_WITH_KUDU=1}"
        test -f impala_fdw.so || { echo "ERROR: impala_fdw.so not produced"; ls -la; exit 1; }
        if [ "''${IMPALA_FDW_WITH_KUDU}" = "1" ]; then
          if command -v ldd >/dev/null 2>&1; then
            ldd impala_fdw.so | grep -q kudu_client \
              || { echo "ERROR: impala_fdw.so built WITH_KUDU but not linked to libkudu_client"; ldd impala_fdw.so; exit 1; }
          fi
          echo "impala_fdw.so built (HS2 thrift + libkudu_client stub; kudu_scan PR-K0)."
        else
          echo "impala_fdw.so built (HS2 thrift client only; NOSASL ready)."
        fi
        echo "Next: devenv tasks run impala-fdw:install"
      '';
      description = "Build PostgreSQL Impala FDW (HS2 thrift + optional libkudu_client)";
    };

    "impala-fdw:install" = {
      exec = ''
        set -euo pipefail
        EXT_DIR="$PWD/.devenv/pg-ext"
        SO="$PWD/components/impala_fdw/impala_fdw.so"
        if [ ! -f "$SO" ]; then
          echo "Build first: devenv tasks run impala-fdw:build"
          exit 1
        fi
        mkdir -p "$EXT_DIR/lib" "$EXT_DIR/share/extension"
        cp -f "$SO" "$EXT_DIR/lib/impala_fdw.so"
        # Control + SQL with absolute module path (nix PG share is read-only)
        cat > "$EXT_DIR/share/extension/impala_fdw.control" <<EOF
comment = 'PostgreSQL FDW for Apache Impala HS2 (Kudu tables)'
default_version = '0.1.0'
module_pathname = '$EXT_DIR/lib/impala_fdw'
relocatable = true
EOF
        # Expand MODULE_PATHNAME in the SQL script
        sed "s|MODULE_PATHNAME|'$EXT_DIR/lib/impala_fdw'|g" \
          components/impala_fdw/sql/impala_fdw--0.1.0.sql \
          > "$EXT_DIR/share/extension/impala_fdw--0.1.0.sql"
        # Register extension objects (CREATE EXTENSION needs control on path;
        # use direct SQL against absolute .so for devenv PG).
        psql -h 127.0.0.1 -p 5455 -d signals -v ON_ERROR_STOP=1 <<SQL
-- Drop stale objects if re-installing
DROP EXTENSION IF EXISTS impala_fdw CASCADE;
DROP FOREIGN DATA WRAPPER IF EXISTS impala_fdw CASCADE;
DROP FUNCTION IF EXISTS impala_fdw_handler() CASCADE;
DROP FUNCTION IF EXISTS impala_fdw_validator(text[], oid) CASCADE;

CREATE FUNCTION impala_fdw_handler()
RETURNS fdw_handler
AS '$EXT_DIR/lib/impala_fdw'
LANGUAGE C STRICT;

CREATE FUNCTION impala_fdw_validator(text[], oid)
RETURNS void
AS '$EXT_DIR/lib/impala_fdw'
LANGUAGE C STRICT;

CREATE FOREIGN DATA WRAPPER impala_fdw
  HANDLER impala_fdw_handler
  VALIDATOR impala_fdw_validator;

-- Default server → local Impala HS2 (NOSASL), Kudu-backed tables
DROP SERVER IF EXISTS impala_kudu_srv CASCADE;
CREATE SERVER impala_kudu_srv
  FOREIGN DATA WRAPPER impala_fdw
  OPTIONS (
    host '127.0.0.1',
    port '21050',
    auth 'nosasl',
    kudu_masters '127.0.0.1:7051',
    default_access 'impala_sql'
  );

CREATE USER MAPPING IF NOT EXISTS FOR CURRENT_USER
  SERVER impala_kudu_srv;

\\echo 'impala_fdw installed; server impala_kudu_srv → 127.0.0.1:21050 (nosasl)'
SQL
        echo "Installed to $EXT_DIR and registered in database signals."
        echo "Smoke: devenv tasks run impala-fdw:smoke"
      '';
      description = "Install impala_fdw into devenv PG (:5455/signals) + create default server";
    };

    "impala-fdw:smoke" = {
      exec = ''
        set -euo pipefail
        # HS2 native smoke (optional binary)
        if [ -x components/impala_fdw/tools/hs2_smoke ]; then
          components/impala_fdw/tools/hs2_smoke 127.0.0.1 21050
        elif [ -f components/impala_fdw/Makefile ]; then
          export THRIFT_HOME="${pkgs.thrift}"
          export BOOST_HOME="${pkgs.boost.dev}"
          make -C components/impala_fdw hs2-smoke \
            THRIFT_HOME="$THRIFT_HOME" BOOST_HOME="$BOOST_HOME" || true
          if [ -x components/impala_fdw/tools/hs2_smoke ]; then
            components/impala_fdw/tools/hs2_smoke 127.0.0.1 21050
          fi
        fi
        # FDW object presence
        psql -h 127.0.0.1 -p 5455 -d signals -v ON_ERROR_STOP=1 <<'SQL'
SELECT fdwname FROM pg_foreign_data_wrapper WHERE fdwname = 'impala_fdw';
SELECT srvname, srvoptions FROM pg_foreign_server WHERE srvname = 'impala_kudu_srv';
-- Lightweight probe: list remote tables via Impala if any (may be empty)
-- CREATE FOREIGN TABLE is deferred until a Kudu table exists in catalog.
SQL
        echo "impala_fdw smoke OK (wrapper + server present; foreign tables after Kudu seed)."
      '';
      description = "Smoke HS2 client + verify impala_fdw FDW objects in PG";
    };

    "hms:install" = {
      exec = ''
        HMS_HOME="$PWD/.devenv/hms"
        HMS_VERSION="4.2.0"
        HMS_URL="https://dlcdn.apache.org/hive/hive-standalone-metastore-$HMS_VERSION/hive-standalone-metastore-$HMS_VERSION-bin.tar.gz"

        if [ -d "$HMS_HOME/lib" ]; then
          echo "HMS already installed at $HMS_HOME"
          exit 0
        fi

        echo "Downloading Hive Standalone Metastore $HMS_VERSION..."
        mkdir -p "$HMS_HOME"
        TMP_DIR=$(mktemp -d)
        curl -fSL "$HMS_URL" -o "$TMP_DIR/hms.tar.gz"
        tar -xzf "$TMP_DIR/hms.tar.gz" -C "$TMP_DIR"
        cp -r "$TMP_DIR"/apache-hive-metastore-*/lib "$HMS_HOME/"
        cp -r "$TMP_DIR"/apache-hive-metastore-*/scripts "$HMS_HOME/"
        rm -rf "$TMP_DIR"

        # Add PostgreSQL JDBC driver if not present
        PG_JDBC="postgresql-42.7.4.jar"
        if [ ! -f "$HMS_HOME/lib/$PG_JDBC" ]; then
          echo "Downloading PostgreSQL JDBC driver..."
          curl -fSL "https://jdbc.postgresql.org/download/$PG_JDBC" -o "$HMS_HOME/lib/$PG_JDBC"
        fi

        echo "HMS installed at $HMS_HOME"
      '';
      description = "Download and install Hive Standalone Metastore";
    };

    "hms:init-schema" = {
      exec = ''
        HMS_HOME="$PWD/.devenv/hms"
        HMS_CONF="$PWD/config/hms"

        if [ ! -d "$HMS_HOME/lib" ]; then
          echo "HMS not installed. Run: devenv tasks run hms:install"
          exit 1
        fi

        echo "Initializing HMS schema in PostgreSQL..."
        java \
          --add-opens java.base/java.lang=ALL-UNNAMED \
          --add-opens java.base/java.lang.reflect=ALL-UNNAMED \
          --add-opens java.base/java.net=ALL-UNNAMED \
          --add-opens java.base/java.util=ALL-UNNAMED \
          -cp "$HMS_CONF:$HMS_HOME/lib/*" \
          org.apache.hadoop.hive.metastore.tools.MetastoreSchemaTool \
          -dbType postgres \
          -initSchema \
          --verbose
      '';
      description = "Initialize HMS schema in PostgreSQL (run once)";
    };

    "kudu:install-java" = {
      exec = ''
        if [ ! -d components/kudu/java ]; then
          echo "components/kudu not initialized. Run: git submodule update --init components/kudu"
          exit 1
        fi
        _sig_root="$PWD"
        export SIG_MAVEN_REPO="''${SIG_MAVEN_REPO:-$_sig_root/.devenv/m2}"
        mkdir -p "$SIG_MAVEN_REPO"
        # Gradle 7.x needs <= JDK 17; pin devenv jdk17 over host JAVA_HOME
        export JAVA_HOME="${pkgs.jdk17}"
        if [ ! -x "$JAVA_HOME/bin/java" ] && [ -x "$JAVA_HOME/lib/openjdk/bin/java" ]; then
          export JAVA_HOME="$JAVA_HOME/lib/openjdk"
        fi
        export PATH="$JAVA_HOME/bin:$PATH"
        cd components/kudu/java
        # Publish into project-local Maven layout (not ~/.m2)
        ./gradlew :kudu-client:publishToMavenLocal \
          -Dmaven.repo.local="$SIG_MAVEN_REPO" \
          -Pmaven.repo.local="$SIG_MAVEN_REPO"
      '';
      description = "Install Kudu Java client into .devenv/m2 (devenv jdk17)";
    };

    "kudu:build-cpp" = {
      exec = ''
        KUDU_SRC="$PWD/components/kudu"
        if [ ! -d "$KUDU_SRC" ] || [ ! -f "$KUDU_SRC/CMakeLists.txt" ]; then
          echo "components/kudu not initialized. Run: git submodule update --init components/kudu"
          exit 1
        fi
        ${asfNativeLinkEnv}
        # GCC 15: C23 bool breaks bundled thirdparty postgres; libstdc++ no longer
        # transitively provides uint*_t in LLVM 11 headers. Force GNU11/C++17 and
        # pre-include stdint.h (not cstdint — compiler-rt uses -nostdinc++).
        export EXTRA_CFLAGS="''${EXTRA_CFLAGS:-} -std=gnu11 -include stdint.h -D_DEFAULT_SOURCE"
        export EXTRA_CXXFLAGS="''${EXTRA_CXXFLAGS:-} -std=gnu++17 -include stdint.h"
        export CFLAGS="''${CFLAGS:-} -std=gnu11 -include stdint.h -D_DEFAULT_SOURCE"
        export CXXFLAGS="''${CXXFLAGS:-} -std=gnu++17 -include stdint.h"
        # Nix gcc is configured with a fake --prefix=/nix/store/eeee...; Kudu's
        # build_llvm() passes that to -DGCC_INSTALL_PREFIX and clang later fails
        # with "cannot find -lgcc". Override with the real store path.
        _libgcc="$(gcc -print-file-name=libgcc.a)"
        _real_gcc_prefix="''${_libgcc%%/lib/gcc/*}"
        # Drop sanitizers/xray: not needed for Kudu IR codegen; LLVM 11 + modern
        # glibc (no termio/crypt) fails to compile compiler-rt sanitizers.
        export EXTRA_CMAKE_FLAGS="''${EXTRA_CMAKE_FLAGS:-} -DGCC_INSTALL_PREFIX=$_real_gcc_prefix -DCOMPILER_RT_BUILD_SANITIZERS=OFF -DCOMPILER_RT_BUILD_XRAY=OFF"
        echo "Kudu build: GCC_INSTALL_PREFIX=$_real_gcc_prefix (sanitizers off)"
        # Gradle 7.6 does not support class file major 65 (Java 21). Prefer devenv jdk17
        # over scanning /nix/store or system JVMs.
        if command -v java >/dev/null 2>&1; then
          _jv="$(java -version 2>&1 | head -1 || true)"
          if echo "$_jv" | grep -qE 'version "2[1-9]'; then
            export JAVA_HOME="${pkgs.jdk17}"
            if [ ! -x "$JAVA_HOME/bin/java" ] && [ -x "$JAVA_HOME/lib/openjdk/bin/java" ]; then
              export JAVA_HOME="$JAVA_HOME/lib/openjdk"
            fi
            export PATH="$JAVA_HOME/bin:$PATH"
            echo "Kudu build: JAVA_HOME=$JAVA_HOME (devenv jdk17 for Gradle)"
          fi
        fi

        mkdir -p "$KUDU_SRC/build/release"
        cd "$KUDU_SRC/build/release"
        # Clear cmake cache if OpenSSL version changed
        if [ -f CMakeCache.txt ]; then
          CACHED_SSL=$(grep OPENSSL_SSL_LIBRARY CMakeCache.txt 2>/dev/null | head -1)
          CURRENT_SSL=$(which openssl 2>/dev/null | xargs readlink -f 2>/dev/null || true)
          if echo "$CACHED_SSL" | grep -q "openssl-3.0" && ! echo "$CURRENT_SSL" | grep -q "openssl-3.0"; then
            echo "OpenSSL version changed, clearing cmake cache..."
            rm -f CMakeCache.txt
          fi
        fi
        # thirdparty complete when llvm-config is present (not merely uninstrumented/)
        if [ ! -x "$KUDU_SRC/thirdparty/installed/uninstrumented/bin/llvm-config" ] && \
           [ ! -x "$KUDU_SRC/thirdparty/installed/common/bin/llvm-config" ]; then
          echo "Building Kudu thirdparty (long; LLVM 11 is the slow step)..."
          (cd "$KUDU_SRC/thirdparty" && ./build-if-necessary.sh)
        fi
        cmake -DCMAKE_BUILD_TYPE=Release -GNinja -DNO_TESTS=1 \
          -DCMAKE_C_FLAGS="-std=gnu11" \
          -DCMAKE_CXX_FLAGS="-std=gnu++17" \
          ../..
        ninja kudu-master kudu-tserver
        ln -sfn "$KUDU_SRC/build/release" "$KUDU_SRC/build/latest"
        echo "Kudu binaries: $KUDU_SRC/build/latest/bin/"
      '';
      description = "Build Kudu C++ master and tserver from components/kudu";
    };

    "impala:bootstrap" = {
      exec = ''
        # Local Ranger/Kudu overrides — skip CDP ranger-admin tarball download
        cp -f config/impala/impala-config-local.sh components/impala/bin/impala-config-local.sh
        # Drop thrift/boost from path pollution (keep sasl/krb5/openssl).
        # Bash vars escaped for Nix multi-line strings via doubled single-quote.
        PATH="$(printf '%s' "''${PATH:-}" | tr ':' '\n' | grep -vE '/thrift-|/boost-' | paste -sd: - || true)"
        CMAKE_INCLUDE_PATH="$(printf '%s' "''${CMAKE_INCLUDE_PATH:-}" | tr ':' '\n' | grep -vE '/thrift-|/boost-' | paste -sd: - || true)"
        CMAKE_LIBRARY_PATH="$(printf '%s' "''${CMAKE_LIBRARY_PATH:-}" | tr ':' '\n' | grep -vE '/thrift-|/boost-' | paste -sd: - || true)"
        CMAKE_PREFIX_PATH="$(printf '%s' "''${CMAKE_PREFIX_PATH:-}" | tr ':' '\n' | grep -vE '/thrift-|/boost-' | paste -sd: - || true)"
        PKG_CONFIG_PATH="$(printf '%s' "''${PKG_CONFIG_PATH:-}" | tr ':' '\n' | grep -vE '/thrift-|/boost-' | paste -sd: - || true)"
        export PATH CMAKE_INCLUDE_PATH CMAKE_LIBRARY_PATH CMAKE_PREFIX_PATH PKG_CONFIG_PATH
        cd components/impala
        source bin/impala-config.sh
        echo "RANGER_HOME=$RANGER_HOME  IMPALA_RANGER_VERSION=$IMPALA_RANGER_VERSION"
        python3 bin/bootstrap_toolchain.py
      '';
      description = "Download Impala toolchain (skips CDP Ranger when local override set)";
    };

    "impala:build" = {
      exec = ''
        cp -f config/impala/impala-config-local.sh components/impala/bin/impala-config-local.sh
        _sig_root="$PWD"
        export SIG_MAVEN_REPO="''${SIG_MAVEN_REPO:-$_sig_root/.devenv/m2}"
        mkdir -p "$SIG_MAVEN_REPO"
        export MAVEN_ARGS="''${MAVEN_ARGS:-} -Dmaven.repo.local=$SIG_MAVEN_REPO"
        # Isolate from Nix/direnv thrift+boost without dropping krb5/openssl/sasl.
        # Parent PATH often still has thrift-0.22 from an older devenv profile.
        # Bash vars escaped for Nix multi-line strings via doubled single-quote.
        PATH="$(printf '%s' "''${PATH:-}" | tr ':' '\n' | grep -vE '/thrift-|/boost-' | paste -sd: - || true)"
        CMAKE_INCLUDE_PATH="$(printf '%s' "''${CMAKE_INCLUDE_PATH:-}" | tr ':' '\n' | grep -vE '/thrift-|/boost-' | paste -sd: - || true)"
        CMAKE_LIBRARY_PATH="$(printf '%s' "''${CMAKE_LIBRARY_PATH:-}" | tr ':' '\n' | grep -vE '/thrift-|/boost-' | paste -sd: - || true)"
        CMAKE_PREFIX_PATH="$(printf '%s' "''${CMAKE_PREFIX_PATH:-}" | tr ':' '\n' | grep -vE '/thrift-|/boost-' | paste -sd: - || true)"
        PKG_CONFIG_PATH="$(printf '%s' "''${PKG_CONFIG_PATH:-}" | tr ':' '\n' | grep -vE '/thrift-|/boost-' | paste -sd: - || true)"
        LIBRARY_PATH="$(printf '%s' "''${LIBRARY_PATH:-}" | tr ':' '\n' | grep -vE '/thrift-|/boost-' | paste -sd: - || true)"
        CPATH="$(printf '%s' "''${CPATH:-}" | tr ':' '\n' | grep -vE '/thrift-|/boost-' | paste -sd: - || true)"
        CPLUS_INCLUDE_PATH="$(printf '%s' "''${CPLUS_INCLUDE_PATH:-}" | tr ':' '\n' | grep -vE '/thrift-|/boost-' | paste -sd: - || true)"
        export PATH CMAKE_INCLUDE_PATH CMAKE_LIBRARY_PATH CMAKE_PREFIX_PATH PKG_CONFIG_PATH LIBRARY_PATH CPATH CPLUS_INCLUDE_PATH
        ${asfNativeLinkEnv}
        # jdk21_headless before impala-config so FindJNI / RUNPATH bake the right libjvm
        ${impalaJdkEnv}
        cd components/impala
        source bin/impala-config.sh
        # Re-assert headless after config (must match process-compose runtime)
        ${impalaJdkEnv}
        # Toolchain gcc/g++ MUST win over Nix gcc (C++20 breaks gutil with -Werror)
        if [ -n "''${IMPALA_TOOLCHAIN_PACKAGES_HOME:-}" ] && \
           [ -x "$IMPALA_TOOLCHAIN_PACKAGES_HOME/gcc-10.4.0/bin/g++" ]; then
          export PATH="$IMPALA_TOOLCHAIN_PACKAGES_HOME/gcc-10.4.0/bin:$PATH"
          export CC="$IMPALA_TOOLCHAIN_PACKAGES_HOME/gcc-10.4.0/bin/gcc"
          export CXX="$IMPALA_TOOLCHAIN_PACKAGES_HOME/gcc-10.4.0/bin/g++"
        fi
        # Prefer toolchain thrift on PATH for any accidental discovery
        if [ -n "''${THRIFT_CPP_HOME:-}" ] && [ -d "$THRIFT_CPP_HOME/bin" ]; then
          export PATH="$THRIFT_CPP_HOME/bin:$PATH"
        fi
        # Reconfigure if CMake still points at full GUI OpenJDK for libjvm
        if [ -f CMakeCache.txt ]; then
          if grep -q 'JAVA_JVM_LIBRARY:FILEPATH=.*openjdk' CMakeCache.txt \
             && ! grep -q 'JAVA_JVM_LIBRARY:FILEPATH=.*headless' CMakeCache.txt; then
            echo "WARNING: CMakeCache uses non-headless JAVA_JVM_LIBRARY — reconfigure"
            rm -f CMakeCache.txt
            rm -rf CMakeFiles
          fi
        fi
        # FE needs ranger-plugins-* at IMPALA_RANGER_VERSION in *project* m2
        if ! ls "$SIG_MAVEN_REPO"/org/apache/ranger/ranger-plugins-common/"$IMPALA_RANGER_VERSION"/*.jar >/dev/null 2>&1; then
          echo "Ranger jars missing in $SIG_MAVEN_REPO for version $IMPALA_RANGER_VERSION."
          echo "Run: devenv tasks run ranger:build"
          exit 1
        fi
        # Drop CMakeCache if poisoned (wrong thrift/boost, bare gssapi, or Nix gcc 15)
        if [ -f CMakeCache.txt ]; then
          _need_reconf=0
          grep -qE '/nix/store/[^ ]*thrift|/nix/store/[^ ]*boost' CMakeCache.txt && _need_reconf=1
          grep -qE 'gcc-wrapper-1[5-9]|gcc-1[5-9]' CMakeCache.txt && _need_reconf=1
          if [ -f be/src/service/CMakeFiles/impalad.dir/link.txt ] && \
             grep -qE '(^|[^-])-lgssapi_krb5' be/src/service/CMakeFiles/impalad.dir/link.txt 2>/dev/null; then
            _need_reconf=1
          fi
          if [ "$_need_reconf" = 1 ]; then
            echo "WARNING: CMakeCache not devenv-portable — reconfigure (keep object trees)"
            rm -f CMakeCache.txt; rm -rf CMakeFiles
          fi
        fi
        echo "CXX=$CXX ($(command -v g++ || true))"
        echo "THRIFT_CPP_HOME=$THRIFT_CPP_HOME"
        echo "SIG_KRB5_LIB=$SIG_KRB5_LIB"
        echo "JAVA_JVM expected under headless: $JAVA_HOME/lib/server/libjvm.so"
        ls -la "$JAVA_HOME/lib/server/libjvm.so"
        ./buildall.sh -notests -noclean
        # Prove link used headless libjvm
        if [ -x be/build/latest/service/impalad ]; then
          echo "=== impalad RUNPATH (must contain headless) ==="
          readelf -d be/build/latest/service/impalad | grep -E 'RUNPATH|RPATH' || true
          if ! readelf -d be/build/latest/service/impalad | grep -q headless; then
            echo "ERROR: impalad RUNPATH does not reference openjdk-headless"
            exit 1
          fi
        fi
      '';
      description = "Full Impala build (jdk21_headless JNI, toolchain gcc, portable krb5; .devenv/m2)";
    };

    "impala:build-fe" = {
      exec = ''
        _sig_root="$PWD"
        export SIG_MAVEN_REPO="''${SIG_MAVEN_REPO:-$_sig_root/.devenv/m2}"
        export MAVEN_ARGS="''${MAVEN_ARGS:-} -Dmaven.repo.local=$SIG_MAVEN_REPO"
        export IMPALA_HOME="$_sig_root/components/impala"
        cp -f config/impala/impala-config-local.sh "$IMPALA_HOME/bin/impala-config-local.sh"
        ${impalaJdkEnv}
        # shellcheck source=/dev/null
        # impala-config.sh is set -u sensitive until IMPALA_HOME is exported
        source "$IMPALA_HOME/bin/impala-config.sh"
        ${impalaJdkEnv}
        # Build FE + impala-package so package-classpath.txt exists for set-classpath.sh
        # (catalogd/impalad process-compose entries require it).
        cd "$IMPALA_HOME/java"
        mvn -Dmaven.repo.local="$SIG_MAVEN_REPO" package \
          -pl ../fe,impala-package -am -DskipTests --no-transfer-progress
        if [ ! -s impala-package/target/package-classpath.txt ]; then
          echo "ERROR: package-classpath.txt not produced under java/impala-package/target/"
          exit 1
        fi
        echo "OK: $(wc -c < impala-package/target/package-classpath.txt) bytes package-classpath.txt"
      '';
      description = "Impala FE + impala-package (package-classpath for catalogd/impalad; .devenv/m2)";
    };

    "impala:test-fe" = {
      exec = ''
        _sig_root="$PWD"
        export SIG_MAVEN_REPO="''${SIG_MAVEN_REPO:-$_sig_root/.devenv/m2}"
        export MAVEN_ARGS="''${MAVEN_ARGS:-} -Dmaven.repo.local=$SIG_MAVEN_REPO"
        cd components/impala
        source bin/impala-config.sh
        mvn -Dmaven.repo.local="$SIG_MAVEN_REPO" test -pl fe \
          -Dtest="ConfigLoaderTest,KuduMetaProviderTest,SignalsDdlExecutorTest" \
          -DfailIfNoTests=false --no-transfer-progress
      '';
      description = "Run Impala FE unit tests for signals changes";
    };

    "polaris:install" = {
      exec = ''
        POLARIS_HOME="$PWD/.devenv/polaris"

        if [ -f "$POLARIS_HOME/polaris-quarkus-server.jar" ] || [ -d "$POLARIS_HOME/lib" ]; then
          echo "Polaris already installed at $POLARIS_HOME"
          exit 0
        fi

        echo "Building Apache Polaris from source..."
        POLARIS_SRC="$PWD/.devenv/polaris-src"

        if [ ! -d "$POLARIS_SRC" ]; then
          git clone --depth 1 https://github.com/apache/polaris.git "$POLARIS_SRC"
        fi

        cd "$POLARIS_SRC"
        ./gradlew :polaris-quarkus-server:build -x test -x intTest --no-daemon

        mkdir -p "$POLARIS_HOME"
        cp quarkus/server/build/quarkus-app/quarkus-run.jar "$POLARIS_HOME/polaris-quarkus-server.jar" 2>/dev/null || true
        if [ -d quarkus/server/build/quarkus-app/lib ]; then
          cp -r quarkus/server/build/quarkus-app/lib "$POLARIS_HOME/"
          cp -r quarkus/server/build/quarkus-app/app "$POLARIS_HOME/" 2>/dev/null || true
          cp -r quarkus/server/build/quarkus-app/quarkus "$POLARIS_HOME/" 2>/dev/null || true
        fi

        echo "Polaris installed at $POLARIS_HOME"
      '';
      description = "Build and install Apache Polaris (Iceberg REST catalog)";
    };
  };

  # ── Shell ──────────────────────────────────────────────────────────────────
  enterShell = ''
    KDC_DIR="$PWD/.devenv/kdc"
    export KRB5_CONFIG="$KDC_DIR/krb5.conf"
    export KRB5_KDC_PROFILE="$KDC_DIR/kdc.conf"
    export KRB5CCNAME="$KDC_DIR/krb5cc"

    # Kudu build location (submodule; override with KUDU_BUILD if needed)
    export KUDU_BUILD="''${KUDU_BUILD:-$PWD/components/kudu/build/latest}"

    # Project-local Maven repo (never pollute ~/.m2 with signals SNAPSHOTs).
    # Maven 3.9+ honors MAVEN_ARGS; tasks also pass -Dmaven.repo.local explicitly.
    export SIG_MAVEN_REPO="''${SIG_MAVEN_REPO:-$PWD/.devenv/m2}"
    mkdir -p "$SIG_MAVEN_REPO"
    export MAVEN_ARGS="''${MAVEN_ARGS:-} -Dmaven.repo.local=$SIG_MAVEN_REPO"

    # ASF C++ portable link paths (krb5/gssapi/sasl/openssl) — see config/asf/native-link-env.sh
    export SIG_KRB5_LIB="${pkgs.krb5.lib}/lib"
    export SIG_KRB5_INC="${pkgs.krb5.dev}/include"
    export SIG_SASL_LIB="${pkgs.cyrus_sasl.out}/lib"
    export SIG_SASL_INC="${pkgs.cyrus_sasl.dev}/include"
    export SIG_SSL_LIB="${pkgs.openssl.out}/lib"
    export SIG_SSL_INC="${pkgs.openssl.dev}/include"
    if [ -f "$PWD/config/asf/native-link-env.sh" ]; then
      # shellcheck source=/dev/null
      . "$PWD/config/asf/native-link-env.sh"
    fi

    # HuggingFace / sentence-transformers caches (lab: RAID; do not clobber host).
    # Prefer ambient HF_HOME / HF_HUB_CACHE / SENTENCE_TRANSFORMERS_HOME (often
    # /raid/cache/...). Only fall back to tree-local build/models if nothing else.
    # Note: HF_HUB_CACHE may differ from $HF_HOME/hub (rch-scoped raid path).
    export HF_HUB_OFFLINE="''${HF_HUB_OFFLINE:-1}"
    export TRANSFORMERS_OFFLINE="''${TRANSFORMERS_OFFLINE:-$HF_HUB_OFFLINE}"
    if [ -z "''${HF_HOME:-}" ] && [ -d /raid/cache/huggingface ]; then
      export HF_HOME=/raid/cache/huggingface
    fi
    if [ -z "''${HF_HUB_CACHE:-}" ]; then
      if [ -d /raid/cache/rch/huggingface ]; then
        export HF_HUB_CACHE=/raid/cache/rch/huggingface
      elif [ -n "''${HF_HOME:-}" ] && [ -d "$HF_HOME/hub" ]; then
        export HF_HUB_CACHE="$HF_HOME/hub"
      fi
    fi
    if [ -z "''${SENTENCE_TRANSFORMERS_HOME:-}" ]; then
      if [ -d /raid/cache/sentence-transformers ]; then
        export SENTENCE_TRANSFORMERS_HOME=/raid/cache/sentence-transformers
      else
        export SENTENCE_TRANSFORMERS_HOME="$PWD/build/models"
      fi
    fi
    # Pipeline HOCON embedding.cache_dir (SentenceTransformer cache_folder)
    export SIGINT_EMBEDDING_CACHE_DIR="''${SIGINT_EMBEDDING_CACHE_DIR:-$SENTENCE_TRANSFORMERS_HOME}"

    # NVIDIA driver libs for PyTorch/CatBoost CUDA.
    # Nix ld-linux doesn't search /lib/x86_64-linux-gnu/ (which also has
    # a conflicting glibc).  Symlink just the driver .so files into a
    # clean directory and prepend it to LD_LIBRARY_PATH.
    NVIDIA_DRIVER_LIBS="$PWD/.devenv/nvidia-driver-libs"
    if [ -e /lib/x86_64-linux-gnu/libcuda.so.1 ]; then
      mkdir -p "$NVIDIA_DRIVER_LIBS"
      for lib in libcuda libnvidia-ml libnvidia-ptxjitcompiler; do
        for f in /lib/x86_64-linux-gnu/''${lib}.so*; do
          [ -e "$f" ] && ln -sfn "$f" "$NVIDIA_DRIVER_LIBS/$(basename "$f")"
        done
      done
      export LD_LIBRARY_PATH="$NVIDIA_DRIVER_LIBS''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    fi

    # OpenTofu alias
    alias tf=tofu

    echo "signals-360 development environment"
    echo ""
    echo "Secrets: secretspec.toml (provider=dotenv via devenv.yaml) — see docs/operations/secrets.md"
    echo "  secretspec run -- <cmd>   # inject declared secrets without shell export"
    echo ""
    echo "Core services (start with 'devenv up'):"
    echo "  PostgreSQL 16     — port 5455, extensions: age, pg_cron"
    echo "  Kerberos KDC      — realm: DEV.VISTA.ZNDX.ORG, host: tinybox.dev.vista.zndx.org, port: 8848"
    echo "  Atlas             — http://localhost:21010 (AGE backend → signals DB)"
    echo "  Ranger Admin      — http://localhost:6080 (when configured)"
    echo "  Kudu Master       — localhost:7051 (web UI: 8051)"
    echo "  Kudu TServer      — localhost:7050 (web UI: 8050)"
    echo "  Kudu Kerberos     — SIGNALS_KUDU_KERBEROS=0|1 (PR-K5a; default 0)"
    echo "  Impala Statestore — localhost:24000 (web UI: 25010)"
    echo "  Impala Catalogd   — localhost:26000 (web UI: 25020, HMS-free)"
    echo "  Impala Daemon     — hs2://localhost:21050 (web UI: 25000)"
    echo ""
    echo "Connect: jdbc:hive2://localhost:21050/default;auth=noSasl"
    echo ""
    echo "Build tasks:"
    echo "  devenv tasks run kudu:build-cpp       — Build Kudu C++ binaries"
    echo "  devenv tasks run kudu:install-java    — Kudu Java client → \$SIG_MAVEN_REPO"
    echo "  devenv tasks run impala:bootstrap     — Download Impala toolchain (no CDP Ranger)"
    echo "  devenv tasks run impala:build         — Full Impala build (C++ + Java)"
    echo "  devenv tasks run impala:build-fe      — Incremental Java frontend build"
    echo "  devenv tasks run impala:test-fe       — Run Impala FE unit tests"
    echo "  devenv tasks run atlas:build          — Build Atlas webapp (AGE)"
    echo "  devenv tasks run ranger:build         — Ranger → .devenv/m2 + distro"
    echo "  devenv tasks run ranger:install       — .devenv/ranger/admin"
    echo "  devenv tasks run ranger:setup         — setup.sh → Postgres ranger DB"
    echo ""
    echo "Maven: SIG_MAVEN_REPO=\$SIG_MAVEN_REPO (project-local; not ~/.m2)"
    echo ""
    echo "Utility tasks:"
    echo "  devenv tasks run sigint:resolve-config — Resolve config to build/config/sigint.env"
    echo "  devenv tasks run sigint:cache-models   — Pre-download models for offline use"
    echo "  devenv tasks run signals:kdc-init     — Initialize KDC"
    echo "  devenv tasks run signals:kdc-reset    — Reset KDC database"
    echo "  devenv tasks run signals:kudu-kerberos-smoke — PR-K5a keytab/auth probe"
    echo "  devenv tasks run signals:catalog-init — Initialize catalog registry schema"
    echo "  devenv tasks run hms:install          — Download Hive Standalone Metastore"
    echo "  devenv tasks run hms:init-schema      — Initialize HMS schema in PostgreSQL"
    echo "  devenv tasks run polaris:install       — Build and install Polaris"
    echo "  devenv tasks run docs:build           — Build documentation"
    echo "  devenv tasks run docs:serve           — Serve docs with live reload"
  '';

  # ── Tests ──────────────────────────────────────────────────────────────────
  enterTest = ''
    echo "=== Waiting for stack health ==="
    python3 scripts/wait_for_stack.py --stale-timeout 300

    echo ""
    echo "=== Tier-0: Component Health ==="
    uv run behave features/ --tags=@tier-0 --no-capture

    echo ""
    echo "=== Tier-1: Integration Tests ==="
    uv run behave features/ --tags=@tier-1 --no-capture

    echo ""
    echo "=== Running Impala FE unit tests ==="
    cd components/impala
    source bin/impala-config.sh
    mvn test -pl fe \
      -Dtest="ConfigLoaderTest,KuduMetaProviderTest,SignalsDdlExecutorTest" \
      -DfailIfNoTests=false --no-transfer-progress
  '';
}
