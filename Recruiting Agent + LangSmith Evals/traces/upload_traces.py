"""Load downloaded traces, shift timestamps to now, regenerate IDs, and upload.

Run from the lca-engine folder with:

    uv run python3 upload_traces.py
    uv run python3 upload_traces.py --project my-project --input downloaded_traces.json
"""

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from langsmith import Client, uuid7

# Project name comes from .env (LANGSMITH_PROJECT); override with --project.
DEFAULT_PROJECT = os.getenv("LANGSMITH_PROJECT")


def parse_dt(s):
    """Parse an ISO timestamp string into a naive (tz-stripped) datetime."""
    if s is None:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="Target project name")
    parser.add_argument("--input", default="downloaded_traces.json", help="Input file path")
    args = parser.parse_args()

    if not args.project:
        parser.error("No project name found. Set LANGSMITH_PROJECT in .env or pass --project.")

    with open(args.input) as f:
        runs = json.load(f)

    print(f"Loaded {len(runs)} runs from {args.input}")
    if not runs:
        print("Nothing to upload.")
        return

    # Shift timestamps so the traces appear recent: move the latest start_time to now,
    # and every other run by the same delta (preserving relative spacing).
    start_times = [parse_dt(r["start_time"]) for r in runs if r.get("start_time")]
    if not start_times:
        raise ValueError("No runs have a start_time; cannot compute time shift.")
    latest = max(start_times)
    time_delta = datetime.now(timezone.utc).replace(tzinfo=None) - latest
    print(f"Shifting timestamps by: {time_delta}")

    # Build a map from old IDs to fresh uuid7s (uuid7 is time-ordered).
    # For root runs, trace_id must equal id, so map both to the same new uuid7.
    id_map = {}
    for run in runs:
        if run.get("parent_run_id") is None:
            root_new_id = str(uuid7())
            id_map[run["id"]] = root_new_id
            id_map[run["trace_id"]] = root_new_id
    for run in runs:
        for field in ("id", "parent_run_id"):
            old_id = run.get(field)
            if old_id and old_id not in id_map:
                id_map[old_id] = str(uuid7())

    # Group runs by (new) trace id and transform onto the new IDs / shifted times.
    traces = defaultdict(list)
    for run in runs:
        trace_id = id_map[run["trace_id"]]
        traces[trace_id].append(
            {
                "id": id_map[run["id"]],
                "trace_id": trace_id,
                "dotted_order": None,  # populated below
                "parent_run_id": id_map.get(run.get("parent_run_id")),
                "name": run["name"],
                "run_type": run["run_type"],
                "inputs": run.get("inputs") or {},
                "outputs": run.get("outputs"),
                "error": run.get("error"),
                "extra": run.get("extra") or {},
                "tags": run.get("tags"),
                "start_time": parse_dt(run["start_time"]) + time_delta,
                "end_time": parse_dt(run["end_time"]) + time_delta if run.get("end_time") else None,
            }
        )

    client = Client()
    print(f"Uploading {len(traces)} traces to project '{args.project}'...")

    for i, (trace_id, trace_runs) in enumerate(traces.items()):
        # Sort: root first, then children by start_time.
        trace_runs.sort(key=lambda r: (r["parent_run_id"] is not None, r["start_time"]))

        # Build dotted_order by walking the parent chain, so nesting is correct
        # regardless of run order or start_time skew.
        runs_by_id = {run["id"]: run for run in trace_runs}
        dotted_orders = {}

        def build_dotted_order(run):
            rid = run["id"]
            if rid in dotted_orders:
                return dotted_orders[rid]
            ts = run["start_time"].strftime("%Y%m%dT%H%M%S%f") + "Z"
            segment = f"{ts}{rid}"
            parent = runs_by_id.get(run["parent_run_id"])
            order = segment if parent is None else f"{build_dotted_order(parent)}.{segment}"
            dotted_orders[rid] = order
            run["dotted_order"] = order
            return order

        for run in trace_runs:
            build_dotted_order(run)

        for run in trace_runs:
            client.create_run(
                id=run["id"],
                trace_id=run["trace_id"],
                dotted_order=run["dotted_order"],
                parent_run_id=run["parent_run_id"],
                name=run["name"],
                run_type=run["run_type"],
                inputs=run["inputs"],
                outputs=run.get("outputs"),
                error=run.get("error"),
                extra=run.get("extra"),
                tags=run.get("tags"),
                start_time=run["start_time"],
                end_time=run["end_time"],
                project_name=args.project,
            )

        if (i + 1) % 10 == 0:
            print(f"  Uploaded {i + 1}/{len(traces)} traces")

    # Wait for all background operations to complete.
    print("Flushing...")
    client.flush()
    print(f"Done! Uploaded {len(traces)} traces to '{args.project}'.")


if __name__ == "__main__":
    main()
