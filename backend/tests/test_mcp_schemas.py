"""The MCP response-model contract, asserted over the models themselves.

No container, no network, and deliberately NO integration marker -- these are the properties
`@safe_tool` depends on, and a violation must fail the FAST suite on the commit that introduces
it rather than at the first degraded tool call in production.

This module must never import `app.mcp.server`. `conftest.py` seeds the MCP environment at module
scope, and importing the server here would couple a container-free shape test to that seeding for
no gain -- `app.mcp.tools.schemas` imports nothing from the transport.

Every model is discovered by WALKING the module, never by a hand-maintained list: a thirteenth
tool's response model must be covered by these checks the moment it exists, without anyone
remembering to add it here. `test_the_walk_actually_finds_the_response_models` is the guard on
that guard.
"""

import re
import types
from pathlib import Path
from typing import Union, get_args, get_origin

import pytest
from pydantic import BaseModel

from app.mcp.tools import schemas
from app.mcp.tools.schemas import MuscleGroupRollup, _McpModel

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_SOURCE = REPO_ROOT / "backend" / "app" / "mcp" / "tools" / "schemas.py"

# Copied VERBATIM from `test_analytics_isolation.py:60`, comment included, because a second
# spelling of this rule is a second thing to keep in sync:
#
# C-2: `Decimal`, never `float`. Anchored on the CONSTRUCTOR and the ANNOTATION positions, never
# the bare word -- `estimates.py`, `schemas.py` and `rollup.py` all use the words "float" and
# "binary floating point" in prose explaining why they do not use one, and a substring check
# would fail on the sentence documenting the rule (the trap recorded at
# `test_hevy_isolation.py:88-93`). A leaked float is how `regr_slope`'s `double precision` or
# `statistics.linear_regression` would enter, and it turns an exact Decimal comparison into a
# test that needs `pytest.approx`.
_FLOAT_USE = re.compile(r"(?<![\w.])float\s*\(|:\s*float\b|->\s*float\b|\[\s*float\s*[],]")

# The two fields whose degraded value is NOT the type's zero. `plateaued_only` echoes the tool's
# default filter back, and the default is True -- a degraded payload claiming the caller asked for
# every exercise would misreport the request it is degrading.
_DEGRADED_OVERRIDES: dict[str, object] = {"plateaued_only": True}


def _response_models() -> list[type[_McpModel]]:
    """Every `*Response` model in `app/mcp/tools/schemas.py`.

    Filtered on `_McpModel` subclass AND a `Response` suffix so the nested projection models
    (`WorkoutSetDetail`, `MuscleGroupRollup`, ...) are excluded: they are components of a
    response, not one, and `data_available` belongs at the top level only.
    """
    found = [
        obj
        for _, obj in vars(schemas).items()
        if isinstance(obj, type)
        and issubclass(obj, _McpModel)
        and obj is not _McpModel
        and obj.__name__.endswith("Response")
    ]
    return sorted(found, key=lambda model: model.__name__)


def _allows_none(annotation: object) -> bool:
    """True for `X | None` and `Optional[X]`, both spellings.

    PEP 604 unions report `types.UnionType` as their origin and `typing.Optional` reports
    `typing.Union`; a check covering only one has a documented way around it.
    """
    return get_origin(annotation) in (Union, types.UnionType) and type(None) in get_args(annotation)


def _degraded_kwargs(model: type[_McpModel]) -> dict[str, object]:
    """The arguments `safe_tool` would pass when it could not reach the database.

    Derived from the annotations rather than hardcoded per model, so a new field on any response
    is covered without editing this file -- and an annotation this builder cannot handle raises
    rather than being silently skipped.
    """
    kwargs: dict[str, object] = {}
    for name, field in model.model_fields.items():
        if name == "data_available":
            kwargs[name] = False
        elif name in _DEGRADED_OVERRIDES:
            kwargs[name] = _DEGRADED_OVERRIDES[name]
        elif _allows_none(field.annotation):
            kwargs[name] = None
        elif get_origin(field.annotation) is list:
            kwargs[name] = []
        elif field.annotation is bool:
            kwargs[name] = False
        elif field.annotation is int:
            kwargs[name] = 0
        elif field.annotation is str:
            kwargs[name] = ""
        else:
            raise AssertionError(
                f"{model.__name__}.{name} has annotation {field.annotation!r}, which this builder "
                f"cannot degrade. A required field with no degraded value means `safe_tool` "
                f"cannot construct this response when the database is unreachable"
            )
    return kwargs


def test_the_walk_actually_finds_the_response_models() -> None:
    """A guard on the guards: an empty collection would make every test below vacuously true.

    If the module were moved or the `Response` suffix convention abandoned, `vars(schemas)`
    yields nothing matching and five contract tests pass while checking nothing at all.
    """
    models = _response_models()

    # Phase 6 registers thirteen tools, each with its own response model. The floor rises with
    # the module on purpose: a floor of 2 stays satisfied by a walk that has silently lost most
    # of what it was supposed to be checking.
    assert len(models) >= 12, (
        f"the walk found only {len(models)} `*Response` models in "
        f"{SCHEMAS_SOURCE.relative_to(REPO_ROOT)}"
    )


