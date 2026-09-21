# Contributing to JXVisionAI

## License

By contributing you agree that your changes are licensed under the
**GNU Affero General Public License v3.0 or later** (same as this repo).

## Setup

```bash
python3 -m venv env && source env/bin/activate
pip install -r requirements.txt
# CPU-only: replace onnxruntime-gpu with onnxruntime in requirements.txt
cp config/config.example.ini config/config.ini
cp .env.example .env   # set VISIONAI_SECRET, REDIS_PASSWORD, MinIO, ZLM_SECRET
```

Do not use the historical example passwords from old docs; they are public.

## Tests

```bash
python -m unittest discover -s tests -v
```

CI runs the same command without GPU and without live cameras.

## Do not commit

- `config/config.ini`, `.env`, Redis/MinIO data, `logs/`, `snapshots/`
- Model weights (`*.pt`, `*.onnx`, `models/buffalo_l/`)
- Face library photos or customer RTSP URLs/passwords
- Debug dumps or personal IP addresses

## Pull requests

- Vendor-specific gateways stay out of this repo; document generic webhook / open API only (`docs/integration.md`).
- Detection type names stored in Redis stay Chinese (protocol); UI strings go
  through `visionai/web/static/i18n/`.
- Prefer tests for protocol/status/auth changes over only manual clicks.
