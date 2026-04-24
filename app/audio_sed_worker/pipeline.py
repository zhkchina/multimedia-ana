from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from app.audio_sed_worker.profiles import PromptSpec, get_profile, slugify
from app.audio_sed_worker.separation import bandit_separation, passthrough_separation


DEFAULT_SAMPLE_RATE = 48000


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _probe_media(input_path: Path) -> tuple[float, list[dict[str, Any]]]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,channels,channel_layout,sample_rate,duration:stream_disposition=default:stream_tags=language",
        "-select_streams",
        "a",
        "-of",
        "json",
        str(input_path),
    ]
    completed = _run(command)
    if completed.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {completed.stderr.strip()}")
    payload = json.loads(completed.stdout or "{}")
    duration = float((payload.get("format") or {}).get("duration") or 0.0)
    streams: list[dict[str, Any]] = []
    for stream in payload.get("streams") or []:
        if stream.get("codec_type") != "audio":
            continue
        disposition = stream.get("disposition") or {}
        tags = stream.get("tags") or {}
        streams.append(
            {
                "stream_index": int(stream["index"]),
                "codec_name": stream.get("codec_name"),
                "channels": stream.get("channels"),
                "channel_layout": stream.get("channel_layout"),
                "sample_rate_hz": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
                "duration_seconds": float(stream["duration"]) if stream.get("duration") else None,
                "language": tags.get("language"),
                "is_default_stream": bool(disposition.get("default", 0)),
            }
        )
    return duration, streams


def _extract_stream(input_path: Path, stream_index: int, output_path: Path, sample_rate: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-map",
        f"0:{stream_index}",
        "-vn",
        "-ac",
        "2",
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_f32le",
        str(output_path),
    ]
    completed = _run(command)
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg stream extraction failed: {completed.stderr.strip()}")


def _audio_levels(audio: np.ndarray) -> tuple[float, float]:
    if audio.size == 0:
        return -120.0, -120.0
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))
    return round(20.0 * np.log10(max(peak, 1e-8)), 2), round(20.0 * np.log10(max(rms, 1e-8)), 2)


def _local_rms_dbfs(audio: np.ndarray, *, sample_rate: int, center_ms: int, window_ms: int) -> float:
    if audio.size == 0:
        return -120.0
    half_window_samples = max(1, int(round(window_ms * sample_rate / 2000)))
    center_sample = int(round(center_ms * sample_rate / 1000))
    start = max(0, center_sample - half_window_samples)
    stop = min(len(audio), center_sample + half_window_samples)
    if stop <= start:
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(audio[start:stop]), dtype=np.float64)))
    return round(20.0 * np.log10(max(rms, 1e-8)), 2)


def _load_mono(path: Path, sample_rate: int) -> np.ndarray:
    audio, actual_sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    if actual_sample_rate != sample_rate:
        import librosa

        resampled, _ = librosa.load(str(path), sr=sample_rate, mono=True)
        return np.asarray(resampled, dtype=np.float32)
    return np.mean(audio, axis=1).astype(np.float32, copy=False)


def _frame_to_ms(frame_index: int, frame_count: int, duration_ms: int) -> int:
    if frame_count <= 0:
        return 0
    return int(round(frame_index * duration_ms / frame_count))


def _segments_from_scores(
    scores: np.ndarray,
    *,
    threshold: float,
    duration_ms: int,
    min_event_ms: int,
    merge_gap_ms: int,
) -> list[tuple[int, int, int, float]]:
    if scores.size == 0:
        return []
    active = scores >= threshold
    raw: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(active):
        if value and start is None:
            start = index
        elif not value and start is not None:
            raw.append((start, index))
            start = None
    if start is not None:
        raw.append((start, len(scores)))

    frame_count = len(scores)
    merged: list[tuple[int, int]] = []
    merge_gap_frames = int(round(merge_gap_ms * frame_count / max(duration_ms, 1)))
    for start_frame, stop_frame in raw:
        if merged and start_frame - merged[-1][1] <= merge_gap_frames:
            merged[-1] = (merged[-1][0], stop_frame)
        else:
            merged.append((start_frame, stop_frame))

    events = []
    for start_frame, stop_frame in merged:
        start_ms = _frame_to_ms(start_frame, frame_count, duration_ms)
        end_ms = max(start_ms + 1, _frame_to_ms(stop_frame, frame_count, duration_ms))
        if end_ms - start_ms < min_event_ms:
            continue
        window = scores[start_frame:stop_frame]
        peak_offset = int(np.argmax(window))
        peak_frame = start_frame + peak_offset
        peak_ms = _frame_to_ms(peak_frame, frame_count, duration_ms)
        events.append((start_ms, peak_ms, end_ms, float(np.max(window))))
    return events