@pytest.mark.parametrize("model", _response_models(), ids=lambda m: m.__name__)
def test_every_response_model_is_frozen_and_forbids_extras(model: type[_McpModel]) -> None:
    """FOUND-05 / T-06-01: the ConfigDict is a security control, not a style choice.

    An output-model `ValidationError` is raised inside the SDK's `convert_result`, which runs
    OUTSIDE `safe_tool`'s reach -- nothing in this repo can catch it -- and its default message
    renders `input_value=...`, i.e. weekly tonnage and body-composition-adjacent numbers, into
    the tool-error text handed back to Claude. `hide_input_in_errors` is what stops that.
    """
    assert model.model_config["hide_input_in_errors"] is True, (
        f"FOUND-05/T-06-01 violated: {model.__name__} would render `input_value=...` into an SDK "
        f"ValidationError message that `safe_tool` cannot intercept"
    )
    assert model.model_config["extra"] == "forbid", (
        f"{model.__name__} must forbid extra fields: these are internal types, and an unexpected "
        f"field is a bug in this repo that should fail loudly rather than be dropped"
    )
    assert model.model_config["frozen"] is True, (
        f"{model.__name__} must be frozen: a response object a caller can mutate is a response "
        f"object two callers will disagree about"
    )


@pytest.mark.parametrize("model", _response_models(), ids=lambda m: m.__name__)
def test_every_response_model_declares_data_available(model: type[_McpModel]) -> None:
    """MCP-06 / `safe_tool`: a degraded payload must be distinguishable from a real empty result.

    Without this field, "the database was unreachable" and "you trained zero sets" serialize
    identically, and Claude narrates an outage as detraining -- a wrong answer with no signal.
    """
    assert "data_available" in model.model_fields, (
        f"MCP-06 violated: {model.__name__} has no `data_available`, so a degraded payload is "
        f"indistinguishable from a real empty result"
    )

    field = model.model_fields["data_available"]
    assert field.annotation is bool, (
        f"{model.__name__}.data_available must be a plain bool, not {field.annotation!r}"
    )
    assert field.is_required(), (
        f"{model.__name__}.data_available must be REQUIRED: a default would let a tool omit the "
        f"one field that says whether its answer is real"
    )


@pytest.mark.parametrize("model", _response_models(), ids=lambda m: m.__name__)
def test_every_response_model_has_a_constructible_degraded_form(model: type[_McpModel]) -> None:
    """T-06-01: `safe_tool`'s fallback must be able to build a VALID payload for every tool.

    A bare `except: pass` that returned an invalid payload would make `convert_result` raise a
    SECOND exception from inside the SDK -- and that one has no guard at all, so its message
    reaches Claude verbatim. The degraded form has to be constructible by construction, which is
    what this proves for every response model at once.
    """
    instance = model(**_degraded_kwargs(model))

    assert instance.model_dump()["data_available"] is False


def test_no_response_model_uses_float() -> None:
    """C-2: `Decimal`, never `float`, and asserted over the committed SOURCE.

    Binary floating point makes two arithmetically identical weekly totals compare unequal, which
    turns "did my tonnage change this week?" into a coin flip. Plan 06-09 extends this same regex
    to the whole of `app/mcp/`; this is the module-scoped version that ships with the module.
    """
    source = SCHEMAS_SOURCE.read_text(encoding="utf-8")

    assert not _FLOAT_USE.search(source), (
        f"C-2 violated: {SCHEMAS_SOURCE.relative_to(REPO_ROOT)} uses `float`. Every magnitude in "
        f"an MCP response is a `Decimal | None`"
    )


def test_muscle_rollup_reshape_is_documented() -> None:
    """CONTEXT.md's "compose these, do not reshape them" rule is broken exactly once in Phase 6.

    The rule about breaking it is that it must be visible AT THE SITE that breaks it -- a reader
    of `MuscleGroupRollup` must not have to find a planning document to learn that this model is
    not a verbatim analytics result.
    """
    doc = MuscleGroupRollup.__doc__ or ""

    assert "DELIBERATE RESHAPE" in doc, (
        "MuscleGroupRollup is the one model in this phase that reshapes an analytics result "
        "rather than composing it; its docstring must say so"
    )


def test_response_models_are_pydantic_models() -> None:
    """Belt and braces on the walk: `_McpModel` must stay a `BaseModel` subclass.

    Returning a `BaseModel` is what auto-populates `outputSchema` and `structured_content`
    (`app/mcp/tools/ping.py:24-28`). If `_McpModel` ever stopped being one, every tool would
    silently lose its published output schema.
    """
    assert issubclass(_McpModel, BaseModel)
    assert all(issubclass(model, BaseModel) for model in _response_models())
