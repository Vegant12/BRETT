"""MCP server assembly (MCP-01, MCP-04, D-05).

Import order here is load-bearing in the same way ``main.py``'s is.
``streamable_http_app()`` MUST run at import: ``mcp.session_manager`` raises
``RuntimeError`` until it has, and ``main.py``'s lifespan reads that attribute.

Three non-obvious constraints, each verified against mcp 2.0.0:

* ``AuthSettings`` is mandatory alongside ``token_verifier``. Passing a verifier
  without it raises ``ValueError`` at import, and ``AuthSettings`` itself requires
  BOTH ``issuer_url`` and ``resource_server_url`` (RESEARCH Pitfall 4). During
  the static-bearer stage ``issuer_url`` is never exercised -- a valid header
  means no 401, so no discovery -- but it must still be a valid URL.
* ``TransportSecuritySettings`` is not optional in practice. Left at ``None`` the
  SDK auto-enables DNS-rebinding protection allowing only localhost, and every
  request through Render's real Host header returns ``421 Invalid Host header``
  with no MCP-level error body (T-02-01, RESEARCH Pitfall 2).
* ``allowed_origins=[]`` on purpose. Claude's connectors call server-to-server
  from Anthropic's egress range and send no ``Origin``; a non-empty list here
  creates a 403 trap for no benefit.

The sub-app returned below owns ``/mcp`` AND
``/.well-known/oauth-protected-resource/mcp`` at its OWN root, so ``main.py``
mounts it at ``/``. Mounting at ``/mcp`` relocates the metadata document to a
path Claude never probes and breaks OAuth discovery silently -- the MCP server
receives the first request while the authorization server sees no traffic at all
(RESEARCH Pitfall 3).
"""

from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from app.config import get_settings
from app.mcp.auth import build_token_verifier
from app.mcp.context import mcp_lifespan
from app.mcp.tools.body import (
    fitness_get_body_weight_trend,
    fitness_get_recomposition_status,
)
from app.mcp.tools.comparison import fitness_compare_periods
from app.mcp.tools.ping import fitness_ping
from app.mcp.tools.progression import (
    fitness_get_exercise_progression,
    fitness_get_plateaus,
)
from app.mcp.tools.records import fitness_get_personal_records
from app.mcp.tools.summary import fitness_get_training_summary
from app.mcp.tools.volume import (
    fitness_get_muscle_group_volume,
    fitness_get_training_frequency,
    fitness_get_weekly_volume,
)
from app.mcp.tools.workouts import fitness_get_recent_workouts, fitness_get_workout

settings = get_settings()  # lru_cached -- not a second read

mcp = MCPServer(
    name="BRETT",
    version="0.1.0",
    lifespan=mcp_lifespan,
    token_verifier=build_token_verifier(settings),
    auth=AuthSettings(
        # `str` is passed deliberately, and the `type: ignore` is the price of
        # doing it correctly. These fields are typed `AnyHttpUrl`, but
        # `AuthSettings` sets `url_preserve_empty_path=True` specifically so a
        # path-less URL passed AS A STRING keeps its canonical form. Coercing
        # with `AnyHttpUrl(...)` here to satisfy mypy would bypass that config
        # and rewrite "https://tenant.authkit.app" to ".../" -- and RFC 8414
        # issuer comparison is exact string comparison, so that trailing slash
        # silently breaks discovery against the real IdP.
        issuer_url=settings.mcp_issuer_url,  # type: ignore[arg-type]
        # Must equal the URL the user types into Claude, character for
        # character, and the Resource Indicator registered at the IdP
        # (RESEARCH Pitfall 8).
        resource_server_url=settings.mcp_resource_url,  # type: ignore[arg-type]
        # Scope design WAS considered in Phase 6, against the real tool set, and
        # `None` is the decision rather than the leftover default (T-06-16).
        # Every registered tool is read-only -- `READ_ONLY` below, and the
        # PostgreSQL READ ONLY transaction `_common.read_only_session` opens --
        # so there is no privileged operation to gate. Adding a required scope
        # would mean re-consenting the Phase 2 connector that already works, and
        # would buy no security: a scope the server never varies its behaviour
        # on is a claim, not a control. Revisit when the first write tool ships.
        required_scopes=None,
    ),
)