def _stub_localization(
    audio: np.ndarray,
    prompts: list[PromptSpec],
    *,
    duration_ms: int,
    limit: int,
) -> list[dict[str, Any]]:
    peak_dbfs, rms_dbfs = _audio_levels(audio)
    if audio.size == 0:
        return []
    envelope = np.abs(audio)
    if envelope.size > 512:
        kernel = np.ones(512, dtype=np.float32) / 512.0
        envelope = np.convolve(envelope, kernel, mode="same")
    top_indices = np.argsort(envelope)[-limit:][::-1]
    events = []
    for rank, sample_index in enumerate(sorted(int(item) for item in top_indices)):
        prompt = prompts[rank % len(prompts)]
        peak_ms = int(round(sample_index * duration_ms / max(len(audio), 1)))
        start_ms = max(0, peak_ms - 120)
        end_ms = min(duration_ms, peak_ms + 160)
        events.append(
            {
                "domain": prompt.domain,
                "prompt": prompt.prompt,
                "start_ms": start_ms,
                "peak_ms": peak_ms,
                "end_ms": end_ms,
                "score": round(float(envelope[sample_index]), 4),
                "source": "stub_energy",
                "audio_peak_dbfs": peak_dbfs,
                "audio_rms_dbfs": rms_dbfs,
            }
        )
    return events


def _openflam_localization(
    audio_path: Path,
    prompts: list[PromptSpec],
    *,
    model_name: str,
    model_cache_dir: Path,
    device: str,
    threshold: float,
    min_event_ms: int,
    merge_gap_ms: int,
    prompt_batch_size: int,
    max_chunk_seconds: float,
    chunk_overlap_seconds: float,
    min_local_rms_dbfs: float,
    local_rms_window_ms: int,
    boundary_ignore_ms: int,
) -> list[dict[str, Any]]:
    import librosa
    import scipy.ndimage
    import torch
    import openflam

    audio, sample_rate = librosa.load(str(audio_path), sr=DEFAULT_SAMPLE_RATE, mono=True)
    model = openflam.OpenFLAM(model_name=model_name, default_ckpt_path=str(model_cache_dir)).to(device)
    model.eval()

    events: list[dict[str, Any]] = []
    peak_dbfs, rms_dbfs = _audio_levels(np.asarray(audio, dtype=np.float32))

    chunk_samples = max(1, int(max_chunk_seconds * DEFAULT_SAMPLE_RATE))
    overlap_samples = max(0, int(chunk_overlap_seconds * DEFAULT_SAMPLE_RATE))
    step_samples = max(1, chunk_samples - overlap_samples)

    for chunk_start in range(0, len(audio), step_samples):
        chunk_end = min(len(audio), chunk_start + chunk_samples)
        chunk = audio[chunk_start:chunk_end]
        if chunk.size == 0:
            continue
        chunk_offset_ms = int(round(chunk_start * 1000 / DEFAULT_SAMPLE_RATE))
        chunk_duration_ms = int(round(len(chunk) * 1000 / DEFAULT_SAMPLE_RATE))
        audio_tensor = torch.tensor(chunk, dtype=torch.float32).unsqueeze(0).to(device)

        for offset in range(0, len(prompts), prompt_batch_size):
            batch = prompts[offset : offset + prompt_batch_size]
            texts = [item.prompt for item in batch]
            with torch.no_grad():
                similarity = model.get_local_similarity(audio_tensor, texts, method="unbiased", cross_product=True)
            scores = similarity.detach().cpu().numpy()
            if scores.ndim == 3:
                scores = scores[0]
            if scores.ndim != 2:
                raise RuntimeError(f"Unexpected OpenFLAM similarity shape: {scores.shape}")
            scores = scipy.ndimage.median_filter(scores, size=(1, 3))
            for prompt_spec, prompt_scores in zip(batch, scores, strict=True):
                segments = _segments_from_scores(
                    np.asarray(prompt_scores, dtype=np.float32),
                    threshold=threshold,
                    duration_ms=chunk_duration_ms,
                    min_event_ms=min_event_ms,
                    merge_gap_ms=merge_gap_ms,
                )
                for start_ms, peak_ms, end_ms, score in segments:
                    global_peak_ms = chunk_offset_ms + peak_ms
                    if global_peak_ms < boundary_ignore_ms or len(audio) * 1000 / DEFAULT_SAMPLE_RATE - global_peak_ms < boundary_ignore_ms:
                        continue
                    local_rms_dbfs = _local_rms_dbfs(
                        np.asarray(audio, dtype=np.float32),
                        sample_rate=DEFAULT_SAMPLE_RATE,
                        center_ms=global_peak_ms,
                        window_ms=local_rms_window_ms,
                    )
                    if local_rms_dbfs < min_local_rms_dbfs:
                        continue
                    events.append(
                        {
                            "domain": prompt_spec.domain,
                            "prompt": prompt_spec.prompt,
                            "start_ms": chunk_offset_ms + start_ms,
                            "peak_ms": global_peak_ms,
                            "end_ms": chunk_offset_ms + end_ms,
                            "score": round(score, 4),
                            "source": "openflam",
                            "audio_peak_dbfs": peak_dbfs,
                            "audio_rms_dbfs": rms_dbfs,
                            "event_local_rms_dbfs": local_rms_dbfs,
                        }
                    )
        if chunk_end >= len(audio):
            break
    return _dedupe_events(sorted(events, key=lambda item: (item["peak_ms"], item["prompt"])))


