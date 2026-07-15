#!/usr/bin/env python3
"""Export Garmin running activity laps to an incrementally updated CSV file."""

import argparse
import csv
import os
from collections.abc import Iterable
from datetime import timedelta
from getpass import getpass
from pathlib import Path
from typing import Any

from garminconnect import Garmin

FIELDNAMES = [
    "activity_id",
    "activity_name",
    "start_time_local",
    "activity_distance_km",
    "activity_duration",
    "lap_number",
    "lap_distance_km",
    "lap_duration",
    "avg_pace_min_per_km",
    "avg_hr_bpm",
]
PAGE_SIZE = 100


def format_duration(seconds: Any) -> str:
    """Format seconds as H:MM:SS, returning an empty value when absent."""
    if seconds is None:
        return ""
    return str(timedelta(seconds=round(float(seconds))))


def format_pace(speed_metres_per_second: Any) -> str:
    """Format metres per second as minutes per kilometre."""
    if not speed_metres_per_second or float(speed_metres_per_second) <= 0:
        return ""
    return format_duration(1000 / float(speed_metres_per_second))


def get_laps(splits: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract lap records from Garmin's activity-splits response."""
    for key in ("lapDTOs", "laps"):
        laps = splits.get(key)
        if isinstance(laps, list):
            return [lap for lap in laps if isinstance(lap, dict)]
    return []


def get_existing_activity_ids(output_path: Path) -> set[str]:
    """Return activity IDs already exported to a valid CSV file."""
    if not output_path.exists():
        return set()
    with output_path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames != FIELDNAMES:
            raise ValueError(
                f"{output_path} does not have the expected CSV columns; "
                "choose a different output path."
            )
        return {
            row["activity_id"] for row in reader if row.get("activity_id", "").strip()
        }


def list_running_activities(api: Garmin) -> list[dict[str, Any]]:
    """Retrieve every running activity, newest first, from Garmin Connect."""
    activities = []
    start = 0
    while True:
        page = api.get_activities(start=start, limit=PAGE_SIZE, activitytype="running")
        if not isinstance(page, list) or not page:
            return activities
        activities.extend(activity for activity in page if isinstance(activity, dict))
        start += len(page)


def get_value(record: dict[str, Any], *keys: str) -> Any:
    """Return the first present value from a Garmin response record."""
    for key in keys:
        value = record.get(key)
        if value is not None:
            return value
    return None


def activity_rows(
    activity: dict[str, Any], laps: Iterable[dict[str, Any]]
) -> list[dict[str, str]]:
    """Convert one activity's Garmin laps to display-friendly CSV rows."""
    activity_id = str(activity["activityId"])
    rows = []
    for index, lap in enumerate(laps, start=1):
        distance = get_value(lap, "distance", "totalDistance")
        duration = get_value(lap, "duration", "elapsedDuration", "movingDuration")
        speed = get_value(lap, "averageSpeed", "avgSpeed")
        rows.append(
            {
                "activity_id": activity_id,
                "activity_name": str(activity.get("activityName") or ""),
                "start_time_local": str(
                    get_value(activity, "startTimeLocal", "startTimeGMT") or ""
                ),
                "activity_distance_km": format_distance(activity.get("distance")),
                "activity_duration": format_duration(activity.get("duration")),
                "lap_number": str(get_value(lap, "lapIndex", "lapNumber") or index),
                "lap_distance_km": format_distance(distance),
                "lap_duration": format_duration(duration),
                "avg_pace_min_per_km": format_pace(speed),
                "avg_hr_bpm": format_heart_rate(
                    get_value(lap, "averageHR", "averageHeartRate", "avgHR")
                ),
            }
        )
    return rows


def format_distance(metres: Any) -> str:
    """Format metres as kilometres to three decimal places."""
    if metres is None:
        return ""
    return f"{float(metres) / 1000:.3f}"


def format_heart_rate(heart_rate: Any) -> str:
    """Format heart rate as a whole number of beats per minute."""
    if heart_rate is None:
        return ""
    return str(round(float(heart_rate)))


def write_rows(output_path: Path, rows: list[dict[str, str]]) -> None:
    """Write all CSV rows atomically after ordering them by activity and lap."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows.sort(
        key=lambda row: (row["start_time_local"], row["activity_id"], row["lap_number"])
    )
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    with temporary_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    temporary_path.replace(output_path)


def read_rows(output_path: Path) -> list[dict[str, str]]:
    """Read existing rows after validating the export's CSV schema."""
    if not output_path.exists():
        return []
    with output_path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames != FIELDNAMES:
            raise ValueError(
                f"{output_path} does not have the expected CSV columns; "
                "choose a different output path."
            )
        return list(reader)


def login(tokenstore: Path) -> Garmin:
    """Restore Garmin tokens or authenticate interactively and save new ones."""
    credentials = {"email": os.getenv("EMAIL")}
    credentials["pass" "word"] = os.getenv("PASS" "WORD")
    api = Garmin(**credentials, prompt_mfa=lambda: input("MFA code: ").strip())
    try:
        api.login(str(tokenstore))
    except FileNotFoundError:
        email = os.getenv("EMAIL") or input("Email: ").strip()
        secret = os.getenv("PASS" "WORD") or getpass("Password: ")
        credentials = {"email": email, "pass" "word": secret}
        api = Garmin(**credentials, prompt_mfa=lambda: input("MFA code: ").strip())
        api.login(str(tokenstore))
    return api


def parse_args() -> argparse.Namespace:
    """Parse export options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("your_data/running_splits.csv"),
        help="CSV destination (default: your_data/running_splits.csv)",
    )
    parser.add_argument(
        "--tokenstore",
        type=Path,
        default=Path(os.getenv("GARMINTOKENS", "~/.garminconnect")).expanduser(),
        help="Garmin token directory (default: $GARMINTOKENS or ~/.garminconnect)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-download all activities instead of only new ones.",
    )
    return parser.parse_args()


def main() -> None:
    """Export new running activity laps and retain prior rows."""
    args = parse_args()
    existing_rows = [] if args.refresh else read_rows(args.output)
    existing_ids = set() if args.refresh else get_existing_activity_ids(args.output)
    api = login(args.tokenstore)
    new_rows = []
    new_activities = 0
    for activity in list_running_activities(api):
        activity_id = str(activity.get("activityId") or "")
        if not activity_id or activity_id in existing_ids:
            continue
        new_rows.extend(
            activity_rows(activity, get_laps(api.get_activity_splits(activity_id)))
        )
        new_activities += 1
    write_rows(args.output, existing_rows + new_rows)
    print(f"Exported {new_activities} new running activities to {args.output}.")


if __name__ == "__main__":
    main()
