#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test de capacité d'instances Vast.ai simultanées.
Lance N instances séquentiellement et garde leurs IDs pour arrêt manuel.
"""

import os
import sys
import time
import json
from datetime import datetime
from typing import List, Dict

# Import Vast.ai client
from vastai_client import VastAIClient

INSTANCES_FILE = "active_instances.json"


class InstanceTester:
    """Testeur d'instances concurrentes."""

    def __init__(self, num_instances: int = 50):
        self.num_instances = num_instances

        # Get API key
        api_key = os.environ.get("VASTAI_API_KEY")
        if not api_key:
            raise Exception("VASTAI_API_KEY not set")

        self.vastai = VastAIClient(api_key)
        self.instances: List[Dict] = []
        self.success_count = 0
        self.fail_count = 0
        self.offer_index = 0  # Pour round-robin

        # Get available offers once
        print("Fetching available GPU offers...")
        self.available_offers = self.vastai.get_ranked_offers(max_results=20)
        if not self.available_offers:
            raise Exception("No GPU offers available")

        print(f"Found {len(self.available_offers)} GPU offers:")
        for i, offer in enumerate(self.available_offers[:10]):
            print(f"  [{i}] {offer['gpu_name']} - ${offer['price_per_hour']:.3f}/hr (reliability: {offer['reliability']:.2f})")
        print()

    def get_next_offer(self) -> Dict:
        """Sélectionne la prochaine offre en round-robin."""
        offer = self.available_offers[self.offer_index % len(self.available_offers)]
        self.offer_index += 1
        return offer

    def launch_instance(self, instance_index: int) -> Dict:
        """Lance une instance et retourne ses infos."""
        try:
            # Sélectionner l'offre (séquentiel, pas de race condition)
            offer = self.get_next_offer()

            print(f"[{instance_index:02d}] Launching instance on {offer['gpu_name']}...", end=" ", flush=True)

            # Create instance
            instance = self.vastai.create_instance(
                offer_id=offer['id'],
                label=f"test-concurrent-{instance_index:02d}"
            )

            if not instance or not instance.get("success"):
                raise Exception("Instance creation failed")

            instance_id = instance['id']
            print(f"✓ {instance_id}")

            self.success_count += 1
            instance_info = {
                'index': instance_index,
                'id': instance_id,
                'offer_id': offer['id'],
                'gpu': offer['gpu_name'],
                'price': offer['price_per_hour'],
                'created_at': datetime.now().isoformat()
            }
            self.instances.append(instance_info)

            return instance_info

        except Exception as e:
            print(f"✗ {e}")
            self.fail_count += 1
            return None

    def save_instances(self):
        """Sauvegarde les IDs des instances dans un fichier."""
        with open(INSTANCES_FILE, 'w') as f:
            json.dump(self.instances, f, indent=2)
        print(f"\nInstances saved to: {INSTANCES_FILE}")

    def run(self):
        """Lance toutes les instances séquentiellement."""
        print("="*70)
        print(f"Vast.ai Sequential Launch Test")
        print("="*70)
        print(f"Target instances: {self.num_instances}")
        print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70)
        print()

        start_time = time.time()

        # Launch instances sequentially
        for i in range(self.num_instances):
            self.launch_instance(i)

        launch_time = time.time() - start_time

        print()
        print("="*70)
        print(f"Launch completed in {launch_time:.1f}s")
        print(f"  Success: {self.success_count}/{self.num_instances} ({100*self.success_count/self.num_instances:.1f}%)")
        print(f"  Failed: {self.fail_count}/{self.num_instances}")
        print("="*70)
        print()

        if self.success_count == 0:
            print("No instances created successfully.")
            return

        # Show active instances by GPU
        print(f"Active instances ({len(self.instances)}):")
        print()

        # Group by GPU
        gpu_groups = {}
        for inst in self.instances:
            gpu_name = inst['gpu']
            if gpu_name not in gpu_groups:
                gpu_groups[gpu_name] = []
            gpu_groups[gpu_name].append(inst)

        for gpu_name, instances in sorted(gpu_groups.items()):
            print(f"{gpu_name} ({len(instances)} instances):")
            for inst in instances:
                print(f"  [{inst['index']:02d}] {inst['id']}")
            print()

        # Save instances to file
        self.save_instances()

        print()
        print("="*70)
        print("Instances are running. To destroy all instances, run:")
        print(f"  python {sys.argv[0]} --destroy-all")
        print("="*70)


def destroy_all_instances():
    """Arrête toutes les instances enregistrées."""
    if not os.path.exists(INSTANCES_FILE):
        print(f"ERROR: {INSTANCES_FILE} not found")
        print("No active instances to destroy.")
        return

    with open(INSTANCES_FILE, 'r') as f:
        instances = json.load(f)

    if not instances:
        print("No active instances found.")
        return

    print(f"Destroying {len(instances)} instance(s)...")
    print()

    api_key = os.environ.get("VASTAI_API_KEY")
    if not api_key:
        print("ERROR: VASTAI_API_KEY not set")
        return

    vastai = VastAIClient(api_key)

    success = 0
    failed = 0

    for inst in instances:
        try:
            inst_id = inst['id']
            inst_index = inst['index']
            print(f"[{inst_index:02d}] Destroying {inst_id}...", end=" ", flush=True)
            vastai.destroy_instance(inst_id)
            print("✓")
            success += 1
        except Exception as e:
            print(f"✗ {e}")
            failed += 1

    print()
    print(f"Destroyed: {success}/{len(instances)}")
    if failed > 0:
        print(f"Failed: {failed}")

    # Remove file after destroying
    os.remove(INSTANCES_FILE)
    print(f"\nRemoved {INSTANCES_FILE}")


def main():
    """Point d'entrée."""
    import argparse

    parser = argparse.ArgumentParser(description="Test Vast.ai concurrent instances capacity")
    parser.add_argument("--num-instances", "-n", type=int, default=50,
                       help="Number of instances to launch (default: 50)")
    parser.add_argument("--destroy-all", action="store_true",
                       help="Destroy all active instances")

    args = parser.parse_args()

    # Check API key
    if not os.environ.get("VASTAI_API_KEY"):
        print("ERROR: VASTAI_API_KEY environment variable not set")
        sys.exit(1)

    # Destroy all instances if requested
    if args.destroy_all:
        destroy_all_instances()
        return

    # Run test
    tester = InstanceTester(num_instances=args.num_instances)

    try:
        tester.run()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        if tester.instances:
            print("Saving instance IDs before exit...")
            tester.save_instances()
            print(f"\nTo destroy instances later, run: python {sys.argv[0]} --destroy-all")


if __name__ == "__main__":
    main()
