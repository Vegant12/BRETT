"""Provider-neutral exercise normalization.

This package deliberately sits OUTSIDE ``app/integrations/hevy/``. HEVY-05 confines Hevy's
request/response code to that directory; the canonical muscle taxonomy is not Hevy's -- it is
the project's, and a second provider must be able to feed the same tables. Nothing here may
import from ``app.integrations``.
"""
