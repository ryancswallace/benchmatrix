"""Deterministic execution schedules for benchmark collection."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from ._schema import KNOWN_METRICS, MetricName

ORDER_SEED_ENV = "BENCHMATRIX_ORDER_SEED"
ORDER_INDEX_ENV = "BENCHMATRIX_ORDER_INDEX"


def balanced_order_indices(
    keys: Sequence[tuple[str, str, str]],
    *,
    order_index: int,
    random_seed: int,
) -> tuple[int, ...]:
    """Return one row of a deterministic Williams-style ordering design."""
    _validate_schedule_inputs(len(keys), order_index=order_index, random_seed=random_seed)
    if not keys:
        return ()
    if len(set(keys)) != len(keys):
        raise ValueError("Balanced-order keys must not contain duplicates.")

    labels = sorted(
        range(len(keys)),
        key=lambda index: (_key_digest(keys[index], random_seed=random_seed), keys[index]),
    )
    count = len(labels)
    if count == 1:
        return (labels[0],)

    # The first Williams row is 0, 1, n-1, 2, n-2, ... . Cyclic shifts
    # balance ordinal position. For odd n, appending the reversed rows balances
    # directed first-order carryover as well.
    template: list[int] = [0]
    low = 1
    high = count - 1
    while low <= high:
        template.append(low)
        low += 1
        if low <= high:
            template.append(high)
            high -= 1

    zero_based_row = order_index - 1
    rotation = zero_based_row % count
    row = [labels[(position + rotation) % count] for position in template]
    if count % 2 == 1 and (zero_based_row // count) % 2 == 1:
        row.reverse()
    return tuple(row)


def balanced_cell_order(
    cells: Sequence[tuple[str, str, MetricName]],
    *,
    order_index: int,
    random_seed: int = 0,
) -> tuple[tuple[str, str, MetricName], ...]:
    """Return one deterministic position- and carryover-balanced cell order.

    Even-sized matrices repeat after ``n`` order indexes. Odd-sized matrices
    larger than one repeat after ``2n`` indexes because every cyclic row is
    followed by a reversed cycle. A one-cell matrix has a one-row cycle.

    Args:
        cells: Unique ``(implementation, case, metric)`` matrix cells.
        order_index: One-based schedule row.
        random_seed: Non-negative seed for the stable base-label permutation.

    Returns:
        The cells in the scheduled execution order.

    Raises:
        TypeError: If an index or seed is not an integer.
        ValueError: If an index, seed, or cell is invalid, or cells repeat.
    """
    frozen = tuple(cells)
    for cell in frozen:
        if (
            not isinstance(cell, tuple)
            or len(cell) != 3
            or not all(isinstance(value, str) and value for value in cell)
            or cell[2] not in KNOWN_METRICS
        ):
            raise ValueError(f"Invalid benchmark matrix cell: {cell!r}.")
    indices = balanced_order_indices(
        [(implementation, case, metric) for implementation, case, metric in frozen],
        order_index=order_index,
        random_seed=random_seed,
    )
    return tuple(frozen[index] for index in indices)


def balanced_order_cycle_length(cell_count: int) -> int:
    """Return the number of rows in a complete balanced-order cycle."""
    if isinstance(cell_count, bool) or not isinstance(cell_count, int):
        raise TypeError("cell_count must be an integer.")
    if cell_count < 0:
        raise ValueError("cell_count must be non-negative.")
    if cell_count <= 1 or cell_count % 2 == 0:
        return cell_count
    return cell_count * 2


def balanced_order_supercycle_length(cell_count: int) -> int:
    """Return the AB/BA-by-balanced-row joint-design cycle length."""
    return 2 * balanced_order_cycle_length(cell_count)


def _validate_schedule_inputs(cell_count: int, *, order_index: int, random_seed: int) -> None:
    """Validate common balanced-order inputs."""
    if isinstance(order_index, bool) or not isinstance(order_index, int):
        raise TypeError("order_index must be an integer.")
    if order_index <= 0:
        raise ValueError("order_index must be positive.")
    if isinstance(random_seed, bool) or not isinstance(random_seed, int):
        raise TypeError("random_seed must be an integer.")
    if random_seed < 0:
        raise ValueError("random_seed must be non-negative.")


def _key_digest(key: tuple[str, str, str], *, random_seed: int) -> bytes:
    """Return a stable seeded digest for one cell key."""
    payload = "\0".join((str(random_seed), *key)).encode()
    return hashlib.sha256(payload).digest()
