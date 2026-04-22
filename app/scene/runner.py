from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path
from typing import Any

from app.core.settings import Settings


class VideoSceneRunner:
    def __init__(self, settings: Settings, logger) -> None:
        self.settings = settings
        self.logger = logger

    def _scenes_csv_path(self, output_dir: Path, video_path: Path) -> Path:
        return output_dir / f"{video_path.stem}-Scenes.csv"

    def _stats_csv_path(self, output_dir: Path) -> Path:
        return output_dir / "stats.csv"

    def _build_command(self, request: dict[str, Any], output_dir: Path) -> list[str]:
        return [
            "python3",
            "-m",
            "scenedetect",
            "-i",
            request["video_uri"],
            "-o",
            str(output_dir),
            "-s",
            str(self._stats_csv_path(output_dir)),
            "-m",
            request.get("min_scene_len", "0.6s"),
            "detect-content",
            "--threshold",
            str(request.get("threshold", 27.0)),
            "list-scenes",
            "--skip-cuts",
            "save-images",
            "--num-images",
            str(request.get("save_image_count", 3)),
        ]

    def _parse_scene_csv(self, csv_path: Path) -> list[dict[str, Any]]:
        if not csv_path.exists():
            return []

        rows = list(csv.reader(csv_path.read_text(encoding="utf-8").splitlines()))
        if len(rows) < 3:
            return []

        scenes: list[dict[str, Any]] = []
        for row in rows[2:]:
            if len(row) < 10:
                continue
            scenes.append(
                {
                    "scene_number": int(row[0]),
                    "start_frame": int(row[1]),
                    "start_timecode": row[2],
                    "start_seconds": float(row[3]),
                    "end_frame": int(row[4]),
                    "end_timecode": row[5],
                    "end_seconds": float(row[6]),
                    "length_frames": int(row[7]),
                    "length_timecode": row[8],
                    "length_seconds": float(row[9]),
                }
            )
        return scenes

    def _collect_images(self, output_dir: Path) -> list[str]:
        patterns = ("*.jpg", "*.jpeg", "*.png", "*.webp")
        images: list[Path] = []
        for pattern in patterns:
            images.extend(output_dir.glob(pattern))
        return [str(path) for path in sorted(images)]

    def analyze(self, request: dict[str, Any], output_path: Path) -> Path:
        video_path = Path(request["video_uri"])
        if not video_path.exists():
            raise FileNotFoundError(f"video_uri 不存在: {video_path}")

        output_dir = output_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        command = self._build_command(request, output_dir)
        self.logger.info("Running scene detection for job %s", request["job_id"])
        completed = subprocess.run(command, capture_output=True, text=True)

        scenes_csv = self._scenes_csv_path(output_dir, video_path)
        stats_csv = self._stats_csv_path(output_dir)
        scenes = self._parse_scene_csv(scenes_csv)
        images = self._collect_images(output_dir)

        if completed.returncode != 0:
            raise RuntimeError(f"scenedetect failed: {completed.stderr.strip()}")
        if not scenes_csv.exists() or not stats_csv.exists():
            raise RuntimeError(
                "scenedetect completed without expected output files. "
                f"stdout={completed.stdout.strip()} stderr={completed.stderr.strip()}"
            )

        result = {
            "job_id": request["job_id"],
            "service": "video-scene",
            "video_uri": str(video_path),
            "profile": request.get("profile"),
            "detector": "detect-content",
            "threshold": request.get("threshold", 27.0),
            "min_scene_len": request.get("min_scene_len", "0.6s"),
            "save_image_count": request.get("save_image_count", 3),
            "scene_count": len(scenes),
            "image_count": len(images),
            "stats_csv": str(stats_csv),
            "scenes_csv": str(scenes_csv),
            "image_files": images,
            "scenes": scenes,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        self.logger.info("Wrote scene analysis result to %s", output_path)
        return output_path
