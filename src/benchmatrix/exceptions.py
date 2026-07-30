"""Errors raised by the benchmatrix pytest-benchmark integration layer."""


class BenchmatrixError(Exception):
    """Base class for benchmatrix matrix, metadata, and result errors."""


class MetadataSerializationError(BenchmatrixError, ValueError):
    """Raised when benchmark metadata cannot be represented as strict JSON."""


class BenchmarkJsonError(BenchmatrixError, ValueError):
    """Raised when pytest-benchmark JSON cannot be parsed as benchmatrix output."""


class BenchmarkCollectionError(BenchmatrixError, RuntimeError):
    """Raised when a repeated-run collection cannot be created."""


class BenchmarkPolicyError(BenchmatrixError, ValueError):
    """Raised when benchmark policy configuration is invalid."""
