import random
from collections import deque

FREE = 0
RESTRICTED = 1


class Grid:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.cells = [[FREE] * width for _ in range(height)]
        self.zones: list[dict] = []

    @classmethod
    def from_zones(cls, width: int, height: int, zones: list[dict]) -> "Grid":
        grid = cls(width, height)
        grid.zones = zones
        for zone in zones:
            for x, y in zone.get("cells", []):
                if grid.in_bounds(x, y):
                    grid.cells[y][x] = RESTRICTED
        return grid

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_free(self, x: int, y: int) -> bool:
        return self.in_bounds(x, y) and self.cells[y][x] == FREE

    def to_dict(self) -> dict:
        return {"width": self.width, "height": self.height, "zones": self.zones}


ZONE_NAMES = [
    "Jotunheimen National Park", "Rondane National Park", "Hardangervidda",
    "Dovrefjell", "Femundsmarka", "Saltfjellet-Svartisen",
    "Reinheimen", "Hallingskarvet",
]


def generate_zones(width: int, height: int, num_zones: int = 5, min_size: int = 40,
                   max_size: int = 140, reserved: list[tuple[int, int]] | None = None,
                   seed: int | None = None) -> list[dict]:
    rng = random.Random(seed)
    reserved_set = set(reserved or [])
    taken = set(reserved_set)
    zones: list[dict] = []
    names = list(ZONE_NAMES)
    rng.shuffle(names)
    edge_pad = max(5, min(width, height) // 10)
    hangar_clearance = max(5, min(width, height) // 8)
    for i in range(num_zones):
        for _ in range(60):
            sx = rng.randint(edge_pad, width - edge_pad - 1)
            sy = rng.randint(edge_pad, height - edge_pad - 1)
            if (sx, sy) in taken:
                continue
            if any(abs(sx - rx) + abs(sy - ry) < hangar_clearance for rx, ry in reserved_set):
                continue
            break
        else:
            continue
        blob = _grow_blob(width, height, (sx, sy), rng.randint(min_size, max_size), taken)
        if not blob:
            continue
        zones.append({"id": f"zone-{i:02d}", "name": names[i % len(names)], "cells": sorted(blob)})
        taken.update(blob)
    return zones


def _grow_blob(width: int, height: int, seed: tuple[int, int], target: int,
               forbidden: set[tuple[int, int]]) -> list[tuple[int, int]]:
    rng = random.Random((seed[0] * 7919 + seed[1]) & 0xFFFFFFFF)
    if seed in forbidden:
        return []
    blob = {seed}
    frontier = deque([seed])
    while blob and len(blob) < target:
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
            if rng.random() < 0.55:
                blob.add((nx, ny))
                frontier.append((nx, ny))
                grew = True
                if len(blob) >= target:
                    break
        if grew:
            frontier.append((cx, cy))
    return list(blob)
