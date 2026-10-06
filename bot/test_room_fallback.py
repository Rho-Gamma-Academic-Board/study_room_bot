#!/usr/bin/env python3
"""Unit tests for multi-room fallback + library-hours end picking (no LibCal)."""

import _bootstrap  # noqa: F401

from study_room_bot import (
    assign_windows_from_support,
    format_window_label,
    ordered_cap10_rooms,
    pick_end_within_library_hours,
)

W12 = ("12:00pm", "12:00", "16:00", "12:00pm–4:00pm")
W4 = ("4:00pm", "16:00", "20:00", "4:00pm–8:00pm")
W8 = ("8:00pm", "20:00", "22:00", "8:00pm–10:00pm")
WINDOWS = [W12, W4, W8]


def test_full_day_single_room():
    rooms = ["360F", "370A"]
    support = {"360F": list(WINDOWS), "370A": list(WINDOWS)}
    plan = assign_windows_from_support(WINDOWS, rooms, support)
    assert plan == [("360F", W12), ("360F", W4), ("360F", W8)]


def test_partial_preferred_falls_back():
    """Preferred room only has noon; evening goes to another large room."""
    rooms = ["360F", "360H", "370A", "370B"]
    support = {
        "360F": [W12, None, None],
        "360H": [None, None, None],
        "370A": [None, W4, W8],
        "370B": [None, W4, None],
    }
    plan = assign_windows_from_support(WINDOWS, rooms, support)
    assert plan == [("360F", W12), ("370A", W4), ("370A", W8)]


def test_target_room_ordered_first():
    import os

    os.environ["TARGET_ROOM"] = "360F"
    try:
        ordered = ordered_cap10_rooms(["370A", "360H", "360F", "172"])
        assert ordered[0] == "360F"
        assert "360H" in ordered
    finally:
        del os.environ["TARGET_ROOM"]


def test_uncovered_window_skipped():
    rooms = ["360F", "370A"]
    support = {"360F": [W12, None, None], "370A": [None, W4, None]}
    plan = assign_windows_from_support(WINDOWS, rooms, support)
    assert plan == [("360F", W12), ("370A", W4)]


def test_library_hours_shorten_afternoon():
    """Friday-style: ideal 4–8, dropdown only offers through 7pm."""
    ends = ["16:30", "17:00", "17:30", "18:00", "18:30", "19:00"]
    assert pick_end_within_library_hours(ends, "16:00", "20:00") == "19:00"
    assert format_window_label("16:00", "19:00") == "4:00pm–7:00pm"


def test_library_hours_prefer_ideal_when_offered():
    ends = ["16:30", "17:00", "17:30", "18:00", "18:30", "19:00", "20:00"]
    assert pick_end_within_library_hours(ends, "16:00", "20:00") == "20:00"


def test_library_hours_user_reported_4_to_6():
    """If library/availability only goes to 6pm, book 4–6."""
    ends = ["16:30", "17:00", "17:30", "18:00"]
    assert pick_end_within_library_hours(ends, "16:00", "20:00") == "18:00"
    assert format_window_label("16:00", "18:00") == "4:00pm–6:00pm"


def test_library_hours_reject_too_short():
    ends = ["16:30"]
    assert pick_end_within_library_hours(ends, "16:00", "20:00") is None


def test_adjusted_afternoon_on_preferred_room():
    """360F afternoon shortened by library hours still counts as coverage."""
    w4_short = ("4:00pm", "16:00", "18:00", "4:00pm–6:00pm")
    rooms = ["360F", "370A"]
    support = {
        "360F": [W12, w4_short, None],
        "370A": [None, None, None],
    }
    plan = assign_windows_from_support(WINDOWS, rooms, support)
    assert plan == [("360F", W12), ("360F", w4_short)]


if __name__ == "__main__":
    test_full_day_single_room()
    test_partial_preferred_falls_back()
    test_target_room_ordered_first()
    test_uncovered_window_skipped()
    test_library_hours_shorten_afternoon()
    test_library_hours_prefer_ideal_when_offered()
    test_library_hours_user_reported_4_to_6()
    test_library_hours_reject_too_short()
    test_adjusted_afternoon_on_preferred_room()
    print("All room-fallback + library-hours tests passed.")
