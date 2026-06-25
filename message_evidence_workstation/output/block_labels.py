"""Display labels for ordered printable artifact evidence blocks."""


def block_label_for_index(index: int) -> str:
    """Return A, B, … Z, AA, AB, … for zero-based index."""
    if index < 0:
        raise ValueError("block index must be non-negative")
    label = ""
    value = index
    while True:
        label = chr(ord("A") + (value % 26)) + label
        value = value // 26 - 1
        if value < 0:
            break
    return label
