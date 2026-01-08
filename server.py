#!/usr/bin/env python3
"""
Demucs Separation API Server
=============================
FastAPI server for audio separation via demucs-separate CLI.

Endpoints:
    POST /job          - Start a new separation job
    GET  /job/{job_id} - Get job status (reads progress.txt)
    GET  /result/{job_id} - Download result file (instrumental.mp3)
    GET  /health       - Health check
    GET  /status       - Server status

Port: 8185 (exposed in Dockerfile)
"""

import os
import sys
import json
import uuid
import asyncio
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

# =============================================================================
# CONFIGURATION
# =============================================================================
JOBS_DIR = Path('/workspace/jobs')
DEMUCS_CLI = '/usr/local/bin/demucs-separate'
MODELS_CACHE = '/models-cache'
MODELS_READY_FILE = f'{MODELS_CACHE}/Kim_Vocal_2.onnx'

# Create jobs directory
JOBS_DIR.mkdir(parents=True, exist_ok=True)

# Active jobs storage
JOBS: Dict[str, Dict[str, Any]] = {}

# =============================================================================
# PYDANTIC MODELS
# =============================================================================
class JobRequest(BaseModel):
    """Request to start a new job"""
    input_url: str = Field(..., description="URL of audio file to process")
    interval_cut: Optional[str] = Field(None, description="Custom cut timestamps (e.g. '300,600,900')")
    all_stems: bool = Field(False, description="Extract all stems (vocals, drums, bass, other)")
    job_id: Optional[str] = Field(None, description="Custom job ID (auto-generated if not provided)")

class JobResponse(BaseModel):
    """Response after creating a job"""
    job_id: str
    status: str
    message: str

class JobStatus(BaseModel):
    """Job status response"""
    job_id: str
    status: str
    state: Optional[str] = None
    tasks: Optional[Dict[str, str]] = None
    details: Optional[Dict[str, Any]] = None
    elapsed_seconds: Optional[float] = None
    error: Optional[str] = None

class ServerStatus(BaseModel):
    """Server status response"""
    status: str
    models_ready: bool
    active_jobs: int
    completed_jobs: int
    uptime_seconds: int

# =============================================================================
# HELPERS
# =============================================================================
START_TIME = datetime.now()

def check_models_ready() -> bool:
    """Check if ML models are extracted and ready."""
    return os.path.exists(MODELS_READY_FILE)

def read_progress_file(job_dir: Path) -> Optional[Dict]:
    """Read progress.txt from job directory."""
    progress_file = job_dir / 'progress.txt'
    if progress_file.exists():
        try:
            with open(progress_file, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return None

async def run_demucs_job(job_id: str, input_url: str, interval_cut: Optional[str], all_stems: bool):
    """Run demucs-separate in background."""
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    JOBS[job_id]['status'] = 'running'
    JOBS[job_id]['started_at'] = datetime.now().isoformat()

    # Build command
    cmd = [
        'python3', DEMUCS_CLI,
        '--input', input_url,
        '--output', str(job_dir)
    ]

    if interval_cut:
        cmd.extend(['--interval-cut', interval_cut])

    if all_stems:
        cmd.append('--all-stems')

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(job_dir)
        )

        stdout, _ = await process.communicate()

        if process.returncode == 0:
            JOBS[job_id]['status'] = 'completed'
            JOBS[job_id]['completed_at'] = datetime.now().isoformat()
        else:
            JOBS[job_id]['status'] = 'failed'
            JOBS[job_id]['error'] = stdout.decode() if stdout else 'Unknown error'

    except Exception as e:
        JOBS[job_id]['status'] = 'failed'
        JOBS[job_id]['error'] = str(e)

# =============================================================================
# FASTAPI APP
# =============================================================================
app = FastAPI(
    title="Demucs Separation API",
    description="Audio separation service using Demucs",
    version="1.0.0"
)

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/status", response_model=ServerStatus)
async def get_status():
    """Get server status."""
    uptime = int((datetime.now() - START_TIME).total_seconds())
    active = sum(1 for j in JOBS.values() if j['status'] == 'running')
    completed = sum(1 for j in JOBS.values() if j['status'] == 'completed')

    return ServerStatus(
        status="running",
        models_ready=check_models_ready(),
        active_jobs=active,
        completed_jobs=completed,
        uptime_seconds=uptime
    )

