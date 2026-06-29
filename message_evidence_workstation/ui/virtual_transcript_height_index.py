"""Prefix-sum height index for virtual transcript scrolling."""

from __future__ import annotations


class FenwickTree:
    """Binary indexed tree for prefix sums over message heights."""

    def __init__(self, size: int) -> None:
        self._size = size
        self._tree = [0.0] * (size + 1)

    def add(self, index: int, delta: float) -> None:
        if index < 0 or index >= self._size:
            return
        position = index + 1
        while position <= self._size:
            self._tree[position] += delta
            position += position & -position

    def prefix_sum(self, end_exclusive: int) -> float:
        if end_exclusive <= 0:
            return 0.0
        end_exclusive = min(end_exclusive, self._size)
        total = 0.0
        position = end_exclusive
        while position > 0:
            total += self._tree[position]
            position -= position & -position
        return total

    def total(self) -> float:
        return self.prefix_sum(self._size)

    def find_last_prefix_le(self, target: float) -> int:
        """Return largest index i in [0, size) with prefix_sum(i) <= target."""
        if self._size <= 0:
            return 0
        if target < 0:
            return 0
        index = 0
        bitmask = 1 << (self._size.bit_length())
        accumulated = 0.0
        while bitmask:
            next_index = index + bitmask
            if next_index <= self._size and accumulated + self._tree[next_index] <= target:
                accumulated += self._tree[next_index]
                index = next_index
            bitmask >>= 1
        return min(index, self._size - 1)


class TranscriptHeightIndex:
    """Maps message ordinals to virtual document pixel offsets."""

    def __init__(self, message_count: int, *, default_height: float = 72.0) -> None:
        self._message_count = message_count
        self._default_height = default_height
        self._heights = [default_height] * message_count
        self._fenwick = FenwickTree(message_count)
        for ordinal in range(message_count):
            self._fenwick.add(ordinal, default_height)

    @property
    def message_count(self) -> int:
        return self._message_count

    @property
    def measured_count(self) -> int:
        return sum(1 for height in self._heights if height != self._default_height)

    def total_height(self) -> float:
        return self._fenwick.total()

    def height_at(self, ordinal: int) -> float:
        if ordinal < 0 or ordinal >= self._message_count:
            return 0.0
        return self._heights[ordinal]

    def set_height(self, ordinal: int, height: float) -> None:
        if ordinal < 0 or ordinal >= self._message_count:
            return
        height = max(1.0, height)
        delta = height - self._heights[ordinal]
        if delta == 0:
            return
        self._heights[ordinal] = height
        self._fenwick.add(ordinal, delta)

    def offset_for_ordinal(self, ordinal: int) -> float:
        if ordinal <= 0:
            return 0.0
        return self._fenwick.prefix_sum(min(ordinal, self._message_count))

    def ordinal_for_offset(self, offset: float) -> int:
        if self._message_count <= 0:
            return 0
        clamped = max(0.0, min(offset, max(0.0, self.total_height() - 1.0)))
        return self._fenwick.find_last_prefix_le(clamped)

    def invalidate_all(self, *, default_height: float | None = None) -> None:
        if default_height is not None:
            self._default_height = default_height
        self._heights = [self._default_height] * self._message_count
        self._fenwick = FenwickTree(self._message_count)
        for ordinal in range(self._message_count):
            self._fenwick.add(ordinal, self._default_height)
