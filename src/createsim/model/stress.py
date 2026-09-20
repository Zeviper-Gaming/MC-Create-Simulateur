"""Bilan Stress Units : qui fournit du couple, qui en consomme.

Cout faible, derive du reseau : invalide avec lui.

Agregation verifiee dans Create `KineticNetwork` :
    capacite_reseau = somme(sources)  capacity x |vitesse generee|
    stress_reseau   = somme(membres)  impact   x |vitesse|
    surcharge si stress > capacite

Un bloc absent des tables a un impact et une capacite nuls. Une surcharge n'a de
sens que sur un reseau qui a une source : du stress sans capacite signifie que
le solveur n'a pas relie ce reseau a son generateur — une limite du modele, pas
un defaut du vaisseau (F5.7).
"""
from __future__ import annotations

from ..data.nbt import Pos
from .vehicle import Organ


class NetworkStress:
    """Les membres d'un reseau, prets a etre sommes a chaque tick."""

    __slots__ = ("index", "cells", "loads", "generators")

    def __init__(self, index: int, cells: list[Pos]):
        self.index = index
        self.cells = cells
        self.loads: list[tuple[Pos, str, float]] = []
        self.generators: list[tuple[Pos, str, float]] = []


class StressOrgan(Organ):
    name = "stress"
    cost = "faible"
    depends = ("cinetique",)

    def __init__(self, model):
        super().__init__(model)
        self.networks: list[NetworkStress] = []

    def affected_by(self, pos: Pos) -> bool:
        name = self.s.name(pos)
        return (self.props.stress_impact(name) > 0
                or self.props.stress_capacity(name) > 0)

    def recompute(self) -> None:
        kin = self.model.organs["cinetique"]
        source_at = {src.pos for src in kin.sources}
        self.networks = []
        for i, cells in enumerate(kin.components):
            net = NetworkStress(i, cells)
            for pos in cells:
                name = kin.nodes[pos]["name"]
                impact = self.props.stress_impact(name)
                if impact:
                    net.loads.append((pos, name, impact))
                capacity = self.props.stress_capacity(name)
                if capacity and pos in source_at:
                    net.generators.append((pos, name, capacity))
            if net.loads or net.generators:
                self.networks.append(net)

    # -- somme a la volee, avec les regimes du tick courant -----------------
    def budget(self, speeds: dict[Pos, float], source_rpm: dict[Pos, float]) -> list[dict]:
        out: list[dict] = []
        for net in self.networks:
            capacity = 0.0
            gens = []
            for pos, name, cap in net.generators:
                rpm = abs(source_rpm.get(pos, 0.0))
                contrib = cap * rpm
                capacity += contrib
                gens.append({"bloc": name, "pos": list(pos), "rpm": round(rpm, 2),
                             "su": round(contrib, 1)})
            stress = 0.0
            loads = []
            for pos, name, impact in net.loads:
                rpm = abs(speeds.get(pos, 0.0))
                if not rpm:
                    continue
                contrib = impact * rpm
                stress += contrib
                loads.append({"bloc": name, "pos": list(pos), "rpm": round(rpm, 2),
                              "su": round(contrib, 1)})
            if not gens and not loads:
                continue
            loads.sort(key=lambda x: -x["su"])
            out.append({
                "blocs": len(net.cells),
                "capacite_su": round(capacity, 1),
                "stress_su": round(stress, 1),
                "marge_su": round(capacity - stress, 1),
                "taux_charge": round(stress / capacity, 3) if capacity else None,
                "surcharge": bool(capacity > 0 and stress > capacity),
                "sans_source": bool(stress > 0 and capacity == 0),
                "sources": gens,
                "consommateurs": loads[:8],
                "consommateurs_total": len(loads),
                "reseau": net.index,
            })
        out.sort(key=lambda x: -(x["capacite_su"] + x["stress_su"]))
        return out

    def overloaded_networks(self, speeds: dict[Pos, float],
                            source_rpm: dict[Pos, float]) -> set[int]:
        """Index des reseaux en surcharge : leurs consommateurs s'arretent (F2.6)."""
        return {r["reseau"] for r in self.budget(speeds, source_rpm) if r["surcharge"]}
