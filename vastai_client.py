#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Client Vast.ai pour orchestration Demucs audio separation.
"""

import os
import sys
import time
import json
import argparse
import uuid
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass
import requests

# =============================================================================
# ENVIRONMENT VARIABLES (Windows User Registry)
# =============================================================================
def get_env_var(name: str) -> Optional[str]:
    """Get environment variable from os.environ or Windows registry."""
    # First check os.environ
    value = os.environ.get(name)
    if value:
        return value

    # On Windows, try to read from user environment variables
    if sys.platform == 'win32':
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Environment', 0, winreg.KEY_READ)
            try:
                value, _ = winreg.QueryValueEx(key, name)
                winreg.CloseKey(key)
                return value
            except WindowsError:
                winreg.CloseKey(key)
        except Exception:
            pass

    return None


# =============================================================================
# CONSTANTS
# =============================================================================
VASTAI_API_URL = "https://console.vast.ai/api/v0"
DOCKER_IMAGE = "ghcr.io/cyrille8000/ffmpeg-demucs-vast-template:latest"
API_PORT = 8185
DEFAULT_DISK_GB = 20
MIN_VRAM_GB = 8  # Minimum VRAM for Demucs


# =============================================================================
# VAST.AI CLIENT
# =============================================================================
class VastAIClient:
    """Client for Vast.ai API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        self.active_instance_id = None

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """Make API request with API key auth."""
        url = f"{VASTAI_API_URL}{endpoint}?api_key={self.api_key}"

        response = requests.request(
            method,
            url,
            headers=self.headers,
            timeout=30,
            **kwargs
        )
        response.raise_for_status()
        return response.json()

    def search_offers(self,
                     min_gpu_ram: int = MIN_VRAM_GB,
                     gpu_name: Optional[str] = None,
                     max_results: int = 100) -> List[Dict]:
        """
        Search available GPU offers.

        Args:
            min_gpu_ram: Minimum GPU RAM in GB
            gpu_name: Filter by GPU name (e.g., "RTX 3090")
            max_results: Maximum number of results

        Returns:
            List of available offers sorted by price
        """
        params = {
            "q": json.dumps({
                "verified": {"eq": True},
                "external": {"eq": False},
                "rentable": {"eq": True},
                "gpu_ram": {"gte": min_gpu_ram * 1024},  # Convert to MB
                "disk_space": {"gte": DEFAULT_DISK_GB},
                "cuda_max_good": {"gte": 11.0},  # CUDA 11+ required
            }),
            "order": [["dph_total", "asc"]],  # Sort by price ascending
            "type": "on-demand"
        }

        if gpu_name:
            params["q"]["gpu_name"] = {"eq": gpu_name}

        endpoint = f"/bundles/?{requests.compat.urlencode(params)}"

        try:
            response = self._request("GET", endpoint)

            if not response or "offers" not in response:
                return []

            offers = response["offers"]

            # Parse and format offers
            available = []
            for offer in offers[:max_results]:
                available.append({
                    "id": offer.get("id"),
                    "gpu_name": offer.get("gpu_name", "Unknown"),
                    "gpu_ram": offer.get("gpu_ram", 0) / 1024,  # Convert to GB
                    "num_gpus": offer.get("num_gpus", 1),
                    "price_per_hour": offer.get("dph_total", 999),
                    "disk_space": offer.get("disk_space", 0),
                    "cuda_version": offer.get("cuda_max_good", 0),
                    "reliability": offer.get("reliability2", 0),
                    "inet_up": offer.get("inet_up", 0),
                    "inet_down": offer.get("inet_down", 0),
                })

            return available

        except Exception as e:
            print(f"Error searching offers: {e}")
            return []

    def get_ranked_offers(self, max_results: int = 20) -> List[Dict]:
        """Get offers ranked by price and reliability."""
        offers = self.search_offers(max_results=max_results * 2)

        if not offers:
            return []

        # Filter by reliability (>= 0.9) and sort by price
        reliable = [o for o in offers if o.get("reliability", 0) >= 0.9]
        reliable.sort(key=lambda x: x["price_per_hour"])

        return reliable[:max_results]

    def create_instance(self,
                       offer_id: int,
                       image: str = DOCKER_IMAGE,
                       disk_gb: int = DEFAULT_DISK_GB,
                       label: str = "demucs-worker") -> Dict:
        """
        Create a new instance from an offer.

        Args:
            offer_id: Offer ID to accept
            image: Docker image to use
            disk_gb: Disk space in GB
            label: Instance label

        Returns:
            Instance details
        """
        payload = {
            "client_id": "me",
            "image": image,
            "disk": disk_gb,
            "label": label,
            "onstart": "/start.sh",
            "runtype": "ssh",
            "image_login": "",
            "python_utf8": False,
            "lang_utf8": False,
            "use_jupyter_lab": False,
            "jupyter_dir": None,
            "create_from": None,
            "force": False,
        }

        endpoint = f"/asks/{offer_id}/"

        try:
            result = self._request("PUT", endpoint, json=payload)

            if result.get("success"):
                instance_id = result.get("new_contract")
                self.active_instance_id = instance_id
                return {
                    "id": instance_id,
                    "offer_id": offer_id,
                    "success": True
                }
            else:
                raise Exception(f"Failed to create instance: {result}")

        except Exception as e:
            raise Exception(f"Failed to create instance: {e}")

    def get_instance(self, instance_id: int) -> Dict:
        """Get instance details and status."""
        endpoint = f"/instances/{instance_id}/"

        try:
            result = self._request("GET", endpoint)

            if "instances" in result:
                # API returns object for single instance, array for list
                instances_data = result["instances"]

                # Handle both object and array responses
                if isinstance(instances_data, dict):
                    instance = instances_data
                elif isinstance(instances_data, list) and len(instances_data) > 0:
                    instance = instances_data[0]
                else:
                    return {"id": instance_id, "status": "not_found"}

                return {
                    "id": instance.get("id"),
                    "status": instance.get("actual_status", "unknown"),
                    "ssh_host": instance.get("ssh_host"),
                    "ssh_port": instance.get("ssh_port"),
                    "direct_port_start": instance.get("direct_port_start"),
                    "direct_port_end": instance.get("direct_port_end"),
                    "direct_port_count": instance.get("direct_port_count"),
                    "gpu_name": instance.get("gpu_name"),
                    "cost_per_hour": instance.get("dph_total", 0),
                    "public_ipaddr": instance.get("public_ipaddr"),
                    "ports": instance.get("ports", {}),
                }
            else:
                return {"id": instance_id, "status": "not_found"}

        except Exception as e:
            print(f"Error getting instance: {e}")
            return {"id": instance_id, "status": "error"}

    def destroy_instance(self, instance_id: int) -> bool:
        """Destroy an instance."""
        endpoint = f"/instances/{instance_id}/"

        try:
            result = self._request("DELETE", endpoint)
            return result.get("success", False)
        except Exception as e:
            print(f"Error destroying instance: {e}")
            return False

    def wait_for_instance_ready(self, instance_id: int, timeout: int = 600) -> Optional[str]:
        """
        Wait for instance to be ready and return API URL.

        First boot can take 5-10min (model extraction ~3GB).

        Returns:
            API URL (http://host:port) or None if timeout
        """
        start = time.time()

        print(f"Waiting for instance {instance_id} to be ready...")
        print("  (First boot: ~5-10min for model extraction)")

        while time.time() - start < timeout:
            instance = self.get_instance(instance_id)
            status = instance.get("status", "unknown")

            if status == "running":
                # Instance is running, check if ports are assigned
                public_ip = instance.get("public_ipaddr")
                ports_map = instance.get("ports", {})

                # Look for port 8185/tcp in the ports mapping
                api_port_info = ports_map.get("8185/tcp")

                if public_ip and api_port_info and len(api_port_info) > 0:
                    # Extract external port from mapping
                    external_port = api_port_info[0].get("HostPort")

                    if external_port:
                        api_url = f"http://{public_ip}:{external_port}"

                        # Test if API is responsive
                        try:
                            response = requests.get(f"{api_url}/health", timeout=5)
                            if response.status_code == 200:
                                elapsed = int(time.time() - start)
                                print(f"\n  Instance ready! API URL: {api_url}")
                                print(f"  Startup time: {elapsed}s")
                                print(f"  Port mapping: 8185 -> {external_port}")
                                return api_url
                        except Exception as e:
                            # API not ready yet, continue waiting
                            pass

            print(".", end="", flush=True)
            time.sleep(10)

        print(f"\nTimeout waiting for instance {instance_id} after {timeout}s")
        return None


