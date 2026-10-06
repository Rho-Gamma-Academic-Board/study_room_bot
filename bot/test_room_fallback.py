#!/usr/bin/env python3
"""Unit tests for multi-room fallback planning (no LibCal)."""

import _bootstrap  # noqa: F401

from study_room_bot import assign_windows_from_support, ordered_cap10_rooms

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
    """Last night's case: 360F only has noon; evening goes to another large room."""
    rooms = ["360F", "360H", "370A", "370B"]
    support = {
        "360F": [W12],
        "360H": [],
        "370A": [W4, W8],
        "370B": [W4],
    }
    plan = assign_windows_from_support(WINDOWS, rooms, support)
    assert plan == [("360F", W12), ("370A", W4), ("370A", W8)]


def test_target_room_ordered_first(monkeypatch_env=None):
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
    support = {"360F": [W12], "370A": [W4]}
    plan = assign_windows_from_support(WINDOWS, rooms, support)
    assert plan == [("360F", W12), ("370A", W4)]


if __name__ == "__main__":
    test_full_day_single_room()
    test_partial_preferred_falls_back()
    test_target_room_ordered_first()
    test_uncovered_window_skipped()
    print("All room-fallback tests passed.")
