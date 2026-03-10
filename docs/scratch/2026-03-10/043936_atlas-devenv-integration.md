# Atlas AGE Backend — devenv Integration

## What was done

Built on the AGE backend compilation work (see `042100_atlas-age-backend-compilation.md`)
to make Atlas runnable as a `devenv up` process with the AGE/PostgreSQL backend.

### Changes

1. **`components/atlas/distro/pom.xml`** — Added `graph-provider-age` profile
   - Activated by `-DGRAPH-PROVIDER=age` (same flag used in compile step)
   - Sets storage/index backends to `age`, disables HBase/Solr/Cassandra/Elasticsearch
   - Uses `NoopEntityAuditRepository` (no HBase for audit)

2. **`config/atlas/atlas-application.properties`** — Runtime config for AGE backend
   - Points to devenv PostgreSQL (`localhost:5432/signals`)
   - Embedded Kafka for notifications (ports 9026/9027)
   - File-based auth (admin/admin), simple authorizer
   - No Kerberos, no TLS, no HBase audit

3. **`config/atlas/users-credentials.properties`** — Copied from distro/src/conf
   - admin/admin (SHA-256 hashed)

4. **`config/atlas/atlas-simple-authz-policy.json`** — Copied from distro/src/conf
   - ROLE_ADMIN, DATA_SCIENTIST, DATA_STEWARD roles

5. **`devenv.nix`** — Three additions:
   - `processes.atlas` — Runs Atlas via `java -cp` with expanded WAR on classpath
   - `tasks."atlas:build"` — `mvn package -pl webapp -am -DskipTests -DGRAPH-PROVIDER=age`
   - Updated `enterShell` banner with Atlas service and build task

### Build issues resolved

Three issues hit during `mvn package -pl webapp -am`:

1. **Test compilation failure** — Repository module tests import JanusGraph/Solr/Elasticsearch
   classes not present with AGE profile. Fix: `-Dmaven.test.skip=true` to skip test compilation.

2. **Enunciate plugin failure** — `enunciate-maven-plugin:2.13.2` uses `com.sun.tools.javac.api`
   which is blocked by JDK 21 module system (`IllegalAccessError`). Fix: `-DskipEnunciate=true`.

3. **WAR plugin failure** — Expects `target/api/v2/apidocs/ui` directory created by enunciate.
   Fix: `mkdir -p webapp/target/api/v2/apidocs/ui` before build.

4. **intg module tests still running** — Atlas parent POM surefire config has
   `<skip>${skipUTs}</skip>` which overrides standard `maven.test.skip`.
   Fix: `-DskipUTs=true`.

Final working build command:
```bash
cd components/atlas
mkdir -p webapp/target/api/v2/apidocs/ui
mvn package -pl webapp -am -Dmaven.test.skip=true -DskipUTs=true \
  -DGRAPH-PROVIDER=age -Dcheckstyle.skip=true -DskipEnunciate=true \
  --no-transfer-progress
```

### How it works

```
devenv tasks run atlas:build   # Build webapp (~2 min)
devenv up                      # Starts PostgreSQL → KDC → Atlas
```

Atlas runs in foreground (not daemonized) via `org.apache.atlas.Atlas` main class
with the expanded WAR directory on the classpath. Runtime data goes to `.devenv/atlas/`
(gitignored via `.devenv*` pattern).

WAR contains all three graphdb jars:
- `atlas-graphdb-age-3.0.0-SNAPSHOT.jar`
- `atlas-graphdb-api-3.0.0-SNAPSHOT.jar`
- `atlas-graphdb-common-3.0.0-SNAPSHOT.jar`

### Verification steps

1. `devenv shell` — no Nix errors
2. `devenv tasks run atlas:build` — full webapp build
3. `devenv up` — all three services start
4. `curl -u admin:admin http://localhost:21000/api/atlas/v2/types/typedefs/headers`
5. Atlas UI at http://localhost:21000
