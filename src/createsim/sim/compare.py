"""Comparer deux executions : dire CE QUI A BOUGE (F5, lot L4).

Deux usages, une seule mecanique. Comparer deux configurations du meme
vaisseau repond a « est-ce que ma modification a servi a quelque chose ». La
non-regression repond a « qu'est-ce que la mise a jour du mod a change chez
moi ». Dans les deux cas, la question n'est pas « quelles valeurs » mais
« lesquelles ont bouge, et de combien ».

Deux sorties, parce qu'elles ne repondent pas a la meme chose :

    les indicateurs      l'ampleur — l'altitude d'equilibre a pris 12 m
    la premiere divergence  l'instant — tout colle jusqu'a la seconde 12

Le second est le plus utile des deux et le plus facile a oublier. Un ecart de
3 % sur l'altitude finale ne dit pas s'il vient d'une portance qui a change au
depart ou d'une trainee qui derive sur toute la montee ; le tick ou les deux
traces se separent, si.

Un indicateur absent d'une trace n'est pas compare, il est SIGNALE. Une
comparaison qui tait silencieusement une colonne manquante laisserait croire
que tout va bien parce que la moitie du bilan n'a pas ete regardee.
"""
from __future__ import annotations

from dataclasses import dataclass

from .telemetry import Trace

#: les grandeurs qu'on suit d'une execution a l'autre.
#: (colonne, agregation, unite, tolerance relative)
INDICATORS: dict[str, tuple] = {
    "altitude finale": ("y", "dernier", "m", 0.001),
    "altitude max": ("y", "max", "m", 0.001),
    "montee": ("y", "temps_63pct", "s", 0.02),
    "vitesse verticale max": ("vitesse_verticale", "max_abs", "blocs/s", 0.001),
    "vitesse max": ("vitesse", "max", "blocs/s", 0.001),
    "distance horizontale": ("vitesse_horizontale", "integrale", "blocs", 0.001),
    "gaz final": ("gaz_total", "dernier", "m³", 0.001),
    "regime max": ("regime_max", "max", "tr/min", 0.001),
    "SU demandes max": ("stress_su", "max", "su", 0.001),
    "capacite SU": ("capacite_su", "max", "su", 0.001),
    "ticks en surcharge": ("surcharge", "somme", "ticks", 0.0),
    "ticks au sol": ("au_sol", "somme", "ticks", 0.0),
}

#: colonnes suivies pour dater la premiere divergence
WATCHED = ("y", "vitesse_verticale", "gaz_total", "regime_max", "stress_su")


def _values(trace: Trace, column: str) -> list[float]:
    return [v for v in trace.column(column) if isinstance(v, (int, float))]


def _aggregate(trace: Trace, column: str, how: str) -> float | None:
    values = _values(trace, column)
    if not values:
        return None
    if how == "dernier":
        return float(values[-1])
    if how == "max":
        return float(max(values))
    if how == "max_abs":
        return float(max(values, key=abs))
    if how == "somme":
        return float(sum(values))
    if how == "integrale":
        times = _values(trace, "temps_s")
        if len(times) < 2:
            return 0.0
        total = 0.0
        for i in range(1, min(len(times), len(values))):
            total += abs(values[i]) * (times[i] - times[i - 1])
        return total
    if how == "temps_63pct":
        # le temps caracteristique : la trainee etant lineaire, c'est lui qui
        # bouge quand une constante de force change, avant l'altitude finale.
        times = _values(trace, "temps_s")
        start, end = values[0], values[-1]
        if abs(end - start) < 1e-9:
            return None
        target = start + 0.632 * (end - start)
        for t, v in zip(times, values):
            if (v >= target) if end > start else (v <= target):
                return float(t)
        return None
    raise ValueError("agregation inconnue : %s" % how)


def indicators(trace: Trace) -> dict[str, float | None]:
    return {name: _aggregate(trace, column, how)
            for name, (column, how, _unit, _tol) in INDICATORS.items()}


