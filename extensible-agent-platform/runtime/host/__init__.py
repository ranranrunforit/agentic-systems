"""Reference host for the ext/v1 extension contract.

The host is the trusted core. Extensions are untrusted by construction: they
declare capabilities and permissions, they run isolated, they reach the outside
world only through the brokered egress proxy, and every privileged action they
propose crosses the authorization gate before it happens.

Nothing in this package is host-vendor specific. `portability/` shows the same
contract driven by a second host binding.
"""

from .audit import AuditLog
from .contract import Extension, Permission, diff_permissions, load_manifest, parse
from .errors import (
    AuthorizationDenied,
    ConfirmationRequired,
    ContractError,
    EgressDenied,
    HostError,
    PermissionExpansionError,
    RegistryError,
    RevokedError,
    SandboxError,
    TokenError,
)
from .gate import (
    AlwaysApproveConfirmation,
    AutoDenyConfirmation,
    CliConfirmation,
    Gate,
    Intent,
    ScriptedConfirmation,
)
from .host import Host, InvocationResult, ProposalOutcome
from .policy import Decision, PolicyEngine, Request
from .registry import Grant, Registry
from .taint import TaintSet, wrap_untrusted

__all__ = [
    "AuditLog",
    "AlwaysApproveConfirmation",
    "AuthorizationDenied",
    "AutoDenyConfirmation",
    "CliConfirmation",
    "ConfirmationRequired",
    "ContractError",
    "Decision",
    "EgressDenied",
    "Extension",
    "Gate",
    "Grant",
    "Host",
    "HostError",
    "Intent",
    "InvocationResult",
    "Permission",
    "PermissionExpansionError",
    "PolicyEngine",
    "ProposalOutcome",
    "Registry",
    "RegistryError",
    "Request",
    "RevokedError",
    "SandboxError",
    "ScriptedConfirmation",
    "TaintSet",
    "TokenError",
    "diff_permissions",
    "load_manifest",
    "parse",
    "wrap_untrusted",
]
