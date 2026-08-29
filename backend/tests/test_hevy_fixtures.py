"""The canned Hevy fixtures are load-bearing test data, so their shape is itself tested.

If a fixture drifts (a stray `rir`, an invented set `id`), every downstream Hevy test would
keep passing against a schema Hevy does not serve. Cheap insurance, fast suite.
"""

from typing import Any

from tests.conftest import hevy_fixture


def test_workout_pages_have_the_live_envelope() -> None:
    for name in ("workouts_page1", "workouts_page2"):
        payload = hevy_fixture(name)
        assert set(payload) == {"page", "page_count", "workouts"}


def test_sets_carry_rpe_and_weight_kg_but_no_rir_no_id() -> None:
    workout = hevy_fixture("workouts_page1")["workouts"][0]
    for exercise in workout["exercises"]:
        assert "id" not in exercise
        for s in exercise["sets"]:
            assert "id" not in s
            assert "rir" not in s
            assert "weight_unit" not in s
            assert set(s) == {
                "index",
                "type",
                "weight_kg",
                "reps",
                "distance_meters",
                "duration_seconds",
                "rpe",
                "custom_metric",
            }


def test_events_are_newest_first_and_use_both_variants() -> None:
    events: list[dict[str, Any]] = hevy_fixture("workout_events_page1")["events"]
    assert [e["type"] for e in events] == ["deleted", "updated"]
    assert events[0]["deleted_at"] > events[1]["workout"]["updated_at"]


def test_body_measurement_rows_have_no_id_and_17_metrics() -> None:
    rows = hevy_fixture("body_measurements_page1")["body_measurements"]
    assert all("id" not in row for row in rows)
    assert all(len(set(row) - {"date"}) == 17 for row in rows)


def test_template_page_includes_an_unmappable_custom_template() -> None:
    templates = hevy_fixture("exercise_templates_page1")["exercise_templates"]
    custom = [t for t in templates if t["is_custom"]]
    assert len(custom) == 1
    assert custom[0]["primary_muscle_group"] == "full_body"