# =============================================================================
# DEMUCS CLIENT (API interaction)
# =============================================================================
class DemucsClient:
    """Client for Demucs API on instance."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def health_check(self) -> bool:
        """Check if API is healthy."""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=10)
            return response.status_code == 200
        except:
            return False

    def get_status(self) -> Dict:
        """Get server status."""
        response = requests.get(f"{self.base_url}/status", timeout=10)
        response.raise_for_status()
        return response.json()

    def create_job(self, input_url: str, interval_cut: Optional[str] = None) -> str:
        """Create a separation job."""
        payload = {"input_url": input_url}
        if interval_cut:
            payload["interval_cut"] = interval_cut

        response = requests.post(
            f"{self.base_url}/job",
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        result = response.json()
        return result["job_id"]

    def get_job_status(self, job_id: str) -> Dict:
        """Get job status."""
        response = requests.get(f"{self.base_url}/job/{job_id}", timeout=60)
        response.raise_for_status()
        return response.json()

    def get_job_logs(self, job_id: str, offset: int = 0) -> Dict:
        """
        Get job logs from offset position.

        Args:
            job_id: Job ID
            offset: Byte offset to start reading from

        Returns:
            {"logs": str, "offset": int, "status": str}
        """
        response = requests.get(
            f"{self.base_url}/job/{job_id}/logs",
            params={"offset": offset},
            timeout=30
        )
        response.raise_for_status()
        return response.json()

    def download_result(self, job_id: str, output_path: str):
        """Download job result."""
        response = requests.get(f"{self.base_url}/result/{job_id}", stream=True, timeout=60)
        response.raise_for_status()

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

    def wait_for_job(self, job_id: str, timeout: int = 1800, stream_logs: bool = True) -> Dict:
        """
        Wait for job to complete with optional log streaming.

        Args:
            job_id: Job ID to wait for
            timeout: Maximum wait time in seconds
            stream_logs: If True, stream logs in real-time

        Returns:
            Final job status dict
        """
        start = time.time()
        log_offset = 0
        last_status = None

        while time.time() - start < timeout:
            status = self.get_job_status(job_id)

            if status["status"] == "completed":
                # Get final logs
                if stream_logs:
                    log_data = self.get_job_logs(job_id, log_offset)
                    if log_data.get("logs"):
                        print(log_data["logs"], end="")
                return status
            elif status["status"] == "failed":
                # Get final logs
                if stream_logs:
                    log_data = self.get_job_logs(job_id, log_offset)
                    if log_data.get("logs"):
                        print(log_data["logs"], end="")
                raise Exception(f"Job failed: {status.get('error')}")

            # Stream logs if enabled
            if stream_logs:
                try:
                    log_data = self.get_job_logs(job_id, log_offset)
                    new_logs = log_data.get("logs", "")
                    if new_logs:
                        print(new_logs, end="", flush=True)
                        log_offset = log_data.get("offset", log_offset)
                except Exception as e:
                    # Log streaming failed, fall back to progress display
                    stream_logs = False
                    print(f"\nLog streaming failed: {e}")
                    print("Falling back to progress display...")

            # Show progress if not streaming logs or as fallback
            if not stream_logs:
                details = status.get("details") or {}
                completed = details.get("completed_segments", 0)
                total = details.get("total_segments", 0)

                if total > 0:
                    percent = (completed / total) * 100
                    print(f"\rProgress: {percent:.0f}% ({completed}/{total})", end="", flush=True)

            time.sleep(5)

        raise Exception(f"Job timeout after {timeout}s")


# =============================================================================
# CLI COMMANDS
# =============================================================================
def cmd_list_offers(args):
    """List available GPU offers."""
    client = VastAIClient(get_env_var("VASTAI_API_KEY") or "")
    offers = client.get_ranked_offers(max_results=20)

    print(f"\n{'GPU Name':<30} {'RAM':<8} {'$/hr':<10} {'Reliability':<12} {'CUDA'}")
    print("-" * 80)

    for offer in offers:
        reliability = f"{offer['reliability']:.2f}"
        cuda = f"{offer['cuda_version']:.1f}"
        print(f"{offer['gpu_name']:<30} {offer['gpu_ram']:<8.0f}GB ${offer['price_per_hour']:<9.3f} {reliability:<12} {cuda}")


def cmd_separate(args):
    """Full workflow: create instance, run job, download, destroy."""
    api_key = get_env_var("VASTAI_API_KEY")
    if not api_key:
        print("ERROR: VASTAI_API_KEY not set")
        sys.exit(1)

    vastai = VastAIClient(api_key)

    # Find best offer
    print("Finding available GPUs...")
    offers = vastai.get_ranked_offers(max_results=10)

    if not offers:
        print("No GPUs available")
        sys.exit(1)

    instance = None
    for offer in offers:
        print(f"Trying: {offer['gpu_name']} (${offer['price_per_hour']:.3f}/hr)...")
        try:
            instance = vastai.create_instance(offer["id"])
            break
        except Exception as e:
            print(f"  Failed: {e}")

    if not instance:
        print("Failed to create instance")
        sys.exit(1)

    instance_id = instance["id"]
    print(f"Instance created: {instance_id}")

    try:
        # Wait for instance ready
        api_url = vastai.wait_for_instance_ready(instance_id, timeout=600)
        if not api_url:
            raise Exception("Instance failed to start")

        # Create job
        demucs = DemucsClient(api_url)
        print(f"\nCreating job: {args.input_url}")
        job_id = demucs.create_job(args.input_url, args.interval_cut)
        print(f"Job ID: {job_id}")

        # Wait for completion
        print("\nWaiting for job completion...")
        status = demucs.wait_for_job(job_id, timeout=1800)
        print(f"\nJob completed!")

        # Download result
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "instrumental.mp3"

        print(f"Downloading: {output_file}")
        demucs.download_result(job_id, str(output_file))

        print(f"\nDone! Result: {output_file}")

    finally:
        if not args.keep_instance:
            print(f"\nDestroying instance {instance_id}...")
            vastai.destroy_instance(instance_id)


def cmd_destroy(args):
    """Destroy an instance."""
    api_key = get_env_var("VASTAI_API_KEY")
    if not api_key:
        print("ERROR: VASTAI_API_KEY not set")
        sys.exit(1)

    client = VastAIClient(api_key)
    success = client.destroy_instance(args.instance_id)

    if success:
        print(f"Instance {args.instance_id} destroyed")
    else:
        print(f"Failed to destroy instance {args.instance_id}")


# =============================================================================
# MAIN
# =============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Vast.ai client for Demucs audio separation",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # list-offers command
    list_parser = subparsers.add_parser("list-offers", aliases=["offers"], help="List available GPU offers")
    list_parser.set_defaults(func=cmd_list_offers)

    # separate command
    sep_parser = subparsers.add_parser("separate", help="Full workflow: create instance, run job, download, destroy")
    sep_parser.add_argument("input_url", help="Input audio URL")
    sep_parser.add_argument("--output", "-o", default="./results", help="Output directory")
    sep_parser.add_argument("--interval-cut", help="Cut intervals in seconds (e.g., '300,600,900')")
    sep_parser.add_argument("--keep-instance", action="store_true", help="Keep instance running after job")
    sep_parser.set_defaults(func=cmd_separate)

    # destroy command
    destroy_parser = subparsers.add_parser("destroy", help="Destroy an instance")
    destroy_parser.add_argument("instance_id", type=int, help="Instance ID to destroy")
    destroy_parser.set_defaults(func=cmd_destroy)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
