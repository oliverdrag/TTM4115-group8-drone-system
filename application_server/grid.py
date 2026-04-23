"""200x200 grid with restricted zones generated as organic blobs.

The blobs are meant to feel like no-fly parks, not pin-drop circles. They're
grown from seed cells via a random walker that picks an adjacent empty
neighbour at each step until the blob hits its target size.
"""

import json
import random
from collections import deque
from typing import Iterable


FREE = 0
RESTRICTED = 1


class Grid:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.cells = [[FREE for _ in range(width)] for _ in range(height)]
        self.zones: list[dict] = []

    # ---- construction ---------------------------------------------------
    @classmethod
    def from_zones(cls, width: int, height: int, zones: list[dict]) -> "Grid":
        grid = cls(width, height)
        grid.zones = zones
        for zone in zones:
            for x, y in zone.get("cells", []):
                if grid.in_bounds(x, y):
                    grid.cells[y][x] = RESTRICTED
        return grid

    # ---- queries --------------------------------------------------------
    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_free(self, x: int, y: int) -> bool:
        return self.in_bounds(x, y) and self.cells[y][x] == FREE

    def restricted_cells(self) -> Iterable[tuple[int, int]]:
        for y in range(self.height):
            for x in range(self.width):
                if self.cells[y][x] == RESTRICTED:
                    yield (x, y)

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "zones": self.zones,
        }


def generate_zones(
    width: int,
    height: int,
    num_zones: int = 6,
    min_size: int = 250,
    max_size: int = 900,
    reserved: list[tuple[int, int]] | None = None,
    seed: int | None = None,
) -> list[dict]:
    """Grow `num_zones` organic no-fly blobs. Reserved cells are kept free."""
    rng = random.Random(seed)
    reserved_set = set(reserved or [])

    taken = set(reserved_set)
    zones: list[dict] = []

    zone_names = [
        "Jotunheimen National Park",
        "Rondane National Park",
        "Hardangervidda",
        "Dovrefjell",
        "Femundsmarka",
        "Saltfjellet-Svartisen",
        "Reinheimen",
        "Hallingskarvet",
    ]
    rng.shuffle(zone_names)

    for i in range(num_zones):
        for _attempt in range(50):
            sx = rng.randint(10, width - 11)
            sy = rng.randint(10, height - 11)
            if (sx, sy) in taken:
                continue
            # Keep a safe corridor clear so drones can always leave the hangar.
            if any(
                abs(sx - rx) + abs(sy - ry) < 8 for rx, ry in reserved_set
            ):
                continue
            break
        else:
            continue

        target = rng.randint(min_size, max_size)
        blob = _grow_blob(width, height, (sx, sy), target, taken)
        if not blob:
            continue
        zones.append(
            {
                "id": f"zone-{i:02d}",
                "name": zone_names[i % len(zone_names)],
                "cells": sorted(blob),
            }
        )
        taken.update(blob)

    return zones


def _grow_blob(
    width: int,
    height: int,
    seed: tuple[int, int],
    target: int,
    forbidden: set[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Random-walker blob growth. Picks a random frontier cell each step."""
    rng = random.Random((seed[0] * 7919 + seed[1]) & 0xFFFFFFFF)
    if seed in forbidden:
        return []

    blob: set[tuple[int, int]] = {seed}
    frontier = deque([seed])

    while blob and len(blob) < target:
        # Pop from a random-ish spot to avoid line-shaped growth.
        idx = rng.randrange(len(frontier))
        frontier.rotate(-idx)
        cx, cy = frontier.popleft()

        grew = False
        neighbours = [(cx + dx, cy + dy) for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1))]
        rng.shuffle(neighbours)
        for nx, ny in neighbours:
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if (nx, ny) in blob or (nx, ny) in forbidden:
                continue
            # Probabilistic growth gives ragged edges instead of square lumps.
            if rng.random() < 0.55:
                blob.add((nx, ny))
                frontier.append((nx, ny))
                grew = True
                if len(blob) >= target:
                    break
        if grew:
            frontier.append((cx, cy))  # keep exploring from here

    return list(blob)


# ---- JSON helpers ---------------------------------------------------------
def zones_to_json(zones: list[dict]) -> str:
    return json.dumps(zones)


def zones_from_json(blob: str) -> list[dict]:
    data = json.loads(blob)
    return data if isinstance(data, list) else []
