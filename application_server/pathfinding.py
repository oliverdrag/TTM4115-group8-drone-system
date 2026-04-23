"""A* over the 200x200 grid. 4-connected movement; Manhattan heuristic."""

import heapq
from typing import Optional

from .grid import Grid


def astar(
    grid: Grid,
    start: tuple[int, int],
    goal: tuple[int, int],
) -> Optional[list[tuple[int, int]]]:
    if not grid.is_free(*start) or not grid.is_free(*goal):
        return None
    if start == goal:
        return [start]

    open_heap: list[tuple[int, int, tuple[int, int]]] = []
    heapq.heappush(open_heap, (0, 0, start))
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g_score: dict[tuple[int, int], int] = {start: 0}
    counter = 0  # tiebreak for equal f-scores

    while open_heap:
        _, _, current = heapq.heappop(open_heap)
        if current == goal:
            return _reconstruct(came_from, current)

        cx, cy = current
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx, ny = cx + dx, cy + dy
            if not grid.is_free(nx, ny):
                continue
            tentative_g = g_score[current] + 1
            if tentative_g < g_score.get((nx, ny), 1 << 30):
                came_from[(nx, ny)] = current
                g_score[(nx, ny)] = tentative_g
                f = tentative_g + _heuristic((nx, ny), goal)
                counter += 1
                heapq.heappush(open_heap, (f, counter, (nx, ny)))

    return None


def _heuristic(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _reconstruct(
    came_from: dict[tuple[int, int], tuple[int, int]],
    current: tuple[int, int],
) -> list[tuple[int, int]]:
    path = [current]
    while current in came_from:
        current = came_from[current]
        path.append(current)
    path.reverse()
    return path
