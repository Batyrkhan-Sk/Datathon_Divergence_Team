#!/usr/bin/env bash
# Keep the service and the tunnel running: restart either if it dies or stops answering.
# Run once from the project root:  nohup bash deploy/watchdog.sh > logs/watchdog.log 2>&1 &
# Logs: logs/service.log, logs/tunnel.log, logs/watchdog.log. Current URL: logs/public_url.txt
cd "$(dirname "$0")/.."
mkdir -p logs

start_service() {
  echo "$(date '+%F %T') starting service"
  setsid bash deploy/run_server.sh >> logs/service.log 2>&1 < /dev/null &
  echo $! > logs/service.pid
}
start_tunnel() {
  echo "$(date '+%F %T') starting tunnel"
  setsid bash deploy/run_tunnel.sh >> logs/tunnel.log 2>&1 < /dev/null &
  echo $! > logs/tunnel.pid
}
alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

while true; do
  # Service: process alive and health endpoint answering (allow ~2 min for model loading)
  if ! alive logs/service.pid; then
    start_service; sleep 120
  elif ! curl -s --max-time 10 "http://localhost:${PORT:-8000}/api/v1/health" | grep -q '"status":"ok"'; then
    echo "$(date '+%F %T') health check failed; restarting service"
    kill "$(cat logs/service.pid)" 2>/dev/null; sleep 5; start_service; sleep 120
  fi
  # Tunnel: process alive; record the public URL whenever it changes
  if ! alive logs/tunnel.pid; then
    start_tunnel; sleep 20
  fi
  url=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' logs/tunnel.log | tail -1)
  if [ -n "$url" ] && [ "$url" != "$(cat logs/public_url.txt 2>/dev/null)" ]; then
    echo "$url" > logs/public_url.txt
    echo "$(date '+%F %T') public URL: $url"
  fi
  sleep 30
done
