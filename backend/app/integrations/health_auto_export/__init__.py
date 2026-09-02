"""Health Auto Export ingest (HEALTH-06, HEALTH-07, NUTR-02).

Everything that knows Health Auto Export's wire format lives here and nowhere else. HAE units
are a per-metric **user preference inside the phone app**, and the app converts on-device at
export time -- so the units on the wire can change between one export and the next with no
version bump, no release note, and nothing to notice it by. That is the whole justification for
this boundary: when HAE changes, exactly one package changes.

Import submodules by full path
(``from app.integrations.health_auto_export.registry import METRIC_REGISTRY``).
This file deliberately re-exports nothing.

The boundary is ONE-DIRECTIONAL by design. This package MAY import ``app.db.models`` and
``app.core.time`` -- the provider-specific persistence decisions belong next to the
provider-specific wire format. Nothing outside it may import this package's ``schemas`` or
``registry``: those are HAE's identifiers, not BRETT's, and an analytics module keyed on them
would drift the moment HAE renames one. ``test_health_auto_export_isolation.py`` enforces both
directions.
"""
