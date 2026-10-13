"""Build-time model integrity boundaries; no model downloads or ML dependencies."""
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import zipfile

import pytest

spec = importlib.util.spec_from_file_location("voice_model_build", Path(__file__).parents[1] / "scripts/build_voice_models.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def expected(content):
    return {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(), "url": "https://example.invalid/model"}


def archive(path, entries):
    with zipfile.ZipFile(path, "w") as target:
        for name, content in entries:
            target.writestr(name, content)


SETTINGS = {"archive_prefix": "checkpoint/", "extract_files": ["config.json"]}
CONFIG = json.dumps({"model_type": "whisper"})


def test_valid_cache_never_downloads_and_corrupt_cache_fails_closed(tmp_path, monkeypatch):
    target = tmp_path / "model.bin"
    target.write_bytes(b"verified")
    monkeypatch.setattr(builder.urllib.request, "urlopen", lambda *_a, **_kw: pytest.fail("unexpected network"))
    assert builder.fetch(expected(b"verified"), target, offline=False) == target
    target.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="checksum/size"):
        builder.fetch(expected(b"verified"), target, offline=False)
    assert target.read_bytes() == b"corrupted"


def test_offline_missing_model_and_symlink_cache_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="Offline"):
        builder.fetch(expected(b"x"), tmp_path / "missing.bin", offline=True)
    real = tmp_path / "real.bin"
    real.write_bytes(b"x")
    link = tmp_path / "model.bin"
    link.symlink_to(real)
    with pytest.raises(ValueError, match="unsafe"):
        builder.fetch(expected(b"x"), link, offline=True)


@pytest.mark.parametrize("bad_name", ["../escape.py", "/absolute.py", "checkpoint/../../escape.py", "checkpoint\\escape.py"])
def test_archive_traversal_rejected_before_any_extraction(tmp_path, bad_name):
    source = tmp_path / "model.zip"
    archive(source, [("checkpoint/config.json", CONFIG), (bad_name, "bad")])
    with pytest.raises(ValueError, match="Unsafe"):
        builder.extract_checkpoint(source, tmp_path / "out", SETTINGS)
    assert not (tmp_path / "out").exists()


def test_archive_symlink_rejected(tmp_path):
    source = tmp_path / "model.zip"
    info = zipfile.ZipInfo("checkpoint/link")
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(source, "w") as target:
        target.writestr("checkpoint/config.json", CONFIG)
        target.writestr(info, "../../outside")
    with pytest.raises(ValueError, match="Unsafe"):
        builder.extract_checkpoint(source, tmp_path / "out", SETTINGS)


def test_scripts_and_training_objects_are_not_extracted(tmp_path):
    source = tmp_path / "model.zip"
    archive(source, [("checkpoint/config.json", CONFIG), ("checkpoint/zero_to_fp32.py", "raise RuntimeError('never execute')"), ("checkpoint/training_args.bin", b"untrusted")])
    builder.extract_checkpoint(source, tmp_path / "out", SETTINGS)
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["config.json"]


def test_archive_size_cap_and_custom_architecture_rejected(tmp_path, monkeypatch):
    source = tmp_path / "large.zip"
    archive(source, [("checkpoint/config.json", CONFIG)])
    monkeypatch.setattr(builder, "MAX_MEMBER_BYTES", 2)
    with pytest.raises(ValueError, match="size cap"):
        builder.extract_checkpoint(source, tmp_path / "out", SETTINGS)
    monkeypatch.setattr(builder, "MAX_MEMBER_BYTES", 1000)
    archive(source, [("checkpoint/config.json", json.dumps({"model_type": "whisper", "auto_map": {"AutoModel": "remote.Code"}}))])
    with pytest.raises(ValueError, match="standard Whisper"):
        builder.extract_checkpoint(source, tmp_path / "custom", SETTINGS)


def test_duplicate_or_missing_archive_member_rejected(tmp_path):
    source = tmp_path / "model.zip"
    with pytest.warns(UserWarning, match="Duplicate"):
        archive(source, [("checkpoint/config.json", CONFIG), ("checkpoint/config.json", CONFIG)])
    with pytest.raises(ValueError, match="Duplicate"):
        builder.extract_checkpoint(source, tmp_path / "out", SETTINGS)
    archive(source, [("checkpoint/other.json", "{}")])
    with pytest.raises(ValueError, match="missing reviewed"):
        builder.extract_checkpoint(source, tmp_path / "missing", SETTINGS)


def test_failed_conversion_hash_does_not_publish_model_directory(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    (cache / "en").mkdir(parents=True)
    (cache / "en/model.bin").write_bytes(b"english")
    source = cache / "indicwhisper-telugu.zip"
    archive(source, [("checkpoint/config.json", CONFIG)])
    manifest = {"en": {"files": [{"name": "model.bin", **expected(b"english")}]}, "te": {**SETTINGS, "archive": expected(source.read_bytes()), "files": [{"name": "model.bin", **expected(b"correct-telugu")}]}}
    def bad_conversion(_checkpoint, destination):
        destination.mkdir()
        (destination / "model.bin").write_bytes(b"wrong-telugu")
    monkeypatch.setattr(builder, "convert_telugu", bad_conversion)
    with pytest.raises(ValueError, match="checksum/size"):
        builder.build(manifest, cache, tmp_path / "published", offline=True)
    assert not (tmp_path / "published").exists()
    assert not list(tmp_path.glob("voice-model-build-*"))
