# Offline CPU voice-model package

This package prepares the free models at **image build time**. The server never downloads a model while handling a recording. Voice remains disabled unless the application release configuration explicitly enables it. Local non-Docker runs do not enable voice simply because dependencies are installed.

## Models and integrity

- English: Systran's pinned multilingual Whisper small conversion, used with explicit English and runtime CPU INT8. Downloaded CT2 weights remain their original format; INT8 conversion happens in memory during loading, matching the tested baseline.
- Telugu: AI4Bharat IndicWhisper Telugu (Whisper medium), converted once to CT2 INT8 during the build.
- `models.json` records exact HTTPS download URLs, revisions where available, byte lengths and SHA256 checksums, including every final runtime file. A corrupted cached download or unexpected conversion output fails the build.
- The Telugu ZIP has no immutable versioned URL; its pinned full-file SHA256 is the input identity. Only reviewed model/tokenizer/config members are extracted. Bundled Python scripts, training arguments and RNG snapshots are ignored. Absolute/traversal paths, symlinks, duplicate entries, oversized archives and custom model architectures are rejected.
- The standard checkpoint's shared tensor storage is loaded once with `weights_only=True`, CPU mapping and mmap. The configured tied output embedding is restored from the decoder embedding, then all state keys are validated strictly. No `trust_remote_code` or model-supplied script executes.
- Model MIT notices and source attribution in `licenses/` are copied into the final image. Runtime Python packages retain their installed licenses.

## Container layout

The Dockerfile pins the official Python 3.12.12 Debian Bookworm image by digest. A disposable first stage installs CPU-only Torch and pinned conversion dependencies, verifies downloads and converts the Telugu checkpoint. The final stage contains the pinned ASR runtime, model files and licenses; it contains no Torch, Transformers, conversion scripts, source archives or training objects.

The final image supplies:

```text
VOICE_MODEL_PATH_TE=/opt/route-share-models/te
VOICE_MODEL_PATH_EN=/opt/route-share-models/en
HF_HUB_OFFLINE=1
HF_HUB_DISABLE_IMPLICIT_TOKEN=1
```

`VOICE_ENABLED` is intentionally not supplied by the image. The application must verify both paths and gate its capability explicitly. The runtime recognizer must continue using `local_files_only=True` and explicit `en`/`te`; a missing model is an unavailable capability, not permission to download or substitute another model.

No microphone recording belongs in build inputs, model caches, logs, source archives or image layers. Temporary recording deletion and model-worker admission/cancellation belong to the application voice service.

## Build and verify

A normal image build downloads about 1.90 GB of pinned model inputs once; final model files total about 1.26 GB. Reuse Docker's verified completed layers for repeated unchanged builds. A failed build does not produce a partially published runtime model directory.

```sh
docker build --platform linux/amd64 -t route-share-voice:review .
```

For an isolated offline local build, populate a cache containing `en/{config.json,model.bin,tokenizer.json,vocabulary.txt}` and `indicwhisper-telugu.zip` from the pinned manifest, then run with the converter environment:

```sh
python scripts/build_voice_models.py --cache /absolute/temporary/cache --output /absolute/temporary/models --offline
python scripts/build_voice_models.py --cache /absolute/temporary/cache --output /absolute/temporary/models --verify-only
```

Always place caches and model outputs outside the source tree. Do not commit or upload weights as source. `scripts/stage_railway.py` includes the small builder, manifest, dependency locks and license files explicitly; other scripts remain excluded by both Docker/Railway ignore files. The source and runtime collectors have been checked to contain no model weights or benchmark audio.

## Validation and capacity limits

The isolated builder reproduced all expected artifact hashes with the cached official inputs. Integrity tests cover bad hashes, offline missing files, unsafe ZIP members, skipped scripts, extraction caps and failure cleanup. The build/runtime dependency locks are separately exercised under Linux x86_64 Python 3.12.12.

A local Docker engine was not available at preparation time (Docker Desktop Linux named pipe absent). Therefore a complete container build, final image size, actual hosted libc/library integration and Railway startup are **not yet verified**. The Dockerfile itself includes a native import/INT8-support smoke check that must pass during the eventual image build.

Measured local Python 3.12 runtime environment size is about 506 MiB; the two model directories total about 1.2 GiB. With Python/OS/app files, estimate roughly 1.8–2.1 GB uncompressed for the final image; this is not an image inspection result or a RAM estimate. Build-only Torch, the original Telugu archive and expanded weights require additional temporary build storage and do not belong in the final image.

The Telugu worker previously peaked near 1.5 GiB RAM by itself. English small also exceeded the existing 500 MB (500,000,000 bytes) server allowance. A 3 GiB service cap is a trial configuration requiring measured hosted headroom, one admitted inference at a time and correct model switching; it is not a guarantee. No resource allocation, paid deployment or model enablement is authorized merely by this document. The user confirmed a **$25/month ceiling for Route Share alone**, including this app's existing service, storage and traffic; unrelated workspace projects are outside this budget. Final paid deployment approval is still required for the exact 2 vCPU / 3 GiB, single-replica configuration and voice settings. The estimate is not a guaranteed bill cap.

`VOICE_DAILY_LIMIT=100` is the proposed aggregate UTC-day admission quota across all users, persisted in the existing SQLite database. Admitted failures and cancellations count; the quota is not reset by process restart. One transcription runs at a time, and the recognizer exits after 60 idle seconds to release model memory. This is volume control, not a literal hosting bill cap: other app activity, storage, egress and resource retention still affect cost. Keep the existing data volume; add no audio volume.

Accuracy evidence remains bounded to a tiny public/synthetic diagnostic. See the separate evaluation report; the Telugu-specific model is a candidate requiring real-phone validation, not a guarantee of correct trips. Explicit editable review and actual map/geocoder resolution remain mandatory.
