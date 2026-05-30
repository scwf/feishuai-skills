import os
from pathlib import Path
import json

import yt_dlp

from .utils import setup_logger


logger = setup_logger("downloader")
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}


def download_audio(url: str, output_dir: str) -> str:
    """Download audio from YouTube URL and return the file path."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    manifest_path = out_path / ".download_manifest.json"

    try:
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                ledger = json.load(f)
            
            if url in ledger:
                cached_filename = out_path / ledger[url]
                if cached_filename.exists() or cached_filename.with_suffix(".asr.json").exists():
                    logger.info(f"0s Network Bypass: Found '{url}' in ledger. Using cached file '{cached_filename.name}'.")
                    return str(cached_filename.resolve())
    except Exception as e:
        logger.warning(f"Failed to read download ledger: {e}")

    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }
        ],
        "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        logger.info(f"Downloading audio from {url}...")
        try:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            final_filename = Path(filename).with_suffix(".wav")
            
            try:
                ledger = {}
                if manifest_path.exists():
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        ledger = json.load(f)
                
                ledger[url] = final_filename.name
                
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(ledger, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"Failed to write download ledger: {e}")

            logger.info(f"Downloaded to {final_filename}")
            return str(final_filename)
        except yt_dlp.utils.DownloadError as e:
            err_msg = str(e).lower()
            if "live event" in err_msg or "begin in" in err_msg or "premiere" in err_msg:
                logger.warning(f"Skipping upcoming live event: {url}")
                return None
            raise e
