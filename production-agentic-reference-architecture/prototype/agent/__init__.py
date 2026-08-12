"""Deep-research agent — orchestration spike for the reference architecture.

Public surface used by the CLI (`run.py`) and the eval harness (`eval/harness.py`):

    from agent import Orchestrator, RunConfig, RunResult
"""

from .orchestrator import Orchestrator, RunConfig, RunResult  # noqa: F401
from .tools import TOOL_REGISTRY_SPEC, TOOLS  # noqa: F401
from .tracing import Tracer, load_trace  # noqa: F401

__all__ = [
    "Orchestrator",
    "RunConfig",
    "RunResult",
    "TOOLS",
    "TOOL_REGISTRY_SPEC",
    "Tracer",
    "load_trace",
]
__version__ = "0.1.0"
