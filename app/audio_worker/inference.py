from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path
from typing import Any

import torch

from app.core.settings import Settings


class AudioASRRunner:
    def __init__(self, settings: Settings, logger) -> None:
        self.settings = settings
        self.logger = logger
        self._model = None

    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): self._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._json_safe(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    def _ensure_runtime(self) -> None:
        if self._model is not None:
            return
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA 不可用，audio-worker 不能按要求走 GPU 链路。")

        from funasr import AutoModel

        self.logger.info(
            "Loading FunASR runtime model=%s vad_model=%s device=%s",
            self.settings.audio_model_id,
            self.settings.audio_vad_model_id,
            self.settings.audio_device,
        )
        self._model = AutoModel(
            model=self.settings.audio_model_id,
            vad_model=self.settings.audio_vad_model_id,
            vad_kwargs={"max_single_segment_time": 30000},
            device=self.settings.audio_device,
            disable_update=True,
        )

    def _preprocess(self, input_path: Path, work_dir: Path) -> Path:
        preprocessed_path = work_dir / "preprocessed.wav"
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-sample_fmt",
            "s16",
            str(preprocessed_path),
        ]
        self.logger.info("Preprocessing audio with ffmpeg: %s", " ".join(command))
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"ffmpeg 预处理失败: {completed.stderr.strip()}")
        return preprocessed_path

    def _duration_seconds(self, wav_path: Path) -> float | None:
        try:
            with wave.open(str(wav_path), "rb") as handle:
                frames = handle.getnframes()
                frame_rate = handle.getframerate()
                if frame_rate <= 0:
                    return None
                return round(frames / frame_rate, 3)
        except Exception:
            self.logger.exception("Failed to read duration from %s", wav_path)
            return None

    def _pick_primary_result(self, raw_result: Any) -> Any:
        if isinstance(raw_result, list) and raw_result:
            return raw_result[0]
        return raw_result

    def _extract_text(self, primary: Any) -> str:
        if isinstance(primary, dict):
            for key in ("text", "pred_text", "raw_text"):
                value = primary.get(key)
                if isinstance(value, str):
                    return value
        if isinstance(primary, str):
            return primary
        return ""

    def _extract_segments(self, primary: Any) -> list[dict[str, Any]]:
        if not isinstance(primary, dict):
            return []

        candidate_lists = []
        for key in ("sentence_info", "sentences", "segments"):
            value = primary.get(key)
            if isinstance(value, list):
                candidate_lists.append(value)

        segments: list[dict[str, Any]] = []
        for items in candidate_lists:
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                start_ms = item.get("start_ms", item.get("start", item.get("begin")))
                end_ms = item.get("end_ms", item.get("end", item.get("stop")))
                text = item.get("text", item.get("sentence", item.get("value", "")))
                segment = {
                    "index": index,
                    "start_ms": self._as_int_or_none(start_ms),
                    "end_ms": self._as_int_or_none(end_ms),
                    "text": text if isinstance(text, str) else str(text),
                }
                if segment["text"] or segment["start_ms"] is not None or segment["end_ms"] is not None:
                    segments.append(segment)
            if segments:
                return segments

        timestamp = primary.get("timestamp")
        if isinstance(timestamp, list):
            for index, item in enumerate(timestamp):
                if isinstance(item, dict):
                    segments.append(
                        {
                            "index": index,
                            "start_ms": self._as_int_or_none(item.get("start", item.get("begin"))),
                            "end_ms": self._as_int_or_none(item.get("end", item.get("stop"))),
                            "text": item.get("text", ""),
                        }
                    )
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    segments.append(
                        {
                            "index": index,
                            "start_ms": self._as_int_or_none(item[0]),
                            "end_ms": self._as_int_or_none(item[1]),
                            "text": item[2] if len(item) > 2 else "",
                        }
                    )
        return segments

    def _extract_aed(self, primary: Any) -> dict[str, Any]:
        if not isinstance(primary, dict):
            return {"available": False, "raw": None}
        for key in ("aed", "aed_result", "event_detection", "aed_info"):
            if key in primary:
                return {"available": True, "raw": self._json_safe(primary.get(key))}
        return {"available": False, "raw": None}

    def _as_int_or_none(self, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        try:
            return int(float(str(value)))
        except Exception:
            return None

    def analyze(self, request: dict[str, Any], output_path: Path) -> Path:
        input_path = Path(request["audio_uri"])
        if not input_path.exists():
            raise FileNotFoundError(f"audio_uri 不存在: {input_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_runtime()

        preprocessed_path = self._preprocess(input_path, output_path.parent)
        self.logger.info("Running FunASR generate on %s", preprocessed_path)
        raw_result = self._model.generate(
            input=str(preprocessed_path),
            cache={},
            language=request.get("language", "auto"),
            use_itn=True,
            batch_size_s=60,
            merge_vad=True,
            merge_length_s=15,
        )

        primary = self._pick_primary_result(raw_result)
        result = {
            "job_id": request["job_id"],
            "backend": "funasr",
            "model_id": self.settings.audio_model_id,
            "vad_model_id": self.settings.audio_vad_model_id,
            "audio_uri": str(input_path),
            "preprocessed_audio_uri": str(preprocessed_path),
            "profile": request.get("profile"),
            "language": request.get("language", "auto"),
            "text": self._extract_text(primary),
            "aed": self._extract_aed(primary),
            "segments": self._extract_segments(primary),
            "metadata": {
                "duration_seconds": self._duration_seconds(preprocessed_path),
                "preprocess": {
                    "codec": "pcm_s16le",
                    "sample_rate_hz": 16000,
                    "channels": 1,
                },
                "device": self.settings.audio_device,
                "cuda_available": torch.cuda.is_available(),
            },
            "raw_result": self._json_safe(raw_result),
        }
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        self.logger.info("Wrote audio analysis result to %s", output_path)
        return output_path
