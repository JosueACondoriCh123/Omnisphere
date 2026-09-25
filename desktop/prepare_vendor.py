"""Pin Windows runtime binaries from published release archives."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor"
ARCHIVES = (
    ("mediamtx", "v1.21.1", "MIT",
     ("https://github.com/bluenviron/mediamtx/releases/download/v1.21.1/"
      "mediamtx_v1.21.1_windows_amd64.zip")),
    ("ffmpeg", "9.0 LGPL shared", "LGPL-2.1-or-later",
     ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
      "ffmpeg-n9.0-latest-win64-lgpl-shared-9.0.zip")),
    ("llama", "b11149 CUDA 12.4", "MIT",
     ("https://github.com/ggml-org/llama.cpp/releases/download/b11149/"
      "llama-b11149-bin-win-cuda-12.4-x64.zip")),
    ("cuda", "b11149 CUDA 12.4", "NVIDIA CUDA runtime",
     ("https://github.com/ggml-org/llama.cpp/releases/download/b11149/"
      "cudart-llama-bin-win-cuda-12.4-x64.zip")),
)
ARCHIVE_SHA256 = {
    "mediamtx": "faa97974861eb75a68b5aa326c78e7e7a6f670b5ef191bace78e715130381f23",
    "ffmpeg": "16e3e99dc13cd31ae1ee2130f4d8e5213d1d08891833c3da03cb5f8d7edc4682",
    "llama": "d3140fe21ab2e665a706ca27923b27ca264f1c564b5837abea4566cc49c16096",
    "cuda": "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
}
REQUIRED = {"mediamtx.exe", "ffmpeg.exe", "llama-server.exe"}
CTRANSLATE2_VERSION = "4.8.2"
CUDNN_SHA256 = "9edbcdff73b0af070eb160b2ce66e59feca04aa017351d8eedcc5e8e149967d2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare() -> None:
    if VENDOR.exists() and any(VENDOR.iterdir()):
        raise RuntimeError(f"{VENDOR} already contains files; remove or archive it explicitly first")
    VENDOR.mkdir(exist_ok=True)
    manifest: dict[str, dict[str, str | int]] = {}
    with tempfile.TemporaryDirectory(prefix="omnistage-vendor-") as scratch:
        temporary = Path(scratch)
        for name, version, license_name, url in ARCHIVES:
            archive_path = temporary / f"{name}.zip"
            print(f"Downloading {name} {version}...", flush=True)
            with urllib.request.urlopen(url, timeout=60) as response, archive_path.open("wb") as target:
                while block := response.read(4 * 1024 * 1024):
                    target.write(block)
            archive_hash = sha256(archive_path)
            if archive_hash != ARCHIVE_SHA256[name]:
                raise RuntimeError(f"{name} archive SHA256 changed: {archive_hash}")
            with zipfile.ZipFile(archive_path) as archive:
                for item in archive.infolist():
                    basename = Path(item.filename).name
                    if item.is_dir() or basename.lower() not in REQUIRED and not basename.lower().endswith(".dll"):
                        continue
                    destination = VENDOR / basename
                    if destination.exists():
                        raise RuntimeError(f"Collision between release archives: {basename}")
                    with archive.open(item) as source, destination.open("wb") as output:
                        while block := source.read(4 * 1024 * 1024):
                            output.write(block)
                    manifest[basename] = {
                        "version": version, "source": url, "archive_sha256": archive_hash,
                        "license": license_name, "sha256": sha256(destination),
                        "size": destination.stat().st_size,
                    }
    if not REQUIRED.issubset(manifest):
        raise RuntimeError(f"Release archives missing required executables: {sorted(REQUIRED - manifest.keys())}")
    distribution = importlib.metadata.distribution("ctranslate2")
    if distribution.version != CTRANSLATE2_VERSION:
        raise RuntimeError(f"Expected CTranslate2 {CTRANSLATE2_VERSION}, got {distribution.version}")
    cudnn_source = Path(distribution.locate_file("ctranslate2/cudnn64_9.dll"))
    if not cudnn_source.is_file() or sha256(cudnn_source) != CUDNN_SHA256:
        raise RuntimeError("Pinned CTranslate2 cuDNN DLL is missing or changed")
    cudnn_target = VENDOR / "cudnn64_9.dll"
    shutil.copyfile(cudnn_source, cudnn_target)
    manifest[cudnn_target.name] = {
        "version": "CTranslate2 4.8.2 / cuDNN 9.10.2.21",
        "source": "https://pypi.org/project/ctranslate2/4.8.2/",
        "package_record_sha256": CUDNN_SHA256,
        "license": "NVIDIA cuDNN redistribution terms",
        "sha256": CUDNN_SHA256,
        "size": cudnn_target.stat().st_size,
    }
    (VENDOR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Prepared {len(manifest)} verified Windows runtime files in {VENDOR}")


if __name__ == "__main__":
    prepare()
