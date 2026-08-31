"""Deterministic training and body-composition analytics.

Requirements: VOL-01..03, PROG-01..04, CMP-01, BODY-01, BODY-02, DQ-01, DQ-02.

A sibling of ``app/normalization/`` and ``app/core/``, not a layer above them. Nothing here
may import from ``app.integrations`` (HEVY-05: a second provider must feed the same tables)
and nothing here may import from ``app.mcp``. The Phase 6 arrow runs one way only -- MCP tools
call these functions; these functions know nothing about MCP, transports, tokens or tools.
Reversing it would put a wire contract inside the arithmetic and make the arithmetic
untestable without a transport.

This package also never reaches ``exercise_muscles`` or ``exercise_muscle_overrides``
directly. Muscle resolution goes through ``app.normalization.resolver.effective_muscles_bulk``,
because the rule is REPLACEMENT (any override replaces the base set entirely), not merge, and
a join expresses merge. A direct join produces byte-identical numbers today only because the
override table has zero rows; it starts lying the first time a user corrects a mapping.
``backend/tests/test_analytics_isolation.py`` enforces both boundaries statically.

Read-only by construction: no function in this package commits, flushes, inserts, updates or
deletes. The caller owns the transaction (the ``app/db/repositories/`` convention).
"""
