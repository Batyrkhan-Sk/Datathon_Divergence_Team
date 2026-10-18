#!/usr/bin/env bash
# Start the jury-facing service on the GPU server (run from the project root).
# Needs API_KEY in .env (root of the project). Logs: logs/service.log
set -euo pipefail
cd "$(dirname "$0")/.."
export HF_HOME="$PWD/hf_cache"           # models live inside the project folder
# Offline once the weights are in hf_cache/ (deploy/download_models.sh); on a fresh clone
# without them, allow the one-time download at start-up.
if [ -d hf_cache/hub ]; then export HF_HUB_OFFLINE=1; else export HF_HUB_OFFLINE=0; fi
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-1}"
export ML_USE_VLM="${ML_USE_VLM:-1}"
export ANALYZER="${ANALYZER:-real}"
export PORT="${PORT:-8000}"
export HOST="${HOST:-127.0.0.1}"          # reachable only through the tunnel
exec env/bin/python -m backend
