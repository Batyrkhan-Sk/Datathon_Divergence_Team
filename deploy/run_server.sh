#!/usr/bin/env bash
# Start the jury-facing service on the GPU server (run from the project root).
# Needs API_KEY in .env (root of the project). Logs: logs/service.log
set -euo pipefail
cd "$(dirname "$0")/.."
export HF_HOME="$PWD/hf_cache"           # models live inside the project folder
export HF_HUB_OFFLINE=1                  # weights are already downloaded: no internet needed
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-1}"
export ML_USE_VLM="${ML_USE_VLM:-1}"
export ANALYZER="${ANALYZER:-real}"
export PORT="${PORT:-8000}"
export HOST="${HOST:-127.0.0.1}"          # reachable only through the tunnel
exec env/bin/python -m backend
