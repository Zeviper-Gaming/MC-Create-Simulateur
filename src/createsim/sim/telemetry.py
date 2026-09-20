"""Trace par tick, export CSV et relecture.

Le cahier demande l'enregistrement continu de : temps, position, vitesse,
assiette, FORCES PAR SOURCE, regimes, remplissage des ballons, Stress Units.
« Forces par source » est la clef : agreger par famille suffit a tracer une
courbe, mais pas a rejouer une trace ni a savoir laquelle des six helices a
molli.

Format ouvert et lisible a la main, comme le cahier l'exige : un CSV a en-tete,
une ligne par tick. Les colonnes de force portent la clef stable de leur source
— `f_helice@11,10,10_y` — pour qu'un fichier reste interpretable sans le code.

Les POINTS d'application ne sont pas enregistres : ils viennent du modele, qui
est le meme au rejeu. Une trace se relit donc avec son vaisseau, pas seule.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field

BASE_COLUMNS = (
    "tick", "temps_s", "x", "y", "z", "vx", "vy", "vz",
    "vitesse", "vitesse_horizontale", "vitesse_verticale",
    "pression", "masse", "poids", "portance", "poussee", "trainee",
    "resultante_y", "gaz_total", "gaz_capacite", "regime_max",
    "stress_su", "capacite_su", "au_sol",
)

#: au-dela, on cesse d'enregistrer plutot que de grignoter la memoire sans fin.
#: 120 000 ticks font 100 minutes de vol a 20 ticks/s.
MAX_ROWS = 120_000

AXES = ("x", "y", "z")


@dataclass
class Trace:
    """L'enregistrement continu, un enregistrement par tick."""

    rows: list[dict] = field(default_factory=list)
    every: int = 1
    force_keys: list[str] = field(default_factory=list)
    truncated: bool = False

    # -- enregistrement ----------------------------------------------------
    def record(self, sim) -> None:
        st = sim.state
        if self.every > 1 and st.tick % self.every and self.rows:
            return
        if len(self.rows) >= MAX_ROWS:
            self.truncated = True
            return

        forces = st.forces or sim.current_forces(st)
        if not self.force_keys:
            self.force_keys = [f.key for f in forces]

        by_family: dict[str, float] = {}
        resultant = [0.0, 0.0, 0.0]
        for f in forces:
            by_family[f.family] = by_family.get(f.family, 0.0) + f.magnitude
            for i in range(3):
                resultant[i] += f.vector[i]

        stress_su = capacity_su = 0.0
        for net in sim.stress.budget(st.speeds, st.source_rpm):
            stress_su += net["stress_su"]
            capacity_su += net["capacite_su"]

        row = {
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
        }
        for f in forces:
            for axis, value in zip(AXES, f.vector):
                row["f_%s_%s" % (f.key, axis)] = round(value, 3)
        self.rows.append(row)

    # -- lecture -----------------------------------------------------------
    @property
    def columns(self) -> list[str]:
        out = list(BASE_COLUMNS)
        for key in self.force_keys:
            out += ["f_%s_%s" % (key, axis) for axis in AXES]
        return out

    def column(self, name: str) -> list:
        return [r.get(name) for r in self.rows]

    def last(self) -> dict | None:
        return self.rows[-1] if self.rows else None

    def window(self, seconds: float) -> list[dict]:
        """Les enregistrements de la fenetre glissante la plus recente."""
        if not self.rows:
            return []
        end = self.rows[-1]["temps_s"]
        start = end - seconds
        return [r for r in self.rows if r["temps_s"] >= start]

    def vectors_at(self, index: int) -> dict[str, tuple]:
        """Les forces enregistrees a ce tick, par clef de source."""
        if not (0 <= index < len(self.rows)):
            return {}
        row = self.rows[index]
        out = {}
        for key in self.force_keys:
            out[key] = tuple(float(row.get("f_%s_%s" % (key, axis), 0.0) or 0.0)
                             for axis in AXES)
        return out

    def __len__(self) -> int:
        return len(self.rows)

    # -- fichiers ----------------------------------------------------------
    def to_csv(self, path: str) -> str:
        columns = self.columns
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.rows)
        return path

    @classmethod
    def from_csv(cls, path: str) -> "Trace":
        """Relit une trace. Les colonnes de force sont reconnues a leur prefixe."""
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            names = list(reader.fieldnames or [])
            rows = []
            for raw in reader:
                row = {}
                for name, text in raw.items():
                    if text is None or text == "":
                        continue
                    try:
                        row[name] = float(text)
                    except ValueError:
                        row[name] = text
                if row:
                    rows.append(row)
        keys: list[str] = []
        for name in names:
            if name.startswith("f_") and name.endswith("_y"):
                keys.append(name[2:-2])
        return cls(rows=rows, force_keys=keys)
