# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Docker template for **Vast.ai/RunPod** with Demucs audio separation (vocals/instrumental). Provides a CLI tool, REST API, and Python clients for GPU cloud orchestration.

## Build & Run Commands

### Docker Build
```bash
docker build -t demucs-template .
```

### Run Container Locally (with GPU)
```bash
docker run --gpus all -p 8185:8185 demucs-template
```

### CLI Usage (inside container)
```bash
# Separate audio from URL
demucs-separate --input "https://example.com/audio.mp3" --output ./results

# With custom cut intervals (seconds)
demucs-separate --input "https://..." --interval-cut "300,600,900" --output ./results

# Extract all stems
demucs-separate --input audio.mp3 --output ./results --all-stems
```

### Cloud Clients (local machine)
```bash
# Vast.ai
export VASTAI_API_KEY="your_key"
python vastai_client.py list-offers
python vastai_client.py separate "https://example.com/audio.mp3" --output ./results

# RunPod
export RUNPOD_API_KEY="your_key"
python runpod_client.py gpus
python runpod_client.py separate "https://example.com/audio.mp3" --output ./results
```

### Test Concurrent Instances (Vast.ai)
```bash
python test_concurrent_instances.py --num-instances 10
python test_concurrent_instances.py --destroy-all
```

## Architecture

```
/
├── Dockerfile              # Image build (~6-7 GB)
├── start.sh                # Startup: GPU check, model extraction, services
├── server.py               # FastAPI REST API (port 8185)
├── demucs-separate         # CLI tool (Python script)
├── vastai_client.py        # Vast.ai orchestration client
├── runpod_client.py        # RunPod orchestration client
├── test_concurrent_instances.py  # Concurrent instance testing
└── mvsep/
    ├── inference_demucs.py # Core Demucs inference (ensemble models)
    ├── models/             # ML models (symlinked from /models-cache)
    ├── demucs3/            # Demucs v3 model implementations
    └── demucs4/            # Demucs v4 model implementations
```

### Key Paths Inside Container
- `/workspace/mvsep/` - Main workspace
- `/models-cache/` - Extracted ML models (Kim_Vocal_2.onnx, etc.)
- `/workspace/model_weights/` - Compressed model weights (extracted on first start)
- `/workspace/jobs/` - Job outputs when using REST API

### Exposed Ports
- **8185** - FastAPI REST API (only exposed port)
- Note: JupyterLab has been removed to reduce startup time and simplify deployment

### REST API Endpoints (port 8185)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/status` | GET | Server status (models_ready, active_jobs) |
| `/job` | POST | Create separation job |
| `/job/{id}` | GET | Get job status + progress |
| `/result/{id}` | GET | Download result file |
| `/jobs` | GET | List all jobs |

### Progress Tracking
Jobs write progress to `progress.txt` (JSON):
```json
{
  "state": "demucs|completed|error",
  "tasks": {"cutting": "running|no_work", "inference": "...", "conversion": "..."},
  "details": {"completed_segments": 2, "total_segments": 4, "percent": 50.0}
}
```

## ML Pipeline

1. **Input**: Audio file (URL or local path)
2. **Cutting**: Auto-split into 5-minute segments (or custom intervals)
3. **Inference**: Ensemble of Demucs + MDX-B models (htdemucs_ft, htdemucs, htdemucs_6s, hdemucs_mmi)
4. **Output**: Concatenated instrumental (mono MP3)

### GPU Memory Handling
- `inference_demucs.py` has two classes:
  - `EnsembleDemucsMDXMusicSeparationModel` - Keeps all models on GPU (requires 11+ GB VRAM)
  - `EnsembleDemucsMDXMusicSeparationModelLowGPU` - Loads models sequentially (lower memory)
- `demucs-separate` auto-detects GPU and calculates chunk_size
- OOM retry: Reduces chunk_size by 50000 per attempt (up to 20 attempts)

## Cloud Client Architecture

Both `vastai_client.py` and `runpod_client.py` follow the same pattern:
1. Search available GPU offers (filtered by VRAM >= 8GB, reliability)
2. Create instance with the Docker image
3. Wait for API ready (poll `/health`)
4. Submit job via REST API
5. Poll progress until complete
6. Download result
7. Destroy instance (unless `--keep-pod`/`--keep-instance`)

### Vast.ai Port Mapping

Vast.ai maps exposed ports to random external ports. The client:
1. Queries the instance API to get the `ports` field
2. Extracts the external port from `ports["8185/tcp"][0]["HostPort"]`
3. Constructs API URL as `http://{public_ipaddr}:{external_port}`

Reference: [Vast.ai Networking Documentation](https://docs.vast.ai/documentation/instances/connect/networking)

## Optimizations

### Build-time vs Runtime
- **FastAPI/uvicorn/pydantic**: Installed during Docker build (not at runtime)
- **ML models**: Downloaded during build, extracted on first container start
- **Result**: Faster container startup (~3-5min for model extraction vs 5-10min previously)

### Removed Components
- **JupyterLab**: Removed to reduce startup time and simplify deployment
- Only FastAPI server runs in foreground

## GitHub Actions

`.github/workflows/docker-build.yml` builds and pushes to `ghcr.io/cyrille8000/ffmpeg-demucs-vast-template:latest` on push to main.
