#!/usr/bin/env python3
"""
RunPod Client for Demucs Separation
====================================
Local Python script to:
  1. Find cheapest available GPU on RunPod
  2. Start a pod with the demucs template
  3. Submit jobs and monitor progress
  4. Download results

Usage:
    # Set API key
    export RUNPOD_API_KEY="your_api_key"

    # Separate audio
    python runpod_client.py separate "https://example.com/audio.mp3" --output ./results

    # With custom intervals
    python runpod_client.py separate "https://example.com/audio.mp3" --interval-cut "300,600,900"

    # List available GPUs
    python runpod_client.py gpus

    # Stop pod when done
    python runpod_client.py stop
"""

import os
import sys
import json
import time
import argparse
import requests
from pathlib import Path
from typing import Optional, Dict, Any, List

__VERSION__ = '1.0.0'

# =============================================================================
# CONFIGURATION
# =============================================================================
RUNPOD_API_URL = "https://api.runpod.io/graphql"
DOCKER_IMAGE = "ghcr.io/cyrille8000/ffmpeg-demucs-vast-template:latest"
MIN_VRAM_GB = 8  # Minimum VRAM for Demucs
DEFAULT_DISK_GB = 20
API_PORT = 8185

# GPU preferences (sorted by price/performance)
PREFERRED_GPUS = [
    "NVIDIA RTX 3090",
    "NVIDIA RTX 4090",
    "NVIDIA RTX A4000",
    "NVIDIA RTX A5000",
    "NVIDIA A40",
    "NVIDIA RTX 3080",
    "NVIDIA RTX 4080",
]

