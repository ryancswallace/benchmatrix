"""Errors raised by the benchmatrix pytest-benchmark integration layer."""


class BenchmatrixError(Exception):
    """Base class for benchmatrix matrix, metadata, and result errors."""


class MetadataSerializationError(BenchmatrixError, ValueError):
    """Raised when benchmark metadata cannot be represented as strict JSON."""


class BenchmarkJsonError(BenchmatrixError, ValueError):
    """Raised when pytest-benchmark JSON cannot be parsed as benchmatrix output."""
