#!/usr/bin/env python3
"""
Download Nemotron-3-Super-120B-Instruct (UD-Q4_K_XL) to the RunPod network volume.

Run this once to seed the volume before first deploy:
    HF_TOKEN=hf_... python download_model.py

The model (~60 GB) must be present at /workspace/models before the endpoint
starts, otherwise the cold-start will timeout trying to download during inference.
"""

import os
import sys

from huggingface_hub import snapshot_download

REPO_ID = "unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF"
ALLOW_PATTERNS = ["*UD-Q4_K_XL*"]
LOCAL_DIR = "/workspace/models"


def main():
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print(
            "Error: HF_TOKEN environment variable not set. "
            "Get your token from https://huggingface.co/settings/tokens"
        )
        sys.exit(1)

    print(f"Repo:        {REPO_ID}")
    print(f"Pattern:     {ALLOW_PATTERNS[0]}")
    print(f"Destination: {LOCAL_DIR}")
    print()
    print("Starting download — this is ~60 GB and will take a while...")

    downloaded_path = snapshot_download(
        repo_id=REPO_ID,
        allow_patterns=ALLOW_PATTERNS,
        local_dir=LOCAL_DIR,
        token=hf_token,
    )

    print()
    print(f"Download complete: {downloaded_path}")
    print()
    print("Next step: Now run: flash deploy nemotron.py")


if __name__ == "__main__":
    main()
