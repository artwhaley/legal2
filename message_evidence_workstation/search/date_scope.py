"""Shared date-scope contract for message filtering.

Every search path that needs timestamp-based filtering must use this single
contract.  Callers should never hand-roll ad-hoc date SQL strings.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MessageDateScope:
    """Optional inclusive start/end bounds for message timestamp filtering.

    An empty scope (both bounds ``None``) means unfiltered behaviour.
    Bounds are inclusive: ``timestamp >= start`` and ``timestamp <= end``.
    """

    start_timestamp: str | None = None
    end_timestamp: str | None = None

    @property
    def is_active(self) -> bool:
        """Return ``True`` when at least one bound is set.

        An empty string bound is treated as unset (the UI normalizes blank
        date controls before constructing a scope).
        """
        return bool(self.start_timestamp or self.end_timestamp)


def date_scope_sql_clauses(scope: MessageDateScope | None) -> tuple[str, tuple]:
    """Return ``(clause_sql, params)`` suitable for appending to a WHERE clause.

    When *scope* is ``None`` or inactive the returned clause is the empty
    string and *params* is an empty tuple.

    Callers must inject via string interpolation:

        clause, extra_params = date_scope_sql_clauses(date_scope)
        if clause:
            sql += f" AND {clause}"
            all_params += extra_params

    The returned clause uses positioned ``?`` placeholders (not named
    bindings) so ordering relative to the rest of the query matters.
    """
    if scope is None or not scope.is_active:
        return "", ()

    clauses: list[str] = []
    params: list[str] = []

    if scope.start_timestamp is not None:
        clauses.append("timestamp >= ?")
        params.append(scope.start_timestamp)
    if scope.end_timestamp is not None:
        clauses.append("timestamp <= ?")
        params.append(scope.end_timestamp)

    return " AND ".join(clauses), tuple(params)