# MCP-05. ONE annotation object reused by every tool: a per-tool literal is
# thirteen chances to forget a flag. The SPEC defaults for `destructive_hint` and
# `open_world_hint` are `true`, so LEAVING THEM UNSET advertises a destructive,
# open-world tool -- they are set explicitly here, not omitted.
#
# The annotation is a HINT. The SDK's own docs say annotations "should not be
# relied upon for security enforcement", which is why
# `_common.read_only_session` opens a PostgreSQL READ ONLY transaction as the
# actual control, and why `test_mcp_readonly.py` drives a write through a tool
# session rather than trusting this object.
READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

# D-08: `fitness_ping` is the Phase 2 canary and stays first-class -- it does a
# real DB round-trip, so it is still the cheapest proof that the lifespan-wired
# session factory reached the tool layer.
mcp.add_tool(
    fitness_ping,
    name="fitness_ping",
    description="Database connectivity check.",
    annotations=READ_ONLY,
)

# A loop rather than twelve literal `add_tool` calls, so "every tool is annotated
# read-only" is STRUCTURALLY true instead of twelve chances to omit
# `annotations=`. `test_mcp_tool_schemas.py` still asserts it, because the loop
# guarantees it today and the test guarantees it after someone adds a thirteenth
# tool by hand.
#
# `_fn.__name__` is the registration name, which is why `_common.safe_tool` MUST
# use `functools.wraps` -- without it every decorated tool would register as
# "wrapper" and Claude would see twelve identically-named tools.
# `Callable[..., Any]` and not `object`: it is `add_tool`'s own parameter type,
# and it is what makes `_fn.__name__` below type-check. An `object` element type
# would need a cast or an ignore at the one line whose whole job is to read the
# function's name.
_TOOLS: tuple[tuple[Callable[..., Any], str], ...] = (
    (
        fitness_get_recent_workouts,
        "Most recent workouts as compact summaries (no per-set detail).",
    ),
    (
        fitness_get_workout,
        "Full exercise and set breakdown for one workout, by the id "
        "fitness_get_recent_workouts returns.",
    ),
    (
        fitness_get_training_summary,
        "Composed training picture in one call: weekly volume, per-muscle work and "
        "frequency, progression verdict and recomposition status.",
    ),
    (
        fitness_get_weekly_volume,
        "Weekly hard sets, reps and tonnage for the last N weeks.",
    ),
    (
        fitness_get_muscle_group_volume,
        "Per-muscle-group direct and indirect set volume over the last N weeks, "
        "all 19 groups.",
    ),
    (
        fitness_get_training_frequency,
        "Sessions per week overall, per muscle group and per exercise.",
    ),
    (
        fitness_get_exercise_progression,
        "One exercise's weight, reps and estimated-1RM time series, by exercise name.",
    ),
    (
        fitness_get_personal_records,
        "One exercise's personal records with the date each was reached, by exercise name.",
    ),
    (
        fitness_get_plateaus,
        "Exercises that have stopped progressing, with the window and threshold used.",
    ),
    (
        fitness_compare_periods,
        "Two explicit date periods compared, every figure normalized per week.",
    ),
    (
        fitness_get_body_weight_trend,
        "7/14/30-day rolling body-weight averages and the smoothed weekly rate of change.",
    ),
    (
        fitness_get_recomposition_status,
        "Recomposition verdict from the body-weight trend and training progression, "
        "with its disclaimer.",
    ),
)

for _fn, _description in _TOOLS:
    mcp.add_tool(_fn, name=_fn.__name__, description=_description, annotations=READ_ONLY)

# MUST run at import time. See the module docstring.
mcp_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    # No session state to lose across a Render restart or spin-down; the
    # 2026-07-28 transport removed protocol-level sessions anyway.
    stateless_http=True,
    transport_security=TransportSecuritySettings(
        allowed_hosts=settings.mcp_allowed_hosts,
        allowed_origins=[],
    ),
)
