"""Resolution des regimes : propagation depuis chaque source, a chaque tick.

La topologie est du modele (elle ne bouge qu'a l'edition) ; les regimes dependent
des signaux de commande et se refont ici. C'est ce qui rend le tick bon marche :
le reseau est deja construit, seule la propagation reste a faire.

Le decouplage d'une transmission analogique a signal 15 est traite explicitement :
c'est le piege que le cahier demande d'ecrire en toutes lettres.
"""
from __future__ import annotations

import math
from collections import deque

from ..data.nbt import Pos
from ..model.kinetics import ANALOG_TRANSMISSION, KineticOrgan


class KineticSolution:
    __slots__ = ("speeds", "source_rpm", "conflicts")

    def __init__(self, speeds: dict[Pos, float], source_rpm: dict[Pos, float],
                 conflicts: list[dict]):
        self.speeds = speeds
        self.source_rpm = source_rpm
        self.conflicts = conflicts

    @property
    def max_rpm(self) -> float:
        return max((abs(v) for v in self.speeds.values()), default=0.0)

    @property
    def driven(self) -> int:
        return sum(1 for v in self.speeds.values() if abs(v) > 1e-9)


def solve_speeds(kin: KineticOrgan, signals: dict[Pos, int] | None = None,
                 stopped: set[int] | None = None) -> KineticSolution:
    """Propage le regime depuis chaque source, dans l'ordre decroissant.

    `stopped` : index de reseaux en surcharge, dont les consommateurs sont a
    l'arret (F2.6). `signals` : signal recu par chaque transmission analogique.
    """
    signals = signals or {}
    stopped = stopped or set()
    ceiling = kin.tables.get("kinetics.max_rotation_speed")
    decouple = kin.tables.get("kinetics.analog_transmission_decouple_signal")
    numerator = kin.tables.get("kinetics.analog_transmission_numerator")

    speeds: dict[Pos, float] = {}
    source_rpm: dict[Pos, float] = {}
    conflicts: list[dict] = []

    for src in sorted(kin.sources, key=lambda s: -abs(s.rpm)):
        source_rpm[src.pos] = src.rpm
        if kin.comp_of.get(src.pos) in stopped:
            continue
        if src.pos in speeds:
            continue
        speeds[src.pos] = src.rpm
        queue = deque([src.pos])
        while queue:
            cur = queue.popleft()
            for nxt, ratio in kin.adj.get(cur, ()):
                v = speeds[cur] * ratio
                block = kin.nodes[nxt]
                if block["name"] == ANALOG_TRANSMISSION:
                    nbt = block.get("nbt") or {}
                    sig = int(signals.get(nxt, nbt.get("Signal", 0) or 0))
                    if sig >= decouple:
                        continue
                    if 1 <= sig <= decouple - 1:
                        v *= numerator / (decouple - sig)
                if abs(v) > ceiling:
                    v = math.copysign(ceiling, v)
                if nxt in speeds:
                    if (abs(abs(speeds[nxt]) - abs(v)) > 1e-6
                            and len(conflicts) < 12):
                        conflicts.append({
                            "pos": list(nxt), "bloc": block["name"],
                            "regimes": [round(speeds[nxt], 2), round(v, 2)]})
                    continue
                speeds[nxt] = v
                queue.append(nxt)
    return KineticSolution(speeds, source_rpm, conflicts)


def concordance(kin: KineticOrgan, speeds: dict[Pos, float],
                tolerance: float = 0.51) -> dict:
    """Compare le solveur aux regimes reellement mesures par le jeu.

    Le jeu fournit sa propre verite terrain : une structure sauvegardee moteur
    tournant conserve dans son NBT les regimes mesures. C'est le mecanisme de
    validation du simulateur, et il est gratuit.
    """
    recorded = kin.recorded
    agree = 0
    ecarts: list[dict] = []
    for pos, measured in sorted(recorded.items()):
        computed = speeds.get(pos)
        ok = computed is not None and abs(abs(computed) - abs(measured)) < tolerance
        if ok:
            agree += 1
        elif len(ecarts) < 12:
            ecarts.append({"pos": list(pos), "bloc": kin.s.blocks[pos]["name"],
                           "mesure": round(measured, 2),
                           "calcule": round(computed, 2) if computed is not None
                           else None})
    return {
        "regimes_enregistres": len(recorded),
        "concordance_solveur": "%d/%d" % (agree, len(recorded)) if recorded else None,
        "accord": agree,
        "total": len(recorded),
        "ecarts": ecarts,
    }
