{ pkgs, lib, config, inputs, ... }:

{
  dotenv.enable = true;

  # ── Packages ───────────────────────────────────────────────────────────────
  packages = with pkgs; [
    # Core
    git
    gh
    jq

    # Kerberos / Security
    krb5
    cyrus_sasl
    openssl

    # ASF build dependencies (Kudu, Impala)
    cmake
    ninja
    gcc
    protobuf
    flatbuffers

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
  env = {
    KRB5_REALM = "KRBTEST.COM";
    KRB5_KDC_PORT = "8848";
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
      { name = "signals"; }
      { name = "hive_metastore"; }
      { name = "polaris"; }
      { name = "signals_catalog"; }
    ];
    initialScript = ''
      CREATE EXTENSION IF NOT EXISTS age;
      LOAD 'age';
      SET search_path = ag_catalog, "$user", public;
      CREATE EXTENSION IF NOT EXISTS pg_cron;
      CREATE EXTENSION IF NOT EXISTS pg_trgm;
    '';
  };

  # ── KDC Process ────────────────────────────────────────────────────────────
  processes.kdc.exec = ''
    # Initialize KDC if needed
    bash scripts/kdc-init.sh

    KDC_DIR="$PWD/.devenv/kdc"

    echo "Starting KDC on 127.0.0.1:''${KRB5_KDC_PORT:-8848}..."
    exec env \
      KRB5_CONFIG="$KDC_DIR/krb5.conf" \
      KRB5_KDC_PROFILE="$KDC_DIR/kdc.conf" \
      krb5kdc -n
  '';

  # ── Atlas Process ────────────────────────────────────────────────────────
  processes.atlas.exec = ''
    ATLAS_DIR="$PWD/components/atlas"
    ATLAS_WEBAPP="$ATLAS_DIR/webapp/target/atlas-webapp-3.0.0-SNAPSHOT"
    ATLAS_CONF="$PWD/config/atlas"
    ATLAS_HOME="$PWD/.devenv/atlas"

    mkdir -p "$ATLAS_HOME/data" "$ATLAS_HOME/logs" "$ATLAS_HOME/conf"

    # Copy credentials/authz to atlas home conf for runtime resolution
    cp -n "$ATLAS_CONF/users-credentials.properties" "$ATLAS_HOME/conf/" 2>/dev/null || true
    cp -n "$ATLAS_CONF/atlas-simple-authz-policy.json" "$ATLAS_HOME/conf/" 2>/dev/null || true

    if [ ! -d "$ATLAS_WEBAPP/WEB-INF" ]; then
      echo "Atlas webapp not built. Run: devenv tasks run atlas:build"
      exit 1
    fi

    echo "Starting Atlas on http://localhost:21000..."
    exec java \
      -Datlas.home="$ATLAS_HOME" \
      -Datlas.conf="$ATLAS_CONF" \
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
      -cp "$ATLAS_CONF:$ATLAS_WEBAPP/WEB-INF/classes:$ATLAS_WEBAPP/WEB-INF/lib/*" \
      org.apache.atlas.Atlas \
      -app "$ATLAS_WEBAPP" \
      -port 21000
  '';

  # ── HMS Process (Hive Standalone Metastore) ──────────────────────────────
  processes.hms.exec = ''
    HMS_HOME="$PWD/.devenv/hms"
    HMS_CONF="$PWD/config/hms"

    if [ ! -d "$HMS_HOME/lib" ]; then
      echo "HMS not installed. Run: devenv tasks run hms:install"
      exit 1
    fi

    mkdir -p /tmp/signals-warehouse

    echo "Starting Hive Metastore on thrift://localhost:9083..."
    exec java \
      --add-opens java.base/java.lang=ALL-UNNAMED \
      --add-opens java.base/java.lang.reflect=ALL-UNNAMED \
      --add-opens java.base/java.net=ALL-UNNAMED \
      --add-opens java.base/java.util=ALL-UNNAMED \
      -Djavax.jdo.option.ConnectionURL=jdbc:postgresql://localhost:5455/hive_metastore \
      -Djavax.jdo.option.ConnectionDriverName=org.postgresql.Driver \
      -server -Xmx512m \
      -cp "$HMS_CONF:$HMS_HOME/lib/*" \
      org.apache.hadoop.hive.metastore.HiveMetaStore \
      -p 9083
  '';

  # ── Polaris Process (Iceberg REST Catalog) ───────────────────────────────
  processes.polaris.exec = ''
    POLARIS_HOME="$PWD/.devenv/polaris"
    POLARIS_CONF="$PWD/config/polaris"

    if [ ! -f "$POLARIS_HOME/polaris-quarkus-server.jar" ] && [ ! -d "$POLARIS_HOME/lib" ]; then
      echo "Polaris not installed. Run: devenv tasks run polaris:install"
      exit 1
    fi

    echo "Starting Polaris (Iceberg REST Catalog) on http://localhost:8181..."
    if [ -f "$POLARIS_HOME/polaris-quarkus-server.jar" ]; then
      exec java \
        -DPOLARIS_PERSISTENCE_TYPE=relational-jdbc \
        -DQUARKUS_DATASOURCE_DB_KIND=postgresql \
        -DQUARKUS_DATASOURCE_JDBC_URL=jdbc:postgresql://localhost:5455/polaris \
        -DQUARKUS_HTTP_PORT=8181 \
        -jar "$POLARIS_HOME/polaris-quarkus-server.jar"
    else
      exec java \
        -DPOLARIS_PERSISTENCE_TYPE=relational-jdbc \
        -DQUARKUS_DATASOURCE_DB_KIND=postgresql \
        -DQUARKUS_DATASOURCE_JDBC_URL=jdbc:postgresql://localhost:5455/polaris \
        -DQUARKUS_HTTP_PORT=8181 \
        -cp "$POLARIS_CONF:$POLARIS_HOME/lib/*" \
        org.apache.polaris.service.PolarisApplication
    fi
  '';

  # ── Kudu Master Process ──────────────────────────────────────────────────
  processes.kudu-master.exec = ''
    KUDU_HOME="$PWD/.devenv/kudu"
    KUDU_BUILD="$HOME/local/src/asf/kudu/build/latest"

    if [ ! -f "$KUDU_BUILD/bin/kudu-master" ]; then
      echo "Kudu not built. Build from $HOME/local/src/asf/kudu"
      exit 1
    fi

    mkdir -p "$KUDU_HOME/master/data" "$KUDU_HOME/master/wal" "$KUDU_HOME/master/logs"

    echo "Starting Kudu Master on localhost:7051..."
    exec "$KUDU_BUILD/bin/kudu-master" \
      --fs_data_dirs="$KUDU_HOME/master/data" \
      --fs_wal_dir="$KUDU_HOME/master/wal" \
      --log_dir="$KUDU_HOME/master/logs" \
      --webserver_port=8051 \
      --rpc_bind_addresses=127.0.0.1:7051 \
      --unlock_unsafe_flags \
      --default_num_replicas=1
  '';

  # ── Kudu Tablet Server Process ───────────────────────────────────────────
  processes.kudu-tserver.exec = ''
    KUDU_HOME="$PWD/.devenv/kudu"
    KUDU_BUILD="$HOME/local/src/asf/kudu/build/latest"

    if [ ! -f "$KUDU_BUILD/bin/kudu-tserver" ]; then
      echo "Kudu not built. Build from $HOME/local/src/asf/kudu"
      exit 1
    fi

    mkdir -p "$KUDU_HOME/tserver/data" "$KUDU_HOME/tserver/wal" "$KUDU_HOME/tserver/logs"

    # Wait for master to be ready
    sleep 3

    echo "Starting Kudu Tablet Server..."
    exec "$KUDU_BUILD/bin/kudu-tserver" \
      --fs_data_dirs="$KUDU_HOME/tserver/data" \
      --fs_wal_dir="$KUDU_HOME/tserver/wal" \
      --log_dir="$KUDU_HOME/tserver/logs" \
      --tserver_master_addrs=127.0.0.1:7051 \
      --webserver_port=8050 \
      --rpc_bind_addresses=127.0.0.1:7050 \
      --unlock_unsafe_flags
  '';

  # ── Impala Runtime Environment ────────────────────────────────────────
  # Impala binaries were built with toolchain GCC 10.4.0 but link against
  # Nix-provided SASL (glibc 2.42) and JVM. We use Nix's ld-linux as the
  # explicit interpreter so that Nix libraries (which need glibc 2.42) work
  # alongside system libraries (which only need glibc ≤2.35, backward-
  # compatible with 2.42). LD_LIBRARY_PATH ordering is critical: Nix glibc
  # must come FIRST so libc.so.6 resolves to glibc 2.42.

  # ── Impala Statestore Process ───────────────────────────────────────────
  processes.impala-statestore.exec = ''
    IMPALA_HOME="$PWD/components/impala"
    source "$IMPALA_HOME/bin/impala-config.sh"
    . "$IMPALA_HOME/bin/set-ld-library-path.sh"

    # Nix/system hybrid LD_LIBRARY_PATH (order matters — Nix glibc FIRST)
    NIX_GLIBC="${pkgs.glibc}/lib"
    GCC_LIB64="$IMPALA_TOOLCHAIN_PACKAGES_HOME/gcc-10.4.0/lib64"
    NIX_KRB5="${pkgs.krb5.lib}/lib"
    export LD_LIBRARY_PATH="$NIX_GLIBC:$GCC_LIB64:$NIX_KRB5:$LD_LIBRARY_PATH:/lib/x86_64-linux-gnu"

    mkdir -p "$PWD/.devenv/impala/statestore/logs"

    echo "Starting Impala Statestore on port 24000..."
    exec ${pkgs.glibc}/lib/ld-linux-x86-64.so.2 \
      "$IMPALA_HOME/be/build/latest/service/statestored" \
      --state_store_port=24000 \
      --webserver_port=25010 \
      --log_dir="$PWD/.devenv/impala/statestore/logs" \
      --hostname=localhost
  '';

  # ── Impala Catalog Server Process ─────────────────────────────────────
  processes.impala-catalogd.exec = ''
    IMPALA_HOME="$PWD/components/impala"
    source "$IMPALA_HOME/bin/impala-config.sh"
    . "$IMPALA_HOME/bin/set-classpath.sh"
    . "$IMPALA_HOME/bin/set-ld-library-path.sh"

    # Nix/system hybrid LD_LIBRARY_PATH (order matters — Nix glibc FIRST)
    NIX_GLIBC="${pkgs.glibc}/lib"
    GCC_LIB64="$IMPALA_TOOLCHAIN_PACKAGES_HOME/gcc-10.4.0/lib64"
    NIX_KRB5="${pkgs.krb5.lib}/lib"
    export LD_LIBRARY_PATH="$NIX_GLIBC:$GCC_LIB64:$NIX_KRB5:$LD_LIBRARY_PATH:/lib/x86_64-linux-gnu"

    mkdir -p "$PWD/.devenv/impala/catalogd/logs"

    # Wait for statestore
    sleep 3

    echo "Starting Impala Catalog Server on port 26000..."
    exec ${pkgs.glibc}/lib/ld-linux-x86-64.so.2 \
      "$IMPALA_HOME/be/build/latest/service/catalogd" \
      --catalog_service_port=26000 \
      --state_store_subscriber_port=23020 \
      --state_store_host=localhost \
      --state_store_port=24000 \
      --webserver_port=25020 \
      --log_dir="$PWD/.devenv/impala/catalogd/logs" \
      --hostname=localhost \
      --kudu_master_hosts=127.0.0.1:7051 \
      --hive_metastore_uris=thrift://localhost:9083
  '';

  # ── Impala Daemon Process ─────────────────────────────────────────────
  processes.impala-impalad.exec = ''
    IMPALA_HOME="$PWD/components/impala"
    source "$IMPALA_HOME/bin/impala-config.sh"
    . "$IMPALA_HOME/bin/set-classpath.sh"
    . "$IMPALA_HOME/bin/set-ld-library-path.sh"

    # Nix/system hybrid LD_LIBRARY_PATH (order matters — Nix glibc FIRST)
    NIX_GLIBC="${pkgs.glibc}/lib"
    GCC_LIB64="$IMPALA_TOOLCHAIN_PACKAGES_HOME/gcc-10.4.0/lib64"
    NIX_KRB5="${pkgs.krb5.lib}/lib"
    export LD_LIBRARY_PATH="$NIX_GLIBC:$GCC_LIB64:$NIX_KRB5:$LD_LIBRARY_PATH:/lib/x86_64-linux-gnu"

    mkdir -p "$PWD/.devenv/impala/impalad/logs"

    # Wait for catalogd
    sleep 5

    echo "Starting Impala Daemon on hs2://localhost:21050..."
    exec ${pkgs.glibc}/lib/ld-linux-x86-64.so.2 \
      "$IMPALA_HOME/be/build/latest/service/impalad" \
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
      --default_fs=file:///tmp/signals-warehouse
  '';

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

    "signals:catalog-init" = {
      exec = ''
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
        cd components/atlas
        # Create empty apidocs dir so WAR plugin succeeds when enunciate is skipped
        mkdir -p webapp/target/api/v2/apidocs/ui
        mvn package -pl webapp -am -Dmaven.test.skip=true -DskipUTs=true \
          -DGRAPH-PROVIDER=age -Dcheckstyle.skip=true -DskipEnunciate=true \
          --no-transfer-progress
      '';
      description = "Build Atlas webapp with AGE backend";
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
        cd "$HOME/local/src/asf/kudu/java"
        ./gradlew :kudu-client:publishToMavenLocal
      '';
      description = "Install Kudu Java client to local Maven repo";
    };

    "kudu:build-cpp" = {
      exec = ''
        KUDU_SRC="$HOME/local/src/asf/kudu"
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
        cmake -DCMAKE_BUILD_TYPE=Release -GNinja -DNO_TESTS=1 ../..
        ninja kudu-master kudu-tserver
        ln -sfn "$KUDU_SRC/build/release" "$KUDU_SRC/build/latest"
      '';
      description = "Build Kudu C++ master and tserver binaries";
    };

    "impala:bootstrap" = {
      exec = ''
        cd components/impala
        source bin/impala-config.sh
        python3 bin/bootstrap_toolchain.py
      '';
      description = "Download Impala toolchain (~5-10 GB)";
    };

    "impala:build" = {
      exec = ''
        cd components/impala
        source bin/impala-config.sh
        ./buildall.sh -notests -noclean
      '';
      description = "Full Impala build (C++ backend + Java frontend)";
    };

    "impala:build-fe" = {
      exec = ''
        cd components/impala
        source bin/impala-config.sh
        cd java && mvn compile -pl ../fe -am -DskipTests --no-transfer-progress
      '';
      description = "Incremental Impala frontend build (Java only)";
    };

    "impala:test-fe" = {
      exec = ''
        cd components/impala
        source bin/impala-config.sh
        mvn test -pl fe \
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

    # Kudu build location
    export KUDU_BUILD="$HOME/local/src/asf/kudu/build/latest"

    # OpenTofu alias
    alias tf=tofu

    echo "signals-360 development environment"
    echo ""
    echo "Services (start with 'devenv up'):"
    echo "  PostgreSQL 16    — extensions: age, pg_cron (port 5455)"
    echo "  Kerberos KDC     — realm: KRBTEST.COM, port: 8848"
    echo "  Atlas            — http://localhost:21000 (AGE backend)"
    echo "  HMS              — thrift://localhost:9083 (PostgreSQL backend)"
    echo "  Polaris          — http://localhost:8181 (Iceberg REST catalog)"
    echo "  Kudu Master      — localhost:7051 (web UI: 8051)"
    echo "  Kudu TServer     — localhost:7050 (web UI: 8050)"
    echo "  Impala Statestore — localhost:24000 (web UI: 25010)"
    echo "  Impala Catalogd  — localhost:26000 (web UI: 25020)"
    echo "  Impala Daemon    — hs2://localhost:21050, beeswax://localhost:21001 (web UI: 25000)"
    echo ""
    echo "Tasks:"
    echo "  devenv tasks run atlas:build          — Build Atlas webapp (AGE)"
    echo "  devenv tasks run hms:install          — Download Hive Standalone Metastore"
    echo "  devenv tasks run hms:init-schema      — Initialize HMS schema in PostgreSQL"
    echo "  devenv tasks run polaris:install       — Build and install Polaris"
    echo "  devenv tasks run kudu:install-java    — Install Kudu Java client to Maven"
    echo "  devenv tasks run kudu:build-cpp       — Build Kudu C++ binaries"
    echo "  devenv tasks run impala:bootstrap     — Download Impala toolchain (~5-10 GB)"
    echo "  devenv tasks run impala:build         — Full Impala build (C++ + Java)"
    echo "  devenv tasks run impala:build-fe      — Incremental Java frontend build"
    echo "  devenv tasks run impala:test-fe       — Run signals FE unit tests"
    echo "  devenv tasks run signals:catalog-init — Initialize catalog registry schema"
    echo "  devenv tasks run signals:kdc-init     — Initialize KDC"
    echo "  devenv tasks run signals:kdc-reset    — Reset KDC database"
    echo "  devenv tasks run docs:build           — Build documentation"
    echo "  devenv tasks run docs:serve           — Serve docs with live reload"
  '';

  # ── Tests ──────────────────────────────────────────────────────────────────
  enterTest = ''
    echo "Running tests"
    git --version | grep --color=auto "${pkgs.git.version}"
  '';
}
