"""Script de descarga, recorte y preparación del corpus de audio para Nerdearla.

Utiliza yt-dlp y ffmpeg para extraer segmentos específicos en formato 16kHz mono WAV.
Si yt-dlp no está disponible o no hay conexión, permite generar fixtures de prueba locales.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("download_corpus")

BASE_DIR = Path(__file__).resolve().parent.parent
AUDIO_DIR = BASE_DIR / "corpus" / "audio"

# Charlas de referencia y especificación de cortes para los 4 perfiles
SAMPLE_MANIFEST = [
    {
        "id": "stage-en",
        "title": "International Keynote - English",
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",  # Reemplazable con URL Nerdearla
        "start_time": "00:01:30",
        "duration": "00:00:30",
        "description": "Charla en inglés técnico con pronunciación clara",
    },
    {
        "id": "stage-es",
        "title": "Arquitectura Backend - Español",
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "start_time": "00:02:00",
        "duration": "00:00:30",
        "description": "Charla en español latinoamericano técnico",
    },
    {
        "id": "stage-spanglish",
        "title": "DevOps de Trinchera - Spanglish",
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "start_time": "00:03:00",
        "duration": "00:00:30",
        "description": "Charla con jerga Spanglish densa (deployar, pods, mergear)",
    },
    {
        "id": "stage-noisy",
        "title": "Workshop Sala Comunitaria - Audio Ruidoso",
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "start_time": "00:04:00",
        "duration": "00:00:30",
        "description": "Audio con eco de salón y ruido de fondo para estresar el VAD",
    },
]


def check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def check_ytdlp() -> bool:
    return shutil.which("yt-dlp") is not None


def generate_synthetic_fixture(stage_id: str, output_path: Path, is_noisy: bool = False) -> None:
    """Genera un archivo WAV sintético normalizado (16kHz, mono, PCM s16le) con ffmpeg."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Generando audio de prueba para %s en %s...", stage_id, output_path)

    # Creamos un patrón de audio con tonos y silencios simulando actividad vocal (VAD)
    if is_noisy:
        # Tono con ruido blanco de fondo (simula eco y salón ruidoso)
        lavfi_filter = "anoisesrc=d=15:c=white:a=0.08,aformat=sample_fmts=s16:sample_rates=16000:channel_layouts=mono"
    else:
        # Señal limpia de prueba de 15 segundos
        lavfi_filter = "sine=frequency=440:duration=15,aformat=sample_fmts=s16:sample_rates=16000:channel_layouts=mono"

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", lavfi_filter,
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        logger.error("Fallo ffmpeg al generar fixture: %s", result.stderr)
    else:
        logger.info("Fixture generado exitosamente: %s", output_path)


def download_and_cut(item: dict[str, str], output_path: Path) -> bool:
    """Descarga el audio con yt-dlp y recorta con ffmpeg."""
    if not check_ytdlp():
        logger.warning("yt-dlp no encontrado. Generando fixture alternativo...")
        generate_synthetic_fixture(item["id"], output_path, is_noisy=("noisy" in item["id"]))
        return True

    temp_audio = output_path.parent / f"temp_{item['id']}.m4a"
    try:
        # Descarga con yt-dlp
        cmd_dl = [
            "yt-dlp",
            "-x",
            "--audio-format", "m4a",
            "-o", str(temp_audio),
            item["url"],
        ]
        subprocess.run(cmd_dl, check=True)

        # Recorte con ffmpeg a 16kHz mono WAV
        cmd_cut = [
            "ffmpeg",
            "-y",
            "-ss", item["start_time"],
            "-i", str(temp_audio),
            "-t", item["duration"],
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "pcm_s16le",
            str(output_path),
        ]
        subprocess.run(cmd_cut, check=True)
        return True
    except subprocess.CalledProcessError as err:
        logger.error("Error al procesar %s: %s", item["id"], err)
        return False
    finally:
        if temp_audio.exists():
            temp_audio.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Corpus Downloader & Generator para Nerdearla")
    parser.add_argument("--synthetic", action="store_true", help="Forzar generación de fixtures sintéticos")
    parser.add_argument("--manifest", type=str, default="", help="Ruta a manifest JSON personalizado")
    args = parser.parse_args()

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    manifest = SAMPLE_MANIFEST
    if args.manifest and Path(args.manifest).exists():
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))

    logger.info("Iniciando preparación de corpus para %d muestras...", len(manifest))
    for item in manifest:
        dest = AUDIO_DIR / f"{item['id']}.wav"
        if args.synthetic or not check_ytdlp():
            generate_synthetic_fixture(item["id"], dest, is_noisy=("noisy" in item["id"]))
        else:
            download_and_cut(item, dest)

    logger.info("Preparación de corpus completada en %s", AUDIO_DIR)


if __name__ == "__main__":
    main()
