from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SeparationResult:
    backend: str
    status: str
    mix_path: Path
    effects_path: Path
    dialogue_path: Path | None
    music_path: Path | None
    output_dir: Path
    metadata: dict[str, Any]


def passthrough_separation(mix_path: Path, effects_path: Path) -> SeparationResult:
    effects_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(mix_path, effects_path)
    return SeparationResult(
        backend="passthrough",
        status="fallback_original_audio",
        mix_path=mix_path,
        effects_path=effects_path,
        dialogue_path=None,
        music_path=None,
        output_dir=effects_path.parent,
        metadata={"reason": "No separation backend was used."},
    )


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=str(cwd), env=env, capture_output=True, text=True, check=False)


def _find_named_stem(candidates: list[Path], exact_names: tuple[str, ...]) -> Path | None:
    for exact_name in exact_names:
        for path in candidates:
            if path.stem.lower() == exact_name:
                return path
    return None


def _copy_if_found(source: Path | None, target: Path) -> Path | None:
    if source is None:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


def bandit_separation(
    mix_path: Path,
    stream_dir: Path,
    *,
    repo_dir: Path,
    ckpt_path: Path,
    model_name: str,
    allow_fallback: bool,
) -> SeparationResult:
    if not repo_dir.exists():
        if allow_fallback:
            return passthrough_separation(mix_path, stream_dir / "effects.wav")
        raise FileNotFoundError(f"BandIt repo not found: {repo_dir}")
    if not ckpt_path.exists():
        if allow_fallback:
            return passthrough_separation(mix_path, stream_dir / "effects.wav")
        raise FileNotFoundError(f"BandIt checkpoint not found: {ckpt_path}")

    separated_dir = stream_dir / "bandit"
    command = [
        "python3",
        "inference.py",
        "inference",
        f"--ckpt_path={ckpt_path}",
        f"--file_path={mix_path}",
        f"--model_name={model_name}",
        f"--output_dir={separated_dir}",
        "--include_track_name=False",
        "--get_residual=True",
        "--get_no_vox_combinations=True",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{repo_dir}:{env.get('PYTHONPATH', '')}"
    env["PROJECT_ROOT"] = str(repo_dir)
    completed = _run(command, cwd=repo_dir, env=env)
    metadata = {
        "command": command,
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }
    (stream_dir / "separation_command.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if completed.returncode != 0:
        if allow_fallback:
            result = passthrough_separation(mix_path, stream_dir / "effects.wav")
            return SeparationResult(
                backend="bandit",
                status="fallback_original_audio",
                mix_path=mix_path,
                effects_path=result.effects_path,
                dialogue_path=None,
                music_path=None,
                output_dir=separated_dir,
                metadata={**metadata, "fallback_backend": "passthrough"},
            )
        raise RuntimeError(f"BandIt separation failed; see {stream_dir / 'separation_command.json'}")

    wavs = sorted(separated_dir.rglob("*.wav"))
    effects_source = _find_named_stem(wavs, ("effects", "effect", "sfx"))
    dialogue_source = _find_named_stem(wavs, ("speech", "dialogue", "dialog", "vox", "vocal"))
    music_source = _find_named_stem(wavs, ("music", "score"))
    if effects_source is None:
        if allow_fallback:
            result = passthrough_separation(mix_path, stream_dir / "effects.wav")
            return SeparationResult(
                backend="bandit",
                status="fallback_original_audio",
                mix_path=mix_path,
                effects_path=result.effects_path,
                dialogue_path=_copy_if_found(dialogue_source, stream_dir / "dialogue.wav"),
                music_path=_copy_if_found(music_source, stream_dir / "music.wav"),
                output_dir=separated_dir,
                metadata={**metadata, "found_wavs": [str(path) for path in wavs], "fallback_backend": "passthrough"},
            )
        raise RuntimeError(f"BandIt did not produce an effects stem; found: {[str(path) for path in wavs]}")

    effects_path = stream_dir / "effects.wav"
    dialogue_path = _copy_if_found(dialogue_source, stream_dir / "dialogue.wav")
    music_path = _copy_if_found(music_source, stream_dir / "music.wav")
    shutil.copyfile(effects_source, effects_path)
    return SeparationResult(
        backend="bandit",
        status="succeeded",
        mix_path=mix_path,
        effects_path=effects_path,
        dialogue_path=dialogue_path,
        music_path=music_path,
        output_dir=separated_dir,
        metadata={**metadata, "found_wavs": [str(path) for path in wavs]},
    )
