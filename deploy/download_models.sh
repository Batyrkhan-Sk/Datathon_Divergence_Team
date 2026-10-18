#!/usr/bin/env bash
# One-time download of the open model weights into hf_cache/ (run from the project root,
# needs internet). After this the service runs offline (HF_HUB_OFFLINE=1 in run_server.sh).
# RT-DETRv2 + OWLv2 are small; the VLM is Qwen3-VL-8B (~17 GB) on a GPU with >= 20 GB,
# otherwise Qwen3-VL-2B. Set VLM_MODEL to force one, or ML_USE_VLM=0 to skip it.
set -euo pipefail
cd "$(dirname "$0")/.."
export HF_HOME="$PWD/hf_cache"
export HF_HUB_OFFLINE=0
env/bin/python - <<'EOF'
import os
from huggingface_hub import snapshot_download

models = ["PekingU/rtdetr_v2_r18vd", "google/owlv2-base-patch16-ensemble"]
if os.environ.get("ML_USE_VLM", "1") == "1":
    from ml.perception.vlm import _choose
    models.append(_choose())
for mid in models:
    print("downloading", mid, flush=True)
    snapshot_download(mid)
print("done:", ", ".join(models))
EOF
