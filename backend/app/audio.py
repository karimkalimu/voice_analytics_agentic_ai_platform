import json
import math
import struct
import subprocess
from pathlib import Path


def probe_audio(audio_path: Path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_type,duration:format=duration", "-of", "json",
         str(audio_path)], capture_output=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode(errors="replace") or "Audio could not be probed.")
    try:
        payload = json.loads(result.stdout)
        streams = payload.get("streams") or []
        if not streams or streams[0].get("codec_type") != "audio":
            raise ValueError
        raw_duration = streams[0].get("duration") or payload.get("format", {}).get("duration")
        duration = float(raw_duration)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("Audio has no usable stream or duration.") from exc
    return duration


def rms_normalized(audio_path: Path):
    process = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(audio_path), "-f", "s16le", "-ac", "1",
         "-ar", "16000", "pipe:1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    sum_squares = 0
    samples = 0
    for chunk in iter(lambda: process.stdout.read(65536), b""):
        for (sample,) in struct.iter_unpack("<h", chunk):
            sum_squares += sample * sample
            samples += 1
    error = process.stderr.read()
    if process.wait() != 0 or not samples:
        raise RuntimeError(error.decode(errors="replace").splitlines()[0] if error else "Audio could not be decoded.")
    return math.sqrt(sum_squares / samples) / 32768
