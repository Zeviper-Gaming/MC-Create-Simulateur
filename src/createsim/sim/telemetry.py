"""Trace par tick et export CSV.

Officiellement un lot ulterieur, mais indispensable des maintenant : c'est le
support des deux niveaux de validation automatiques, et c'est la que l'on voit
un vaisseau osciller autour de son altitude d'equilibre au lieu de s'y poser.

Format ouvert et lisible a la main, comme le cahier l'exige.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field

COLUMNS = (
    "tick", "temps_s", "x", "y", "z", "vx", "vy", "vz",
    "vitesse", "vitesse_horizontale", "vitesse_verticale",
    "pression", "masse", "poids", "portance", "poussee", "trainee",
    "resultante_y", "gaz_total", "gaz_capacite", "regime_max",
    "stress_su", "capacite_su", "au_sol",
)


@dataclass
class Trace:
    """L'enregistrement continu, un enregistrement par tick."""

    rows: list[dict] = field(default_factory=list)
    every: int = 1

    def record(self, sim) -> None:
        st = sim.state
        if self.every > 1 and st.tick % self.every and self.rows:
            return
        forces = st.forces or sim.current_forces(st)
        by_family: dict[str, float] = {}
        for f in forces:
            by_family[f.family] = by_family.get(f.family, 0.0) + f.magnitude
        resultant = [0.0, 0.0, 0.0]
        for f in forces:
            for i in range(3):
                resultant[i] += f.vector[i]
        stress_su = capacity_su = 0.0
        for net in sim.stress.budget(st.speeds, st.source_rpm):
            stress_su += net["stress_su"]
            capacity_su += net["capacite_su"]
        self.rows.append({
            "tick": st.tick,
            "temps_s": round(st.seconds, 3),
            "x": round(st.position[0], 4),
            "y": round(st.position[1], 4),
            "z": round(st.position[2], 4),
            "vx": round(st.velocity[0], 5),
            "vy": round(st.velocity[1], 5),
            "vz": round(st.velocity[2], 5),
            "vitesse": round(st.speed, 5),
            "vitesse_horizontale": round(st.horizontal_speed, 5),
            "vitesse_verticale": round(st.vertical_speed, 5),
            "pression": round(st.pressure, 5),
            "masse": round(sim.mass.total, 2),
            "poids": round(by_family.get("gravite", 0.0), 2),
            "portance": round(by_family.get("ballon", 0.0)
                              + by_family.get("levitite", 0.0), 2),
            "poussee": round(by_family.get("helice", 0.0)
                             + by_family.get("roue", 0.0), 2),
            "trainee": round(by_family.get("trainee", 0.0), 2),
            "resultante_y": round(resultant[1], 3),
            "gaz_total": round(sum(st.gas), 2),
            "gaz_capacite": sum(p.capacity for p in sim.balloons.pockets),
            "regime_max": round(max((abs(v) for v in st.speeds.values()),
                                    default=0.0), 2),
            "stress_su": round(stress_su, 1),
            "capacite_su": round(capacity_su, 1),
            "au_sol": int(st.on_ground),
        })

    def to_csv(self, path: str) -> str:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(COLUMNS))
            writer.writeheader()
            writer.writerows(self.rows)
        return path

    def column(self, name: str) -> list:
        return [r[name] for r in self.rows]

    def last(self) -> dict | None:
        return self.rows[-1] if self.rows else None

    def __len__(self) -> int:
        return len(self.rows)
