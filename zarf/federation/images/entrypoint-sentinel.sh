#!/bin/sh
# Health TCP/HTTP on FEDERATION_HEALTH_PORT + MiNiFi agent.
set -eu
PORT="${FEDERATION_HEALTH_PORT:-8080}"
cd "${MINIFI_HOME:-/opt/minifi/minifi-current}"

python3 - <<PY &
import os, socket, threading, time
port = int(os.environ.get("FEDERATION_HEALTH_PORT", "8080"))
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("0.0.0.0", port))
s.listen(16)

def serve():
    while True:
        c, _ = s.accept()
        try:
            c.recv(1024)
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        finally:
            c.close()

threading.Thread(target=serve, daemon=True).start()
while True:
    time.sleep(3600)
PY
HEALTH_PID=$!

if [ -x ./bin/minifi.sh ]; then
  ./bin/minifi.sh run &
  MINIFI_PID=$!
  # Exit if either dies
  while kill -0 "$MINIFI_PID" 2>/dev/null && kill -0 "$HEALTH_PID" 2>/dev/null; do
    sleep 5
  done
  kill "$MINIFI_PID" "$HEALTH_PID" 2>/dev/null || true
  wait || true
  exit 1
fi

wait "$HEALTH_PID"
