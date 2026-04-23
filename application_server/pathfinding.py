import heapq
from typing import Optional

from .grid import Grid


def astar(grid: Grid, start: tuple[int, int], goal: tuple[int, int]) -> Optional[list[tuple[int, int]]]:
    if not grid.is_free(*start) or not grid.is_free(*goal):
        return None
    if start == goal:
        return [start]
    open_heap = [(0, 0, start)]
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g_score = {start: 0}
    counter = 0
    while open_heap:
        _, _, current = heapq.heappop(open_heap)
        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path
        cx, cy = current
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nxt = (cx + dx, cy + dy)
            if not grid.is_free(*nxt):
                continue
            tentative_g = g_score[current] + 1
            if tentative_g < g_score.get(nxt, 1 << 30):
                came_from[nxt] = current
                g_score[nxt] = tentative_g
                counter += 1
                heapq.heappush(open_heap, (tentative_g + abs(nxt[0] - goal[0]) + abs(nxt[1] - goal[1]), counter, nxt))
    return None
