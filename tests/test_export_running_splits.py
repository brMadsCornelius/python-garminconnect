"""Tests for the incremental running split CSV exporter."""

import csv
from pathlib import Path

from export_running_splits import (
    FIELDNAMES,
    activity_rows,
    format_duration,
    format_pace,
    get_existing_activity_ids,
    get_laps,
    write_rows,
)


def test_formats_duration_and_pace() -> None:
    """Display durations and pace in readable clock notation."""
    assert format_duration(65.4) == "0:01:05"
    assert format_duration(None) == ""
    assert format_pace(3.333333333) == "0:05:00"
    assert format_pace(0) == ""


def test_activity_rows_uses_lap_metrics() -> None:
    """Map Garmin's activity and lap fields into the public CSV schema."""
    activity = {
        "activityId": 123,
        "activityName": "Morning Run",
        "startTimeLocal": "2026-07-15 06:00:00",
        "distance": 5000,
        "duration": 1500,
    }
    rows = activity_rows(
        activity,
        [
            {
                "lapIndex": 1,
                "distance": 1000,
                "duration": 300,
                "averageSpeed": 3.333333333,
                "averageHR": 152.4,
            }
        ],
    )

    assert rows == [
        {
            "activity_id": "123",
            "activity_name": "Morning Run",
            "start_time_local": "2026-07-15 06:00:00",
            "activity_distance_km": "5.000",
            "activity_duration": "0:25:00",
            "lap_number": "1",
            "lap_distance_km": "1.000",
            "lap_duration": "0:05:00",
            "avg_pace_min_per_km": "0:05:00",
            "avg_hr_bpm": "152",
        }
    ]


def test_get_laps_accepts_garmin_lap_dtos() -> None:
    """Read standard split responses and reject non-dictionary lap records."""
    assert get_laps({"lapDTOs": [{"distance": 1000}, "invalid"]}) == [
        {"distance": 1000}
    ]


def test_get_laps_prefers_distance_splits() -> None:
    """Use kilometer split metrics instead of the full activity lap metrics."""
    assert get_laps(
        {
            "lapDTOs": [{"distance": 5000, "averageHR": 150}],
            "splitDTOs": [{"distance": 1000, "averageHR": 152, "averageSpeed": 3.5}],
        }
    ) == [{"distance": 1000, "averageHR": 152, "averageSpeed": 3.5}]


def test_existing_ids_and_write_rows_support_incremental_updates(
    tmp_path: Path,
) -> None:
    """Keep prior activity rows while writing a stable, valid CSV."""
    output_path = tmp_path / "running_splits.csv"
    rows = [
        dict(zip(FIELDNAMES, ["2", "", "2026-02-01", "", "", "1", "", "", "", ""])),
        dict(zip(FIELDNAMES, ["1", "", "2026-01-01", "", "", "1", "", "", "", ""])),
    ]

    write_rows(output_path, rows)

    assert get_existing_activity_ids(output_path) == {"1", "2"}
    with output_path.open(newline="", encoding="utf-8") as csv_file:
        written_rows = list(csv.DictReader(csv_file))
    assert [row["activity_id"] for row in written_rows] == ["1", "2"]
