"""Pression atmospherique et sol.

Port exact de Sable `DimensionPhysics.createDefault()` + `BezierResourceFunction`
(interpolation Hermite cubique entre les points de controle).

Le sol est defini des maintenant comme une FONCTION HAUTEUR AU POINT, pour qu'un
terrain importe puisse s'y substituer plus tard sans rien changer au reste
(decision arretee du cahier : plan horizontal a altitude reglable en L0,
import de terrain comme evolution).
"""
from __future__ import annotations

import math
from typing import Protocol


class PressureCurve:
    """Le profil de pression, calcule une fois puis interpole."""

    __slots__ = ("points", "_alts")

    def __init__(self, points: list[tuple[float, float, float]]):
        self.points = points
        self._alts = [p[0] for p in points]

    @classmethod
    def from_tables(cls, tables) -> "PressureCurve":
        k = tables.get("pressure.pressure_k")
        cap = tables.get("pressure.pressure_cap")
        step = tables.get("pressure.pressure_step")
        margin = tables.get("pressure.pressure_top_margin")
        sea_level = tables.get("pressure.sea_level")
        min_y = tables.get("pressure.min_y")
        logical_height = tables.get("pressure.logical_height")

        max_y = min_y + logical_height
        top_band = max_y - margin
        y = max(float(min_y), math.log(cap) / k + sea_level)

        points: list[tuple[float, float, float]] = []
        while True:
            v = math.exp(k * (y - sea_level))
            points.append((y, v, v * k))
            if y < sea_level and y + step >= sea_level:
                y = float(sea_level)
            elif y < top_band and y + step >= top_band:
                y = top_band
            elif y >= top_band:
                break
            else:
                y += step

        last_value = points[-1][1]
        end_slope = -2.0 * last_value / (max_y - top_band)
        points.append((float(max_y), 0.0, end_slope))
        return cls(points)

    def at(self, y: float) -> float:
        pts = self.points
        if not pts:
            return 1.0
        if len(pts) == 1:
            return pts[0][1]

        idx = -1
        for alt in self._alts:
            if y < alt:
                break
            idx += 1
        if idx == -1:
            return pts[0][1]
        if idx >= len(pts) - 1:
            return pts[-1][1]

        a0, v0, m0 = pts[idx]
        a1, v1, m1 = pts[idx + 1]
        dx = a1 - a0
        dy = v1 - v0
        t = (y - a0) / dx
        a = (m0 + m1) * dx - 2.0 * dy
        b = 3.0 * dy - (2.0 * m0 + m1) * dx
        c = dx * m0
        return max(0.0, ((a * t + b) * t + c) * t + v0)

    def altitude_for(self, target: float, lo: float = -64.0,
                     hi: float = 320.0) -> float | None:
        """Altitude ou la pression vaut `target`, par dichotomie."""
        cap = self.at(lo)
        if target > cap:
            return None
        if self.at(hi) > target:
            return hi
        for _ in range(200):
            mid = (lo + hi) / 2.0
            if self.at(mid) > target:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0


class Ground(Protocol):
    def height_at(self, x: float, z: float) -> float: ...


class FlatGround:
    """Plan horizontal a altitude reglable. Le sol de L0."""

    __slots__ = ("y", "friction", "enabled")

    def __init__(self, y: float = 0.0, friction: float = 1.0,
                 enabled: bool = True):
        self.y = y
        self.friction = friction
        self.enabled = enabled

    def height_at(self, x: float, z: float) -> float:
        return self.y if self.enabled else float("-inf")

    def report(self) -> dict:
        return {"type": "plan horizontal", "altitude": self.y,
                "friction": self.friction, "actif": self.enabled}


class NoGround:
    """Espace libre : le vehicule evolue sans plan de sol."""

    __slots__ = ()

    def height_at(self, x: float, z: float) -> float:
        return float("-inf")

    def report(self) -> dict:
        return {"type": "aucun", "actif": False}