@app.post("/job", response_model=JobResponse)
async def create_job(request: JobRequest, background_tasks: BackgroundTasks):
    """Create a new separation job."""

    # Generate job ID
    job_id = request.job_id or str(uuid.uuid4())[:8]

    # Check if job already exists
    if job_id in JOBS:
        raise HTTPException(status_code=409, detail=f"Job {job_id} already exists")

    # Check models are ready
    if not check_models_ready():
        raise HTTPException(status_code=503, detail="Models not ready yet. Please wait.")

    # Create job entry
    JOBS[job_id] = {
        'status': 'pending',
        'input_url': request.input_url,
        'interval_cut': request.interval_cut,
        'all_stems': request.all_stems,
        'created_at': datetime.now().isoformat(),
        'started_at': None,
        'completed_at': None,
        'error': None
    }

    # Start background task
    background_tasks.add_task(
        run_demucs_job,
        job_id,
        request.input_url,
        request.interval_cut,
        request.all_stems
    )

    return JobResponse(
        job_id=job_id,
        status="pending",
        message=f"Job {job_id} created. Use GET /job/{job_id} to check progress."
    )

@app.get("/job/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Get job status including progress from progress.txt."""

    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    job = JOBS[job_id]
    job_dir = JOBS_DIR / job_id

    # Read progress file if job is running
    progress = None
    if job['status'] == 'running':
        progress = read_progress_file(job_dir)
    elif job['status'] == 'completed':
        progress = read_progress_file(job_dir)

    return JobStatus(
        job_id=job_id,
        status=job['status'],
        state=progress.get('state') if progress else None,
        tasks=progress.get('tasks') if progress else None,
        details=progress.get('details') if progress else None,
        elapsed_seconds=progress.get('elapsed_seconds') if progress else None,
        error=job.get('error')
    )

@app.get("/result/{job_id}")
async def get_result(job_id: str, file: str = "instrumental.mp3"):
    """Download result file from completed job."""

    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    job = JOBS[job_id]

    if job['status'] != 'completed':
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} is not completed. Status: {job['status']}"
        )

    job_dir = JOBS_DIR / job_id
    result_file = job_dir / file

    if not result_file.exists():
        # Try to find the file
        available = [f.name for f in job_dir.glob('*') if f.is_file()]
        raise HTTPException(
            status_code=404,
            detail=f"File '{file}' not found. Available: {available}"
        )

    return FileResponse(
        path=str(result_file),
        filename=file,
        media_type="audio/mpeg" if file.endswith('.mp3') else "application/octet-stream"
    )

@app.get("/jobs")
async def list_jobs(status: Optional[str] = None, limit: int = 50):
    """List all jobs."""
    jobs = []
    for job_id, job in list(JOBS.items())[-limit:]:
        if status is None or job['status'] == status:
            jobs.append({
                'job_id': job_id,
                'status': job['status'],
                'created_at': job['created_at'],
                'completed_at': job.get('completed_at')
            })

    return {"jobs": jobs, "total": len(JOBS)}

@app.delete("/job/{job_id}")
async def delete_job(job_id: str):
    """Delete a job and its files."""

    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    job = JOBS[job_id]

    if job['status'] == 'running':
        raise HTTPException(status_code=400, detail="Cannot delete running job")

    # Delete job directory
    job_dir = JOBS_DIR / job_id
    if job_dir.exists():
        import shutil
        shutil.rmtree(job_dir, ignore_errors=True)

    # Remove from jobs
    del JOBS[job_id]

    return {"status": "deleted", "job_id": job_id}

# =============================================================================
# MAIN
# =============================================================================
if __name__ == "__main__":
    import uvicorn

    print("=" * 50)
    print("  DEMUCS SEPARATION API SERVER")
    print("=" * 50)
    print(f"  Models ready: {check_models_ready()}")
    print(f"  Jobs directory: {JOBS_DIR}")
    print(f"  Port: 8185")
    print("=" * 50)

    uvicorn.run(app, host="0.0.0.0", port=8185, log_level="info")
