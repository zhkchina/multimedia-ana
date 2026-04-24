from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path


DEFAULT_BANDIT_MODEL = "dnr-3s-mus64-l1snr"
DEFAULT_BANDIT_STABLE_BATCH_SIZE = 8


def _run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, cwd=str(cwd) if cwd else None, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            "Command failed "
            f"({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout[-4000:]}\n"
            f"stderr:\n{completed.stderr[-4000:]}"
        )
    return completed


def _prepare_stable_batch_variant(
    *,
    repo_dir: Path,
    model_dir: Path,
    model_name: str,
    checkpoint_path: Path,
    batch_size: int,
) -> dict[str, str]:
    variant_dir = model_dir.parent / f"{model_name}-bs{batch_size}"
    variant_checkpoint_dir = variant_dir / "checkpoints"
    variant_checkpoint_dir.mkdir(parents=True, exist_ok=True)

    source_hparams = model_dir / "hparams.yaml"
    variant_hparams = variant_dir / "hparams.yaml"
    inference_config = repo_dir / "configs" / "inference" / f"default{batch_size}.yaml"
    if not inference_config.exists():
        raise FileNotFoundError(f"BandIt stable inference config not found: {inference_config}")
    hparams_text = source_hparams.read_text(encoding="utf-8").replace(
        "configs/inference/default.yaml",
        f"configs/inference/default{batch_size}.yaml",
    )
    variant_hparams.write_text(hparams_text, encoding="utf-8")

    variant_checkpoint = variant_checkpoint_dir / checkpoint_path.name
    if variant_checkpoint.exists() or variant_checkpoint.is_symlink():
        variant_checkpoint.unlink()
    variant_checkpoint.symlink_to(checkpoint_path)
    return {
        "model_dir": str(variant_dir),
        "checkpoint_path": str(variant_checkpoint),
        "hparams_path": str(variant_hparams),
    }


