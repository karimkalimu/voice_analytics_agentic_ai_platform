# Audio analysis POC backend

[Project overview](../README.md) · [Data model](../docs/data-model.md) · [Guardrails](../docs/guardrails.md)

FastAPI authenticates users and exposes file results. tusd receives resumable uploads and calls private FastAPI hooks. The backend validates audio, transcribes it with AssemblyAI, runs structured LLM analysis, and stores results in SQLite and per-user local storage.

## Setup

Supported host: Ubuntu 22.04 or 24.04 on x86_64/amd64.

```sh
chmod +x ubuntu_setup.sh run_api.sh run_tusd.sh
./ubuntu_setup.sh
```

The setup installs Python 3.13, FFmpeg/FFprobe, pinned Python packages, and checksum-verified tusd v2.10.1. It creates `.env` from `.env.example` only when `.env` is absent.

Fill in `.env` with:

- the Firebase service-account JSON path;
- the AssemblyAI API key;
- fast and quality LLM API keys, base URLs, and model IDs;
- the supplied processing versions and POC limits; and
- FastAPI and tusd addresses and ports.

`.env.example` contains every required variable. Credentials, `.env`, SQLite files, uploads, and local tools are ignored by Git.

Run the services in separate terminals:

```sh
./run_api.sh
```

```sh
./run_tusd.sh
```

Defaults: FastAPI `http://localhost:8000`; tusd upload creation `http://localhost:8081/files/`.

## API summary

| Request | Purpose | Authentication |
| --- | --- | --- |
| `GET /health` | Service health | Public |
| `GET /guardrails` | Enforced POC limits and policy text | Public |
| `GET /files` | Owned files with optional filters | Firebase bearer token |
| `GET /files/{id}` | One owned file and analysis result | Firebase bearer token |
| `GET /files/{id}/transcript` | Saved transcript | Firebase bearer token |
| `POST /files/{id}/layer2` | Add predefined analyses | Firebase bearer token |
| `DELETE /files/{id}` | Delete a terminal owned file | Firebase bearer token |
| `POST /hooks/tusd` | tusd `pre-create` and `post-finish` hooks | Loopback/private |

The TUS creation request sends the Firebase token plus `user_id` and `filename` metadata. Optional `layer2_options` may contain `rms`, `count_nouns`, `count_adjectives`, `sentiment`, or `topic_mentions`; `topic_mentions` requires a 1–100 character topic.

## Offline collective analysis

For this POC, aggregate jobs run offline through a separate CLI process. Jobs are persisted as `queued`, `running`, `completed`, or `failed` and unfinished jobs resume after restart.

Examples:

```sh
.venv/bin/python -m app.aggregate_job --group-by user
.venv/bin/python -m app.aggregate_job --group-by taxonomy --taxonomy-label software
.venv/bin/python -m app.aggregate_job --group-by sentiment --user-id FIREBASE_UID
.venv/bin/python -m app.aggregate_job --group-by all --user-id FIREBASE_UID
```

Optional filters are `--user-id`, `--created-from`, `--created-to`, and `--taxonomy-label`. Global `all` is rejected; an undifferentiated content summary always requires one user scope. LLM inputs use bounded existing summaries and taxonomy instead of unbounded raw transcripts.

## POC limits

- Maximum audio size: 25 MB
- Maximum duration: 90 seconds
- Maximum active files per user: 5
- English, audible, intelligible, profanity-free speech
- Initial TUS creation is authenticated; returned upload URLs are private capability URLs

See [guardrails](../docs/guardrails.md) for the malicious-input controls and [data model](../docs/data-model.md) for ownership and storage layout.

## POC resource profile

Resource usage was measured on the deployed POC while exercising the application with `scripts/monitor_resources.py`.

Environment:

- Hetzner Cloud
- Ubuntu 24.04.5 LTS
- x86_64
- 2 vCPU — Intel Xeon Skylake
- 3.8 GB RAM
- Python 3.13.15
- tusd v2.10.1
- Measurement duration: ~39.5 minutes

| Service | Avg CPU | Peak CPU | Avg RSS | Peak RSS |
|---|---:|---:|---:|---:|
| FastAPI / processing | 0.56% | 81.2% | 229.5 MB | 304.4 MB |
| tusd | 0.01% | 4.9% | 33.3 MB | 35.4 MB |
| Combined | 0.57% | 81.2% | 262.9 MB | 339.8 MB |

The API measurement includes child processes such as ffmpeg/ffprobe. These are results from one small POC VM, not production capacity benchmarks. Average CPU includes idle periods, so peak CPU better represents active processing demand.

## Verification

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/pip check
.venv/bin/python -m compileall -q app tests
bash -n ubuntu_setup.sh run_api.sh run_tusd.sh
```

The 23 backend tests cover authentication boundaries, ownership isolation, tusd hooks, processing, filters, guardrails, Layer 2, caching, aggregation, recovery, and storage.
