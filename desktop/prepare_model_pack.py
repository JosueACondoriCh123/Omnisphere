"""Download pinned public model artifacts into an offline, hash-checked pack."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from huggingface_hub import hf_hub_download

WHISPER_REPO = "Systran/faster-whisper-small"
WHISPER_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
WHISPER_FILES = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")
GEMMA_REPO = "google/gemma-4-E2B-it-qat-q4_0-gguf"
GEMMA_REVISION = "675cff42a74c774d6cb76f76d8eacb49b48c9b93"
GEMMA_FILE = "gemma-4-E2B_q4_0-it.gguf"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare(destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    files = []
    for filename in WHISPER_FILES:
        target = Path(hf_hub_download(
            WHISPER_REPO, filename, revision=WHISPER_REVISION,
            local_dir=destination / "faster-whisper",
        ))
        files.append({"path": f"faster-whisper/{filename}", "size": target.stat().st_size,
                      "sha256": sha256(target)})
    downloaded = Path(hf_hub_download(
        GEMMA_REPO, GEMMA_FILE, revision=GEMMA_REVISION, local_dir=destination,
    ))
    target = destination / "gemma-4-e2b-q4.gguf"
    if downloaded != target:
        downloaded.replace(target)
    files.append({"path": target.name, "size": target.stat().st_size, "sha256": sha256(target)})
    manifest = {
        "format": 1,
        "models": {
            "asr": {"repo": WHISPER_REPO, "revision": WHISPER_REVISION, "license": "MIT"},
            "translation": {"repo": GEMMA_REPO, "revision": GEMMA_REVISION,
                            "license": "Apache-2.0", "source_file": GEMMA_FILE},
        },
        "files": files,
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("desktop/model-pack"))
    args = parser.parse_args()
    result = prepare(args.out)
    print(f"Prepared {len(result['files'])} files in {args.out.resolve()}")