@dataclass
class Delta:
    """Un indicateur, avant et apres."""

    nom: str
    avant: float | None
    apres: float | None
    unite: str
    tolerance: float

    @property
    def absent(self) -> bool:
        return self.avant is None or self.apres is None

    @property
    def ecart(self) -> float | None:
        if self.absent:
            return None
        return self.apres - self.avant

    @property
    def relatif(self) -> float | None:
        """Ecart relatif. `None` quand la reference est nulle : diviser par
        zero donnerait un infini qui ne veut rien dire de plus que l'ecart."""
        if self.absent or abs(self.avant) < 1e-12:
            return None
        return (self.apres - self.avant) / abs(self.avant)

    @property
    def bouge(self) -> bool:
        if self.absent:
            return True
        ecart = abs(self.apres - self.avant)
        if abs(self.avant) < 1e-12:
            return ecart > 1e-9
        return ecart / abs(self.avant) > self.tolerance

    def line(self) -> str:
        if self.absent:
            return "%-24s ABSENT d'une des deux traces" % self.nom
        relatif = ("%+7.2f %%" % (100 * self.relatif)
                   if self.relatif is not None else "      —")
        return ("%-24s %12.3f -> %12.3f  %-9s %s"
                % (self.nom, self.avant, self.apres, self.unite, relatif))


@dataclass
class Comparison:
    """Ce qui a bouge entre deux executions."""

    deltas: list[Delta]
    divergence_tick: int | None
    divergence_colonne: str | None
    divergence_seconde: float | None
    longueurs: tuple[int, int]

    @property
    def bouges(self) -> list[Delta]:
        return [d for d in self.deltas if d.bouge]

    @property
    def identique(self) -> bool:
        return not self.bouges and self.divergence_tick is None

    @property
    def verdict(self) -> str:
        if self.identique:
            return "identique"
        if self.longueurs[0] != self.longueurs[1]:
            return "traces de longueurs differentes"
        graves = [d for d in self.bouges
                  if d.relatif is not None and abs(d.relatif) > 0.05]
        return "rupture" if graves else "derive"

    def report(self) -> dict:
        return {
            "verdict": self.verdict,
            "identique": self.identique,
            "longueurs": list(self.longueurs),
            "divergence": None if self.divergence_tick is None else {
                "tick": self.divergence_tick,
                "seconde": self.divergence_seconde,
                "colonne": self.divergence_colonne,
            },
            "indicateurs": [
                {"nom": d.nom, "avant": d.avant, "apres": d.apres,
                 "unite": d.unite, "ecart": d.ecart, "relatif": d.relatif,
                 "bouge": d.bouge}
                for d in self.deltas
            ],
        }

    def text(self) -> str:
        lines = ["verdict : %s" % self.verdict]
        if self.divergence_tick is not None:
            lines.append(
                "les traces se separent au tick %d (%.2f s), sur « %s »"
                % (self.divergence_tick, self.divergence_seconde or 0.0,
                   self.divergence_colonne))
        else:
            lines.append("aucune divergence tick a tick")
        bouges = self.bouges
        if not bouges:
            lines.append("aucun indicateur n'a bouge")
        for delta in bouges:
            lines.append("  " + delta.line())
        return "\n".join(lines)


def first_divergence(a: Trace, b: Trace,
                     tolerance: float = 1e-6) -> tuple[int | None, str | None,
                                                       float | None]:
    """Le premier tick ou les deux traces cessent de coincider.

    C'est l'information que les indicateurs ne donnent pas : elle date le
    changement au lieu d'en mesurer l'effet cumule.
    """
    for row_a, row_b in zip(a.rows, b.rows):
        for column in WATCHED:
            va, vb = row_a.get(column), row_b.get(column)
            if not isinstance(va, (int, float)) or not isinstance(vb, (int, float)):
                continue
            echelle = max(1.0, abs(va), abs(vb))
            if abs(va - vb) > tolerance * echelle:
                return (row_a.get("tick"), column, row_a.get("temps_s"))
    if len(a.rows) != len(b.rows):
        shortest = min(len(a.rows), len(b.rows))
        if shortest:
            row = (a.rows if len(a.rows) > shortest else b.rows)[shortest]
            return (row.get("tick"), "longueur", row.get("temps_s"))
    return (None, None, None)


def compare(reference: Trace, candidate: Trace,
            tolerance: float = 1e-6) -> Comparison:
    """Compare deux traces. `reference` est l'avant, `candidate` l'apres."""
    before, after = indicators(reference), indicators(candidate)
    deltas = [Delta(name, before.get(name), after.get(name), unit, tol)
              for name, (_col, _how, unit, tol) in INDICATORS.items()]
    tick, column, second = first_divergence(reference, candidate, tolerance)
    return Comparison(deltas=deltas, divergence_tick=tick,
                      divergence_colonne=column, divergence_seconde=second,
                      longueurs=(len(reference), len(candidate)))
