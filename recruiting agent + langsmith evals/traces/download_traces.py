"""Download all runs from a LangSmith project and save them to a JSON file.

Run from the lca-engine folder with:

    uv run python3 download_traces.py
    uv run python3 download_traces.py --project lca-engine --output downloaded_traces.json
"""

import argparse
import json
import os
import re
import uuid
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from langsmith import Client

# Project name comes from .env (LANGSMITH_PROJECT); override with --project.
DEFAULT_PROJECT = os.getenv("LANGSMITH_PROJECT")

# Runtime tracebacks (captured in run.error and sometimes inputs/outputs) bake in
# the absolute path of the local install, e.g.
#   /Users/<you>/.../lca-engine/.venv/lib/python3.13/site-packages/...
# That leaks the author's home directory into the committed traces. Rewrite any
# such local project path to a neutral "/app" so the file is portable and clean.
# The regex matches a POSIX home-style prefix up to and including the project dir.
_LOCAL_PATH_RE = re.compile(r"/(?:Users|home)/[^\s\"'\\]*?/lca-engine")


def scrub(text):
    """Replace local absolute project paths with a neutral '/app' prefix."""
    return _LOCAL_PATH_RE.sub("/app", text)


def serialize(obj):
    """JSON serializer for objects not serializable by default (datetime, UUID)."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, uuid.UUID):
        return str(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="Source project name")
    parser.add_argument("--output", default="downloaded_traces.json", help="Output file path")
    args = parser.parse_args()

    if not args.project:
        parser.error("No project name found. Set LANGSMITH_PROJECT in .env or pass --project.")

    client = Client()
    print(f"Fetching runs from project '{args.project}'...")

    runs = []
    for run in client.list_runs(project_name=args.project):
        runs.append(
            {
                "id": str(run.id),
                "trace_id": str(run.trace_id),
                "parent_run_id": str(run.parent_run_id) if run.parent_run_id else None,
                "name": run.name,
                "run_type": run.run_type,
                "inputs": run.inputs,
                "outputs": run.outputs,
                "error": run.error,
                "extra": run.extra,
                "tags": run.tags,
                "start_time": run.start_time.isoformat() if run.start_time else None,
                "end_time": run.end_time.isoformat() if run.end_time else None,
            }
        )

    # Sort for stable output: by trace, then root-first, then start_time.
    runs.sort(key=lambda r: (r["trace_id"], r["parent_run_id"] is not None, r["start_time"] or ""))

    # Serialize first, then scrub any local absolute paths out of the whole
    # payload (error tracebacks, inputs, outputs, extra) in one pass.
    payload = scrub(json.dumps(runs, indent=2, default=serialize))
    with open(args.output, "w") as f:
        f.write(payload)

    n_traces = len({r["trace_id"] for r in runs})
    print(f"Saved {len(runs)} runs across {n_traces} traces to {args.output}")


if __name__ == "__main__":
    main()