# =============================================================================
# API CLIENT
# =============================================================================
class RunPodClient:
    """Client for RunPod API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Content-Type": "application/json"
        }
        self.active_pod_id = None
        self.pod_url = None

    def _graphql(self, query: str, variables: Dict = None) -> Dict:
        """Execute GraphQL query."""
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        # API key goes in URL, not header
        url = f"{RUNPOD_API_URL}?api_key={self.api_key}"

        response = requests.post(
            url,
            headers=self.headers,
            json=payload,
            timeout=30
        )
        response.raise_for_status()
        return response.json()

    def get_available_gpus(self) -> List[Dict]:
        """Get list of available GPU types with pricing."""
        query = """
        query GpuTypes {
            gpuTypes {
                id
                displayName
                memoryInGb
                secureCloud
                communityCloud
                lowestPrice(input: {gpuCount: 1}) {
                    minimumBidPrice
                    uninterruptablePrice
                }
            }
        }
        """
        result = self._graphql(query)

        if "errors" in result:
            raise Exception(f"GraphQL error: {result['errors']}")

        gpus = result.get("data", {}).get("gpuTypes", [])

        # Filter and sort by price
        available = []
        for gpu in gpus:
            if gpu.get("memoryInGb", 0) >= MIN_VRAM_GB:
                price_info = gpu.get("lowestPrice", {}) or {}
                price = price_info.get("minimumBidPrice") or price_info.get("uninterruptablePrice") or 999

                available.append({
                    "id": gpu["id"],
                    "name": gpu.get("displayName", gpu["id"]),
                    "vram_gb": gpu.get("memoryInGb", 0),
                    "price_per_hour": price,
                    "secure": gpu.get("secureCloud", False),
                    "community": gpu.get("communityCloud", False)
                })

        # Sort by price (cheapest first)
        available.sort(key=lambda x: x["price_per_hour"])
        return available

    def find_cheapest_gpu(self) -> Optional[Dict]:
        """Find the cheapest available GPU."""
        gpus = self.get_ranked_gpus()
        return gpus[0] if gpus else None

    def get_ranked_gpus(self, max_results: int = 10) -> List[Dict]:
        """Get GPUs ranked by preference (preferred GPUs first, then by price)."""
        gpus = self.get_available_gpus()

        if not gpus:
            return []

        # Build ranked list: preferred GPUs first (if cheap), then rest by price
        ranked = []
        used_ids = set()

        # First: add preferred GPUs from top 10 cheapest
        for preferred in PREFERRED_GPUS:
            for gpu in gpus[:10]:
                if preferred.lower() in gpu["name"].lower() and gpu["id"] not in used_ids:
                    ranked.append(gpu)
                    used_ids.add(gpu["id"])
                    break

        # Then: add remaining GPUs by price
        for gpu in gpus:
            if gpu["id"] not in used_ids:
                ranked.append(gpu)
                used_ids.add(gpu["id"])

        return ranked[:max_results]

    def try_create_pod(self, gpu_id: str, name: str = "demucs-worker") -> Optional[Dict]:
        """Try to create a pod, return None if GPU unavailable."""
        try:
            return self.create_pod(gpu_id, name)
        except Exception as e:
            error_msg = str(e).lower()
            if "resources" in error_msg or "not have" in error_msg:
                return None  # GPU unavailable, caller should try next
            raise  # Other error, propagate

    def create_pod(self, gpu_id: str, name: str = "demucs-worker") -> Dict:
        """Create a new pod with the demucs template."""
        mutation = """
        mutation CreatePod($input: PodFindAndDeployOnDemandInput!) {
            podFindAndDeployOnDemand(input: $input) {
                id
                name
                imageName
                gpuCount
                costPerHr
                desiredStatus
                runtime {
                    uptimeInSeconds
                    ports {
                        ip
                        isIpPublic
                        privatePort
                        publicPort
                        type
                    }
                }
            }
        }
        """

        variables = {
            "input": {
                "cloudType": "ALL",
                "gpuCount": 1,
                "gpuTypeId": gpu_id,
                "name": name,
                "imageName": DOCKER_IMAGE,
                "containerDiskInGb": DEFAULT_DISK_GB,
                "volumeInGb": 0,
                "ports": f"{API_PORT}/http",
                "startSsh": False
            }
        }

        result = self._graphql(mutation, variables)

        if "errors" in result:
            raise Exception(f"Failed to create pod: {result['errors']}")

        pod = result.get("data", {}).get("podFindAndDeployOnDemand", {})
        self.active_pod_id = pod.get("id")
        return pod

    def get_pod(self, pod_id: str) -> Dict:
        """Get pod status and details."""
        query = """
        query Pod($podId: String!) {
            pod(input: { podId: $podId }) {
                id
                name
                imageName
                desiredStatus
                lastStatusChange
                runtime {
                    uptimeInSeconds
                    ports {
                        ip
                        isIpPublic
                        privatePort
                        publicPort
                        type
                    }
                }
            }
        }
        """

        result = self._graphql(query, {"podId": pod_id})

        if "errors" in result:
            raise Exception(f"Failed to get pod: {result['errors']}")

        return result.get("data", {}).get("pod", {})

    def stop_pod(self, pod_id: str) -> bool:
        """Stop and terminate a pod."""
        mutation = """
        mutation TerminatePod($podId: String!) {
            podTerminate(input: { podId: $podId })
        }
        """

        result = self._graphql(mutation, {"podId": pod_id})

        if "errors" in result:
            raise Exception(f"Failed to stop pod: {result['errors']}")

        return True

    def wait_for_pod_ready(self, pod_id: str, timeout: int = 300) -> str:
        """Wait for pod to be ready and return the API URL."""
        print(f"Waiting for pod {pod_id} to be ready...")

        start = time.time()
        while time.time() - start < timeout:
            pod = self.get_pod(pod_id)

            runtime = pod.get("runtime", {})
            ports = runtime.get("ports", [])

            # Find the API port
            for port in ports:
                if port.get("privatePort") == API_PORT:
                    ip = port.get("ip")
                    public_port = port.get("publicPort")

                    if ip and public_port:
                        url = f"http://{ip}:{public_port}"

                        # Test health endpoint
                        try:
                            response = requests.get(f"{url}/health", timeout=5)
                            if response.status_code == 200:
                                print(f"Pod ready! API URL: {url}")
                                self.pod_url = url
                                return url
                        except requests.exceptions.RequestException:
                            pass

            print(".", end="", flush=True)
            time.sleep(5)

        raise TimeoutError(f"Pod {pod_id} did not become ready in {timeout}s")


# =============================================================================
# DEMUCS API CLIENT
# =============================================================================
class DemucsClient:
    """Client for Demucs API on the pod."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def health(self) -> Dict:
        """Check API health."""
        response = requests.get(f"{self.base_url}/health", timeout=10)
        response.raise_for_status()
        return response.json()

    def status(self) -> Dict:
        """Get server status."""
        response = requests.get(f"{self.base_url}/status", timeout=10)
        response.raise_for_status()
        return response.json()

    def create_job(
        self,
        input_url: str,
        interval_cut: Optional[str] = None,
        all_stems: bool = False,
        job_id: Optional[str] = None
    ) -> Dict:
        """Create a new separation job."""
        payload = {
            "input_url": input_url,
            "all_stems": all_stems
        }

        if interval_cut:
            payload["interval_cut"] = interval_cut

        if job_id:
            payload["job_id"] = job_id

        response = requests.post(
            f"{self.base_url}/job",
            json=payload,
            timeout=30
        )
        response.raise_for_status()
        return response.json()

    def get_job(self, job_id: str) -> Dict:
        """Get job status."""
        response = requests.get(f"{self.base_url}/job/{job_id}", timeout=10)
        response.raise_for_status()
        return response.json()

    def download_result(self, job_id: str, output_path: Path, filename: str = "instrumental.mp3"):
        """Download result file."""
        response = requests.get(
            f"{self.base_url}/result/{job_id}",
            params={"file": filename},
            stream=True,
            timeout=300
        )
        response.raise_for_status()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        print(f"Downloaded: {output_path}")

    def wait_for_job(self, job_id: str, timeout: int = 1800) -> Dict:
        """Wait for job to complete."""
        print(f"Waiting for job {job_id}...")

        start = time.time()
        last_progress = ""

        while time.time() - start < timeout:
            job = self.get_job(job_id)
            status = job.get("status")

            if status == "completed":
                print("\nJob completed!")
                return job

            if status == "failed":
                raise Exception(f"Job failed: {job.get('error')}")

            # Show progress
            details = job.get("details", {})
            progress = f"{details.get('percent', 0)}%" if details else ""

            if progress != last_progress:
                print(f"Progress: {progress}")
                last_progress = progress

            time.sleep(5)

        raise TimeoutError(f"Job {job_id} did not complete in {timeout}s")