def _dedupe_events(events: list[dict[str, Any]], window_ms: int = 160) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    for event in sorted(events, key=lambda item: item["score"], reverse=True):
        if any(
            event["prompt"] == kept["prompt"] and abs(event["peak_ms"] - kept["peak_ms"]) <= window_ms
            for kept in deduped
        ):
            continue
        deduped.append(event)
    return sorted(deduped, key=lambda item: (item["peak_ms"], item["prompt"]))


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"input does not exist: {input_path}")

    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    profile = get_profile(args.profile)
    trace: dict[str, Any] = {"stages": {}, "config": vars(args)}
    started = time.monotonic()
    duration_seconds, streams = _probe_media(input_path)
    if not streams:
        raise RuntimeError(f"No audio streams found in {input_path}")

    all_streams = []
    total_event_count = 0
    for stream in streams:
        stream_started = time.monotonic()
        stream_index = int(stream["stream_index"])
        stream_dir = work_dir / "streams" / f"stream_{stream_index}"
        mix_path = stream_dir / "mix.wav"

        _extract_stream(input_path, stream_index, mix_path, args.sample_rate)
        if args.separation_backend == "bandit":
            separation = bandit_separation(
                mix_path,
                stream_dir,
                repo_dir=Path(args.bandit_repo_dir),
                ckpt_path=Path(args.bandit_ckpt_path),
                model_name=args.bandit_model_name,
                allow_fallback=args.allow_separation_fallback,
            )
        else:
            separation = passthrough_separation(mix_path, stream_dir / "effects.wav")
        effects_path = separation.effects_path
        audio = _load_mono(effects_path, args.sample_rate)
        duration_ms = int(round(len(audio) * 1000 / args.sample_rate))

        if args.localization_backend == "stub_energy":
            stream_events = _stub_localization(audio, profile, duration_ms=duration_ms, limit=args.stub_event_limit)
        else:
            try:
                stream_events = _openflam_localization(
                    effects_path,
                    profile,
                    model_name=args.openflam_model,
                    model_cache_dir=Path(args.model_cache_dir),
                    device=args.device,
                    threshold=args.threshold,
                    min_event_ms=args.min_event_ms,
                    merge_gap_ms=args.merge_gap_ms,
                    prompt_batch_size=args.prompt_batch_size,
                    max_chunk_seconds=args.openflam_chunk_seconds,
                    chunk_overlap_seconds=args.openflam_chunk_overlap_seconds,
                    min_local_rms_dbfs=args.min_event_local_rms_dbfs,
                    local_rms_window_ms=args.event_local_rms_window_ms,
                    boundary_ignore_ms=args.boundary_ignore_ms,
                )
            except Exception:
                if not args.allow_stub_fallback:
                    raise
                stream_events = _stub_localization(audio, profile, duration_ms=duration_ms, limit=args.stub_event_limit)
                trace.setdefault("warnings", []).append(
                    f"OpenFLAM failed on stream {stream_index}; used stub_energy fallback."
                )

        enriched_stream_events = []
        for event in stream_events:
            prompt_slug = slugify(event["prompt"])
            event_id = f"{input_path.stem}:s{stream_index}:{event['domain']}:{prompt_slug}:{event['peak_ms']}"
            enriched_stream_events.append(
                {
                    "event_id": event_id,
                    "file_uri": str(input_path),
                    "clip_id": input_path.stem,
                    "audio_stream_index": stream_index,
                    "is_default_stream": bool(stream["is_default_stream"]),
                    "stem": "effects",
                    **event,
                }
            )

        stream_events_jsonl = stream_dir / "events.jsonl"
        stream_events_jsonl.write_text(
            "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in enriched_stream_events),
            encoding="utf-8",
        )
        total_event_count += len(enriched_stream_events)

        stream_result = {
            **stream,
            "mix_path": str(mix_path),
            "effects_path": str(effects_path),
            "dialogue_path": str(separation.dialogue_path) if separation.dialogue_path else None,
            "music_path": str(separation.music_path) if separation.music_path else None,
            "separation": {
                "backend": separation.backend,
                "status": separation.status,
                "output_dir": str(separation.output_dir),
                "metadata": separation.metadata,
            },
            "event_count": len(enriched_stream_events),
            "events_jsonl": str(stream_events_jsonl),
            "events": sorted(enriched_stream_events, key=lambda item: (item["peak_ms"], item["prompt"])),
            "elapsed_seconds": round(time.monotonic() - stream_started, 3),
        }
        all_streams.append(stream_result)
        _json_dump(stream_dir / "stream_result.json", stream_result)

    result = {
        "service": "audio-sed",
        "mode": "debug-pipeline",
        "file_uri": str(input_path),
        "profile": args.profile,
        "summary": {
            "duration_ms": int(round(duration_seconds * 1000)),
            "audio_stream_count": len(streams),
            "analyzed_stream_count": len(all_streams),
            "candidate_count": total_event_count,
            "event_count": total_event_count,
        },
        "audio_streams": all_streams,
        "metadata": {
            "pipeline_version": "audio_sed_pipeline_v0",
            "event_layout": "per_audio_stream",
            "sample_rate_hz": args.sample_rate,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "result_json": str(work_dir / "result.json"),
        },
    }
    trace["elapsed_seconds"] = result["metadata"]["elapsed_seconds"]
    _json_dump(work_dir / "pipeline_trace.json", trace)
    _json_dump(work_dir / "result.json", result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the audio-sed debug pipeline inside Docker.")
    parser.add_argument("--input", required=True, help="Container-visible media file path.")
    parser.add_argument("--work-dir", required=True, help="Writable output directory under /data.")
    parser.add_argument("--profile", default="action_beats_v1")
    parser.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--separation-backend", choices=["bandit", "passthrough"], default="bandit")
    parser.add_argument("--allow-separation-fallback", action="store_true")
    parser.add_argument("--bandit-repo-dir", default="/data/multimedia-ana/audio-sed/vendor/bandit")
    parser.add_argument(
        "--bandit-ckpt-path",
        default="/data/multimedia-ana/audio-sed/models/bandit/dnr-3s-mus64-l1snr-bs8/checkpoints/dnr-3s-mus64-l1snr.ckpt",
    )
    parser.add_argument("--bandit-model-name", default="dnr-3s-mus64-l1snr")
    parser.add_argument("--model-cache-dir", default="/data/multimedia-ana/audio-sed/models/openflam")
    parser.add_argument("--openflam-model", default="v1-base")
    parser.add_argument("--localization-backend", choices=["openflam", "stub_energy"], default="openflam")
    parser.add_argument("--allow-stub-fallback", action="store_true")
    parser.add_argument("--threshold", type=float, default=0.2)
    parser.add_argument("--min-event-ms", type=int, default=120)
    parser.add_argument("--merge-gap-ms", type=int, default=160)
    parser.add_argument("--prompt-batch-size", type=int, default=8)
    parser.add_argument("--openflam-chunk-seconds", type=float, default=9.5)
    parser.add_argument("--openflam-chunk-overlap-seconds", type=float, default=0.5)
    parser.add_argument("--min-event-local-rms-dbfs", type=float, default=-45.0)
    parser.add_argument("--event-local-rms-window-ms", type=int, default=240)
    parser.add_argument("--boundary-ignore-ms", type=int, default=300)
    parser.add_argument("--stub-event-limit", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    result = run_pipeline(parse_args())
    print(json.dumps({"result_json": result["metadata"]["result_json"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
