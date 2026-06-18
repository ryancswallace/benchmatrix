"""Errors raised by the benchmatrix pytest-benchmark integration layer."""


class BenchmatrixError(Exception):
    """Base class for benchmatrix matrix, metadata, and result errors."""


class MetadataSerializationError(BenchmatrixError, ValueError):
    """Raised when benchmark metadata cannot be represented as strict JSON.

    Args:
        message: Explanation of the unsupported metadata value.
    """


class BenchmarkJsonError(BenchmatrixError, ValueError):
    """Raised when pytest-benchmark JSON cannot be parsed as benchmatrix output.

    Args:
        message: Explanation of the invalid or unsupported JSON structure.
    """
