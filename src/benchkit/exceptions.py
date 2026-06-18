"""Errors raised by the benchkit pytest-benchmark integration layer."""


class BenchkitError(Exception):
    """Base class for benchkit matrix, metadata, and result errors."""


class MetadataSerializationError(BenchkitError, ValueError):
    """Raised when benchmark metadata cannot be represented as strict JSON.

    Args:
        message: Explanation of the unsupported metadata value.
    """


class BenchmarkJsonError(BenchkitError, ValueError):
    """Raised when pytest-benchmark JSON cannot be parsed as benchkit output.

    Args:
        message: Explanation of the invalid or unsupported JSON structure.
    """
