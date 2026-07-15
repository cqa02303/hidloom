"""Side-effect-free LED Life Game state for push-trigger effects."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class LifeGameCell:
    idx: int
    x: int
    y: int
    raw_x: float
    raw_y: float


def _ranked_axis(values: Sequence[float], *, tolerance: float = 0.25) -> dict[float, int]:
    ranks: dict[float, int] = {}
    current_rank = -1
    previous: float | None = None
    for value in sorted(set(float(v) for v in values)):
        if previous is None or abs(value - previous) > tolerance:
            current_rank += 1
        ranks[value] = current_rank
        previous = value
    return ranks


def cells_from_led_positions(led_keys: Sequence[str], led_positions: Mapping[str, Mapping[str, float]]) -> list[LifeGameCell]:
    """Convert physical LED coordinates to a sparse integer grid.

    The PCB coordinates are not uniformly spaced, but their x/y values still form
    stable rows and columns. Ranking each axis gives Conway-style neighbour
    checks without assuming a rectangular row-column matrix.
    """
    xs: list[float] = []
    ys: list[float] = []
    raw: list[tuple[int, float, float]] = []
    for idx, key in enumerate(led_keys):
        pos = led_positions.get(key)
        if not isinstance(pos, Mapping):
            continue
        try:
            x = float(pos["x"])
            y = float(pos["y"])
        except (KeyError, TypeError, ValueError):
            continue
        xs.append(x)
        ys.append(y)
        raw.append((idx, x, y))
    x_rank = _ranked_axis(xs)
    y_rank = _ranked_axis(ys)
    return [LifeGameCell(idx=idx, x=x_rank[x], y=y_rank[y], raw_x=x, raw_y=y) for idx, x, y in raw]


class LedLifeGameState:
    """Sparse Conway-like state with per-LED intensity decay."""

    def __init__(self, cells: Sequence[LifeGameCell], *, decay: float = 0.72, death_decay: float = 0.0) -> None:
        self._cells = list(cells)
        self._idx_to_xy = {cell.idx: (cell.x, cell.y) for cell in self._cells}
        self._xy_to_idx = {(cell.x, cell.y): cell.idx for cell in self._cells}
        self._neighbors = _build_staggered_neighbors(self._cells)
        self._alive: set[int] = set()
        self._intensity: dict[int, float] = {}
        self._pending_intensity: dict[int, float] = {}
        self._dying_intensity: dict[int, float] = {}
        self._born: set[int] = set()
        self._birth_parents: set[int] = set()
        self._tick = 0
        self._decay = max(0.0, min(1.0, float(decay)))
        self._death_decay = max(0.0, min(1.0, float(death_decay)))

    @property
    def alive_count(self) -> int:
        return len(self._alive)

    @property
    def pending_count(self) -> int:
        return len(self._pending_intensity)

    @property
    def tick_count(self) -> int:
        return self._tick

    def clear(self) -> None:
        self._alive.clear()
        self._intensity.clear()
        self._pending_intensity.clear()
        self._dying_intensity.clear()
        self._born.clear()
        self._birth_parents.clear()
        self._tick = 0

    def seed_index(self, idx: int, *, radius: int = 1, intensity: float = 1.0) -> None:
        center = self._idx_to_xy.get(int(idx))
        if center is None:
            return
        radius = max(0, int(radius))
        value = max(0.0, min(1.0, float(intensity)))
        seed = {int(idx)}
        frontier = {int(idx)}
        for _ in range(radius):
            next_frontier: set[int] = set()
            for item in frontier:
                next_frontier.update(self._neighbors.get(item, ()))
            seed.update(next_frontier)
            frontier = next_frontier
        for target in seed:
            self._alive.add(target)
            self._intensity[target] = max(value, self._intensity.get(target, 0.0))
            self._pending_intensity.pop(target, None)
            self._dying_intensity.pop(target, None)

    def queue_seed_index(self, idx: int, *, radius: int = 0, intensity: float = 1.0) -> None:
        if self._idx_to_xy.get(int(idx)) is None:
            return
        radius = max(0, int(radius))
        value = max(0.0, min(1.0, float(intensity)))
        seed = {int(idx)}
        frontier = {int(idx)}
        for _ in range(radius):
            next_frontier: set[int] = set()
            for item in frontier:
                next_frontier.update(self._neighbors.get(item, ()))
            seed.update(next_frontier)
            frontier = next_frontier
        for target in seed:
            if target in self._alive:
                self._intensity[target] = max(value, self._intensity.get(target, 0.0))
            else:
                self._pending_intensity[target] = max(value, self._pending_intensity.get(target, 0.0))
            self._dying_intensity.pop(target, None)

    def step(self) -> None:
        self._tick += 1
        if self._pending_intensity:
            self._born = set(self._pending_intensity)
            self._birth_parents.clear()
            self._alive.update(self._born)
            for idx, value in self._pending_intensity.items():
                self._intensity[idx] = max(value, self._intensity.get(idx, 0.0))
            self._pending_intensity.clear()
            return
        neighbor_counts: dict[int, int] = {}
        birth_parent_candidates: dict[int, set[int]] = {}
        for idx in self._alive:
            for neighbor in self._neighbors.get(idx, ()):
                neighbor_counts[neighbor] = neighbor_counts.get(neighbor, 0) + 1
                birth_parent_candidates.setdefault(neighbor, set()).add(idx)

        new_alive: set[int] = set()
        for idx, count in neighbor_counts.items():
            if count == 3 or (idx in self._alive and count == 2):
                new_alive.add(idx)
        born = new_alive - self._alive
        self._born = born
        dying = self._alive - new_alive
        new_dying_intensity: dict[int, float] = {}
        for idx, value in self._dying_intensity.items():
            if idx in new_alive:
                continue
            faded = value * self._death_decay
            if faded >= 0.03:
                new_dying_intensity[idx] = faded
        for idx in dying:
            new_dying_intensity[idx] = 1.0
        self._dying_intensity = new_dying_intensity
        self._birth_parents = set()
        for idx in born:
            self._birth_parents.update(birth_parent_candidates.get(idx, ()))

        new_intensity: dict[int, float] = {}
        for idx, value in self._intensity.items():
            if idx in dying or idx in self._dying_intensity:
                continue
            faded = value * self._decay
            if faded >= 0.03:
                new_intensity[idx] = faded
        for idx in new_alive:
            new_intensity[idx] = max(new_intensity.get(idx, 0.0), 1.0)

        self._alive = new_alive
        self._intensity = new_intensity

    def transition_frame(self, led_count: int) -> list[str]:
        out = [""] * max(0, int(led_count))
        for idx in self._born:
            if 0 <= idx < len(out):
                out[idx] = "born"
        for idx in self._pending_intensity:
            if 0 <= idx < len(out):
                out[idx] = "pending"
        for idx in self._birth_parents:
            if 0 <= idx < len(out):
                out[idx] = "birth_parent"
        for idx in self._dying_intensity:
            if 0 <= idx < len(out):
                out[idx] = "dying"
        return out

    def transition_intensity_frame(self, led_count: int) -> list[float]:
        out = [0.0] * max(0, int(led_count))
        for idx in self._born:
            if 0 <= idx < len(out):
                out[idx] = 1.0
        for idx, value in self._pending_intensity.items():
            if 0 <= idx < len(out):
                out[idx] = max(0.0, min(1.0, value))
        for idx in self._birth_parents:
            if 0 <= idx < len(out):
                out[idx] = 1.0
        for idx, value in self._dying_intensity.items():
            if 0 <= idx < len(out):
                out[idx] = max(0.0, min(1.0, value))
        return out

    def frame(self, led_count: int) -> list[float]:
        out = [0.0] * max(0, int(led_count))
        for idx, value in self._intensity.items():
            if 0 <= idx < len(out):
                out[idx] = max(0.0, min(1.0, value))
        for idx, value in self._pending_intensity.items():
            if 0 <= idx < len(out):
                out[idx] = max(out[idx], max(0.0, min(1.0, value)))
        return out


def _build_staggered_neighbors(cells: Sequence[LifeGameCell]) -> dict[int, tuple[int, ...]]:
    by_row: dict[int, list[LifeGameCell]] = {}
    for cell in cells:
        by_row.setdefault(cell.y, []).append(cell)
    for row in by_row.values():
        row.sort(key=lambda cell: (cell.raw_x, cell.x, cell.idx))

    neighbors: dict[int, set[int]] = {cell.idx: set() for cell in cells}

    def add(a: int, b: int) -> None:
        if a == b:
            return
        neighbors.setdefault(a, set()).add(b)
        neighbors.setdefault(b, set()).add(a)

    for row_index, row in by_row.items():
        for pos, cell in enumerate(row):
            if pos > 0:
                add(cell.idx, row[pos - 1].idx)
            if pos + 1 < len(row):
                add(cell.idx, row[pos + 1].idx)
            for adjacent_row_index in (row_index - 1, row_index + 1):
                adjacent = by_row.get(adjacent_row_index)
                if not adjacent:
                    continue
                nearest_pos = min(
                    range(len(adjacent)),
                    key=lambda index: (abs(adjacent[index].raw_x - cell.raw_x), abs(adjacent[index].x - cell.x)),
                )
                step = _row_step(adjacent)
                nearest_dx = abs(adjacent[nearest_pos].raw_x - cell.raw_x)
                if nearest_dx <= step * 0.25:
                    adjacent_positions = (nearest_pos - 1, nearest_pos, nearest_pos + 1)
                else:
                    adjacent_positions = tuple(
                        index
                        for index, adjacent_cell in enumerate(adjacent)
                        if abs(adjacent_cell.raw_x - cell.raw_x) <= step * 0.75
                    )
                for adjacent_pos in adjacent_positions:
                    if 0 <= adjacent_pos < len(adjacent):
                        add(cell.idx, adjacent[adjacent_pos].idx)
    return {idx: tuple(sorted(items)) for idx, items in neighbors.items()}


def _row_step(row: Sequence[LifeGameCell]) -> float:
    gaps = [
        abs(right.raw_x - left.raw_x)
        for left, right in zip(row, row[1:])
        if abs(right.raw_x - left.raw_x) > 0.0
    ]
    if not gaps:
        return 1.0
    gaps.sort()
    return gaps[len(gaps) // 2]
