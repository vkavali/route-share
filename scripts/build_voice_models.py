#!/usr/bin/env python3
"""Build-time only: download verified free weights and prepare offline CPU models."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import urllib.request
import zipfile

DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / "docs/voice/models.json"
CHUNK = 4 * 1024 * 1024
MAX_MEMBER_BYTES = 1_600_000_000
MAX_TOTAL_BYTES = 1_700_000_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_file(path: Path, expected: dict) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing/unsafe model file: {path.name}")
    if path.stat().st_size != expected["bytes"] or sha256(path) != expected["sha256"]:
        raise ValueError(f"Model checksum/size mismatch: {path.name}")


def fetch(expected: dict, destination: Path, offline: bool) -> Path:
    """Reuse only valid cached data. A corrupt cache is an error, never trusted."""
    if destination.exists() or destination.is_symlink():
        verify_file(destination, expected)
        return destination
    if offline:
        raise ValueError(f"Offline build cache is missing {destination.name}")
    if not expected["url"].startswith("https://"):
        raise ValueError("Model downloads require HTTPS")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".download")
    if temporary.exists() or temporary.is_symlink():
        raise ValueError("Refusing existing model download temporary path")
    try:
        with urllib.request.urlopen(expected["url"], timeout=120) as response, temporary.open("xb") as target:
            count = 0
            while block := response.read(CHUNK):
                count += len(block)
                if count > expected["bytes"]:
                    raise ValueError("Model download exceeded manifest size")
                target.write(block)
        verify_file(temporary, expected)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def extract_checkpoint(archive: Path, destination: Path, settings: dict) -> None:
    """Inspect the entire ZIP, then extract only reviewed standard tensor/config files."""
    prefix = settings["archive_prefix"]
    allowed = set(settings["extract_files"])
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        seen, selected, total = set(), [], 0
        for info in members:
            path = PurePosixPath(info.filename)
            mode = info.external_attr >> 16
            if path.is_absolute() or ".." in path.parts or "\\" in info.filename or stat.S_ISLNK(mode):
                raise ValueError("Unsafe checkpoint archive member")
            if info.filename in seen:
                raise ValueError("Duplicate checkpoint archive member")
            seen.add(info.filename)
            if info.file_size > MAX_MEMBER_BYTES:
                raise ValueError("Checkpoint archive member exceeds size cap")
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                raise ValueError("Checkpoint archive exceeds extracted-size cap")
            if info.filename.startswith(prefix) and info.filename[len(prefix):] in allowed:
                selected.append(info)
        if {info.filename[len(prefix):] for info in selected} != allowed:
            raise ValueError("Checkpoint is missing reviewed files")
        destination.mkdir(parents=True, exist_ok=False)
        for info in selected:
            target = destination / info.filename[len(prefix):]
            with source.open(info) as incoming, target.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, CHUNK)
    config = json.loads((destination / "config.json").read_text())
    if config.get("model_type") != "whisper" or "auto_map" in config:
        raise ValueError("Only standard Whisper checkpoints are accepted")


def convert_telugu(checkpoint: Path, destination: Path) -> None:
    # Imports are build-only. Runtime never installs Torch or Transformers.
    os.environ.update(HF_HUB_OFFLINE="1", HF_HUB_DISABLE_IMPLICIT_TOKEN="1")
    import torch
    from transformers import WhisperTokenizerFast
    from ctranslate2.converters import TransformersConverter

    class TensorOnlyConverter(TransformersConverter):
        def load_model(self, model_class, model_name_or_path, **kwargs):
            # The release stores all tensor views in one storage. A single mmap
            # avoids repeatedly reading 1.53GB per parameter in HF's loader.
            state = torch.load(Path(model_name_or_path) / "pytorch_model.bin",
                               map_location="cpu", weights_only=True, mmap=True)
            if "proj_out.weight" not in state:
                if not kwargs["config"].tie_word_embeddings:
                    raise ValueError("Unexplained missing output projection")
                state["proj_out.weight"] = state["model.decoder.embed_tokens.weight"]
            with torch.device("meta"):
                model = model_class(kwargs["config"])
            model.load_state_dict(state, strict=True, assign=True)
            model.tie_weights()
            model.eval()
            return model

    converter = TensorOnlyConverter(str(checkpoint), copy_files=["preprocessor_config.json"],
                                    trust_remote_code=False)
    converter.convert(str(destination), quantization="int8")
    tokenizer = WhisperTokenizerFast.from_pretrained(str(checkpoint), local_files_only=True)
    tokenizer.backend_tokenizer.save(str(destination / "tokenizer.json"))


def verify_models(output: Path, manifest: dict) -> None:
    for language in ("en", "te"):
        for expected in manifest[language]["files"]:
            name = expected["name"]
            if PurePosixPath(name).name != name:
                raise ValueError("Unsafe manifest filename")
            verify_file(output / language / name, expected)


def build(manifest: dict, cache: Path, output: Path, offline: bool) -> None:
    if output.exists() or output.is_symlink():
        verify_models(output, manifest)
        print("Existing model directory verified")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="voice-model-build-", dir=output.parent) as temporary:
        staging = Path(temporary) / "models"
        (staging / "en").mkdir(parents=True)
        for expected in manifest["en"]["files"]:
            name = expected["name"]
            if PurePosixPath(name).name != name:
                raise ValueError("Unsafe manifest filename")
            source = fetch(expected, cache / "en" / name, offline)
            shutil.copyfile(source, staging / "en" / name)
        archive = fetch(manifest["te"]["archive"], cache / "indicwhisper-telugu.zip", offline)
        checkpoint = Path(temporary) / "checkpoint"
        extract_checkpoint(archive, checkpoint, manifest["te"])
        convert_telugu(checkpoint, staging / "te")
        verify_models(staging, manifest)
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        staging.replace(output)
    print("English and Telugu model hashes verified; offline runtime files ready")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offline", action="store_true", help="use already-verified cached downloads only")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if manifest.get("schema_version") != 1:
        parser.error("Unsupported model manifest")
    if args.verify_only:
        verify_models(args.output, manifest)
        print("Model files verified")
    else:
        build(manifest, args.cache, args.output, args.offline)


if __name__ == "__main__":
    main()
