"""Domain exceptions used by NetState Reconciler."""


class NetStateError(Exception):
    """Base exception for expected application errors."""


class DesiredStateError(NetStateError):
    """Raised when a desired-state YAML document is invalid."""


class CollectionError(NetStateError):
    """Raised when configuration collection fails."""


class UnsafeRemediationError(NetStateError):
    """Raised when an operation is not safe to perform automatically."""
