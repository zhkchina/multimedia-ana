from __future__ import annotations

import csv
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
        params = request.get("params") or {}
        detector = str(params.get("detector", "content")).strip().lower() or "content"
        if detector != "content":
            raise ValueError(f"scene 目前仅支持 detector=content，收到: {detector}")

        command = [
            "python3",
            "-m",
            "scenedetect",
            "-i",
            request["file_uri"],
        ]

        downscale = int(params.get("downscale", 0) or 0)
        if downscale > 0:
            command.extend(["--downscale", str(downscale)])

        frame_skip = int(params.get("frame_skip", 0) or 0)
        if frame_skip > 0:
            command.extend(["--frame-skip", str(frame_skip)])

        command.extend(
            [
                "-o",
                str(output_dir),
                "-s",
                str(self._stats_csv_path(output_dir)),
                "-m",
                str(params.get("min_scene_len", "0.6s")),
                "detect-content",
                "--threshold",
                str(params.get("threshold", 27.0)),
                "list-scenes",
                "--skip-cuts",
            ]
        )
        save_image_count = int(params.get("save_image_count", 0))
        if save_image_count > 0:
            command.extend(["save-images", "--num-images", str(save_image_count)])
        return command

    def _parse_scene_csv(self, csv_path: Path) -> list[dict[str, Any]]:
        if not csv_path.exists():
            return []

        rows = list(csv.reader(csv_path.read_text(encoding="utf-8").splitlines()))
        if not rows:
            return []

        scenes: list[dict[str, Any]] = []
        for row in rows:
            if len(row) < 10:
                continue
            if not row[0].strip().isdigit():
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

    def analyze(self, request: dict[str, Any], work_dir: Path) -> dict[str, Any]:
        params = request.get("params") or {}
        video_path = Path(request["file_uri"])
        if not video_path.exists():
            raise FileNotFoundError(f"file_uri 不存在: {video_path}")

        output_dir = work_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        command = self._build_command(request, output_dir)
        self.logger.info("Running scene detection for task %s", request["task_id"])
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
            "service": "video-scene",
            "file_uri": str(video_path),
            "params": {
                "profile": params.get("profile", "standard"),
                "detector": str(params.get("detector", "content")).strip().lower() or "content",
                "threshold": params.get("threshold", 27.0),
                "min_scene_len": params.get("min_scene_len", "0.6s"),
                "downscale": int(params.get("downscale", 0) or 0),
                "frame_skip": int(params.get("frame_skip", 0) or 0),
                "save_image_count": int(params.get("save_image_count", 0)),
                "include_artifacts": bool(params.get("include_artifacts", False)),
            },
            "summary": {
                "scene_count": len(scenes),
                "image_count": len(images),
            },
            "scenes": scenes,
        }
        if bool(params.get("include_artifacts", False)):
            result["artifacts"] = {
                "stats_csv": str(stats_csv),
                "scenes_csv": str(scenes_csv),
                "image_files": images,
            }
        return result