def _prepare_bandit(args: argparse.Namespace) -> dict[str, object]:
    repo_dir = Path(args.bandit_repo_dir)
    repo_ready = repo_dir.exists() and (repo_dir / "inference.py").exists()
    if args.bandit_skip_repo_download:
        if not repo_ready:
            raise FileNotFoundError(
                f"BandIt repo is not ready at {repo_dir}. "
                "Place the source tree there with inference.py, or unset --bandit-skip-repo-download."
            )
    if args.bandit_local_archive:
        archive_path = Path(args.bandit_local_archive)
        if not archive_path.exists():
            raise FileNotFoundError(f"BandIt local archive not found: {archive_path}")
        extract_dir = repo_dir.parent / f"bandit-extract-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "r:gz") as handle:
            handle.extractall(extract_dir)
        extracted_roots = [path for path in extract_dir.iterdir() if path.is_dir()]
        if not extracted_roots:
            raise RuntimeError(f"BandIt archive did not contain a source directory: {archive_path}")
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        shutil.move(str(extracted_roots[0]), str(repo_dir))
        shutil.rmtree(extract_dir, ignore_errors=True)
        repo_ready = (repo_dir / "inference.py").exists()
    if repo_dir.exists():
        if repo_ready:
            pass
        elif (repo_dir / ".git").exists():
            _run(["git", "fetch", "--depth", "1", "origin", args.bandit_ref], cwd=repo_dir)
            _run(["git", "checkout", args.bandit_ref], cwd=repo_dir)
            repo_ready = (repo_dir / "inference.py").exists()
        elif any(repo_dir.iterdir()):
            backup_dir = repo_dir.with_name(f"{repo_dir.name}.broken-{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            shutil.move(str(repo_dir), str(backup_dir))
        else:
            repo_dir.rmdir()
    if not repo_dir.exists():
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
    if not repo_ready and not args.bandit_skip_repo_download:
        tarball_path = repo_dir.parent / f"bandit-{args.bandit_ref}.tar.gz"
        tarball_url = args.bandit_tarball_url or f"https://github.com/kwatcharasupat/bandit/archive/refs/heads/{args.bandit_ref}.tar.gz"
        try:
            _run(["curl", "-L", "--fail", "--output", str(tarball_path), tarball_url])
        except RuntimeError:
            _run(["git", "clone", "--depth", "1", "--branch", args.bandit_ref, args.bandit_repo_url, str(repo_dir)])
        else:
            extract_dir = repo_dir.parent / f"bandit-extract-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            extract_dir.mkdir(parents=True, exist_ok=True)
            with tarfile.open(tarball_path, "r:gz") as handle:
                handle.extractall(extract_dir)
            extracted_roots = [path for path in extract_dir.iterdir() if path.is_dir()]
            if not extracted_roots:
                raise RuntimeError(f"BandIt tarball did not contain a source directory: {tarball_path}")
            if repo_dir.exists():
                shutil.rmtree(repo_dir)
            shutil.move(str(extracted_roots[0]), str(repo_dir))
            shutil.rmtree(extract_dir, ignore_errors=True)
        if not (repo_dir / "inference.py").exists():
            raise RuntimeError(f"BandIt repo is incomplete, missing inference.py: {repo_dir}")

    model_name = args.bandit_model
    model_dir = Path(args.bandit_model_dir) / model_name
    checkpoint_dir = model_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = checkpoint_dir / f"{model_name}.ckpt"
    if not checkpoint_path.exists():
        url = args.bandit_ckpt_url or f"https://zenodo.org/records/10160698/files/{model_name}.ckpt?download=1"
        _run(["curl", "-L", "--fail", "--output", str(checkpoint_path), url])

    hparams_path = model_dir / "hparams.yaml"
    if not hparams_path.exists():
        if args.bandit_hparams_url:
            _run(["curl", "-L", "--fail", "--output", str(hparams_path), args.bandit_hparams_url])
        else:
            candidates = [
                path
                for path in [
                    repo_dir / "expt" / f"{model_name}.yaml",
                    repo_dir / "expt" / f"{model_name}-mne.yaml",
                    repo_dir / "expt" / f"{model_name}-long.yaml",
                ]
                if path.exists()
            ]
            if not candidates:
                candidates = sorted(repo_dir.glob(f"expt/**/*{model_name}*.yaml"))
            if not candidates:
                tokens = model_name.replace("dnr-3s-", "").replace("-l1snr", "").split("-")
                candidates = [
                    path
                    for path in sorted(repo_dir.glob("expt/**/*.yaml"))
                    if all(token in path.name for token in tokens)
                ]
            if not candidates:
                raise FileNotFoundError(
                    f"Could not infer BandIt hparams yaml for {model_name}. "
                    "Set BANDIT_HPARAMS_URL or copy hparams.yaml manually."
                )
            shutil.copyfile(candidates[0], hparams_path)

    stable_variant = _prepare_stable_batch_variant(
        repo_dir=repo_dir,
        model_dir=model_dir,
        model_name=model_name,
        checkpoint_path=checkpoint_path,
        batch_size=args.bandit_stable_batch_size,
    )

    return {
        "repo_dir": str(repo_dir),
        "model": model_name,
        "checkpoint_path": str(checkpoint_path),
        "hparams_path": str(hparams_path),
        "stable_batch_size": args.bandit_stable_batch_size,
        "stable_variant": stable_variant,
        "license_note": "BandIt code is Apache-2.0; Zenodo model weights are CC-BY-NC-4.0.",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download/cache audio-sed worker models.")
    parser.add_argument("--openflam", action="store_true", help="Download/cache OpenFLAM.")
    parser.add_argument("--openflam-model", default="v1-base")
    parser.add_argument("--openflam-cache-dir", default="/data/multimedia-ana/audio-sed/models/openflam")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--bandit", action="store_true", help="Clone BandIt and download the default DnR checkpoint.")
    parser.add_argument("--bandit-repo-url", default="https://github.com/kwatcharasupat/bandit.git")
    parser.add_argument("--bandit-tarball-url", default=None)
    parser.add_argument("--bandit-local-archive", default=None)
    parser.add_argument("--bandit-skip-repo-download", action="store_true")
    parser.add_argument("--bandit-ref", default="main")
    parser.add_argument("--bandit-repo-dir", default="/data/multimedia-ana/audio-sed/vendor/bandit")
    parser.add_argument("--bandit-model", default=DEFAULT_BANDIT_MODEL)
    parser.add_argument("--bandit-model-dir", default="/data/multimedia-ana/audio-sed/models/bandit")
    parser.add_argument("--bandit-ckpt-url", default=None)
    parser.add_argument("--bandit-hparams-url", default=None)
    parser.add_argument("--bandit-stable-batch-size", type=int, default=DEFAULT_BANDIT_STABLE_BATCH_SIZE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results: dict[str, object] = {}
    if args.openflam:
        import torch
        import openflam

        cache_dir = Path(args.openflam_cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        device = args.device if args.device.startswith("cuda") and torch.cuda.is_available() else "cpu"
        model = openflam.OpenFLAM(model_name=args.openflam_model, default_ckpt_path=str(cache_dir)).to(device)
        if hasattr(model, "sanity_check"):
            model.sanity_check()
        results["openflam"] = {
            "model": args.openflam_model,
            "cache_dir": str(cache_dir),
            "device": device,
            "cuda_available": torch.cuda.is_available(),
        }
    if args.bandit:
        results["bandit"] = _prepare_bandit(args)
    print(json.dumps({"status": "ok", "models": results}, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
