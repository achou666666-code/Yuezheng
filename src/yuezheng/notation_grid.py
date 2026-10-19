"""Shared notation grid used by every projection of a music plan.

The MusicXML projection and the jianpu projection must agree on where a note
starts and how long it lasts, so both take their bars and lanes from here.
Performance timing stays in the plan: this grid is a provisional notation
projection and never changes the recorded performance.
"""
from collections import defaultdict

from .music_plan import seconds_to_quarters

TICKS = 480

TYPES = [(1920, "whole"), (960, "half"), (480, "quarter"), (240, "eighth"),
         (120, "16th"), (60, "32nd"), (30, "64th")]


def pieces(duration):
    """Split a duration into representable note values, longest first."""
    for base, kind in TYPES:
        dotted = base * 3 // 2
        while duration >= dotted:
            yield dotted, kind, True
            duration -= dotted
        while duration >= base:
            yield base, kind, False
            duration -= base
    if duration:
        raise ValueError("Duration is not representable on this notation grid")


def bars(plan, last):
    """Return (start_tick, end_tick, meter) for every bar up to ``last``."""
    meters = plan["meter_map"]
    result, pos, index = [], 0, 0
    while pos < max(480, last):
        if index + 1 < len(meters) and round(meters[index + 1]["quarter"] * 480) == pos:
            index += 1
        m = meters[index]
        end = pos + round(m["numerator"] * 4 / m["denominator"] * 480)
        result.append((pos, end, m))
        pos = end
    return result


def lanes(plan, track):
    """Group one track's events into non-overlapping voices on the grid."""
    grid = round(plan.get("notation", {}).get("grid_quarters", .25) * 480)
    grouped = defaultdict(list)
    for event in plan["performance"]["events"]:
        if event["track"] == track["id"]:
            begin = round(seconds_to_quarters(event["start_seconds"], plan["tempo_map"]) * 480 / grid) * grid
            end = max(begin + grid, round(seconds_to_quarters(event["end_seconds"], plan["tempo_map"]) * 480 / grid) * grid)
            grouped[begin, end].append(event)
    result = []
    for (begin, end), notes in sorted(grouped.items()):
        lane = next((l for l in result if l[-1][1] <= begin), None)
        if lane is None:
            lane = []
            result.append(lane)
        lane.append((begin, end, notes))
    return result or [[]]
