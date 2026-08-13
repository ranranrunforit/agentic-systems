"""Host error taxonomy. Every failure is attributable to a layer."""


class HostError(Exception):
    """Base class for all host errors."""

    layer = "host"


class ContractError(HostError):
    """Manifest violates the ext/v1 contract."""

    layer = "contract"


class RegistryError(HostError):
    """Load / approval / revocation problem."""

    layer = "registry"


class PermissionExpansionError(RegistryError):
    """An upgrade requests permissions beyond the approved grant."""

    layer = "governance"


class RevokedError(RegistryError):
    """The extension was killed by the kill-switch."""

    layer = "governance"


class AuthorizationDenied(HostError):
    """The authorization gate denied a proposed action."""

    layer = "gate"

    def __init__(self, message: str, *, reason: str = "policy_denied", decision=None):
        super().__init__(message)
        self.reason = reason
        self.decision = decision


class ConfirmationRequired(AuthorizationDenied):
    """A high-impact action needs human confirmation that was not supplied."""

    layer = "gate"

    def __init__(self, message: str, *, decision=None):
        super().__init__(message, reason="confirmation_required", decision=decision)


class TokenError(HostError):
    """Token minting / validation / revocation failure."""

    layer = "broker"


class EgressDenied(HostError):
    """The egress proxy refused a destination or an unscoped call."""

    layer = "egress"


class SandboxError(HostError):
    """Extension crashed, timed out, or attempted a blocked syscall/import."""

    layer = "sandbox"