# =============================================================================
# CLI COMMANDS
# =============================================================================
def cmd_gpus(args):
    """List available GPUs."""
    client = RunPodClient(os.environ.get("RUNPOD_API_KEY", ""))
    gpus = client.get_available_gpus()

    print(f"\n{'GPU Name':<30} {'VRAM':<8} {'$/hr':<10} {'Available'}")
    print("-" * 60)

    for gpu in gpus[:20]:
        available = "Community" if gpu["community"] else ("Secure" if gpu["secure"] else "No")
        print(f"{gpu['name']:<30} {gpu['vram_gb']:<8} ${gpu['price_per_hour']:<9.3f} {available}")


def cmd_separate(args):
    """Run audio separation."""
    api_key = os.environ.get("RUNPOD_API_KEY")
    if not api_key:
        print("Error: RUNPOD_API_KEY environment variable not set")
        sys.exit(1)

    runpod = RunPodClient(api_key)

    # Get ranked GPUs
    print("Finding available GPUs...")
    gpus = runpod.get_ranked_gpus(max_results=10)

    if not gpus:
        print("Error: No GPU available")
        sys.exit(1)

    # Try to create pod with each GPU until one works
    pod = None
    selected_gpu = None

    for gpu in gpus:
        print(f"Trying: {gpu['name']} ({gpu['vram_gb']}GB) @ ${gpu['price_per_hour']:.3f}/hr")

        pod = runpod.try_create_pod(gpu["id"])
        if pod:
            selected_gpu = gpu
            break
        else:
            print(f"  -> Not available, trying next...")

    if not pod:
        print("Error: Could not find any available GPU. Try again later.")
        sys.exit(1)

    pod_id = pod["id"]
    print(f"Pod created: {pod_id} on {selected_gpu['name']}")

    try:
        # Wait for pod
        url = runpod.wait_for_pod_ready(pod_id)
        demucs = DemucsClient(url)

        # Check models ready
        status = demucs.status()
        if not status.get("models_ready"):
            print("Waiting for models to be extracted...")
            for _ in range(60):  # Wait up to 5 min
                time.sleep(5)
                status = demucs.status()
                if status.get("models_ready"):
                    break
                print(".", end="", flush=True)
            print()

        # Create job
        print(f"\nStarting separation job...")
        job = demucs.create_job(
            input_url=args.input,
            interval_cut=args.interval_cut,
            all_stems=args.all_stems
        )
        job_id = job["job_id"]
        print(f"Job ID: {job_id}")

        # Wait for completion
        demucs.wait_for_job(job_id)

        # Download result
        output = Path(args.output) / "instrumental.mp3"
        demucs.download_result(job_id, output)

        print(f"\nDone! Result: {output}")

    finally:
        if not args.keep_pod:
            print(f"\nStopping pod {pod_id}...")
            runpod.stop_pod(pod_id)
            print("Pod stopped.")


def cmd_stop(args):
    """Stop the active pod."""
    api_key = os.environ.get("RUNPOD_API_KEY")
    if not api_key:
        print("Error: RUNPOD_API_KEY environment variable not set")
        sys.exit(1)

    if not args.pod_id:
        print("Error: --pod-id required")
        sys.exit(1)

    client = RunPodClient(api_key)
    client.stop_pod(args.pod_id)
    print(f"Pod {args.pod_id} stopped.")


# =============================================================================
# MAIN
# =============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="RunPod client for Demucs audio separation",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__VERSION__}")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # gpus command
    gpus_parser = subparsers.add_parser("gpus", help="List available GPUs")
    gpus_parser.set_defaults(func=cmd_gpus)

    # separate command
    sep_parser = subparsers.add_parser("separate", help="Separate audio from URL")
    sep_parser.add_argument("input", help="URL of audio file")
    sep_parser.add_argument("--output", "-o", default="./results", help="Output directory")
    sep_parser.add_argument("--interval-cut", help="Custom cut timestamps (e.g. '300,600,900')")
    sep_parser.add_argument("--all-stems", action="store_true", help="Extract all stems")
    sep_parser.add_argument("--keep-pod", action="store_true", help="Don't stop pod after job")
    sep_parser.set_defaults(func=cmd_separate)

    # stop command
    stop_parser = subparsers.add_parser("stop", help="Stop a pod")
    stop_parser.add_argument("--pod-id", required=True, help="Pod ID to stop")
    stop_parser.set_defaults(func=cmd_stop)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
