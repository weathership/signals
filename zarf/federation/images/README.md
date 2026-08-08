# minifi-sentinel image

Build from `components/minifi-cpp` (weathership/oss-minifi-cpp).

```bash
# Sketch — freeze tag in BOOTSTRAP_VERSIONS.txt and zarf.yaml images: list
podman build -t localhost:5555/minifi-sentinel:0.1.0-dev \
  -f zarf/federation/images/Dockerfile.minifi-sentinel \
  components/minifi-cpp
```

Air-gap: load into Zarf registry during `package create` / package component
`minifi-sentinel-images`. No public pull on the closed node.
