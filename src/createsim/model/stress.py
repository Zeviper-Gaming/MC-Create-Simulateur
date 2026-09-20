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

Un palier d'helice fait exception a l'impact fixe, et c'est une MESURE qui l'a
impose : son impact vaut la valeur de table PAR VOILE de son rotor, de la meme
facon que la capacite du moulin vaut 512 su PAR TOUR. Une helice de 16 voiles
a 256 tr/min consomme 8192 su, pas 512 (`data/mesures/jeu.json`). Rotor
assemble, le compte de voiles n'est plus dans le fichier : on retombe alors sur
l'impact fixe, et l'organe le signale comme une limite du modele plutot que de
livrer un chiffre faux sans le dire.
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
    depends = ("cinetique", "paliers")

    def __init__(self, model):
        super().__init__(model)
        self.networks: list[NetworkStress] = []
        self.per_sail: frozenset[str] = frozenset()
        #: paliers dont le compte de voiles est inconnu (rotor assemble)
        self.unknown_rotors: list[Pos] = []

    def affected_by(self, pos: Pos) -> bool:
        name = self.s.name(pos)
        return (self.props.stress_impact(name) > 0
                or self.props.stress_capacity(name) > 0)

    def _impact_at(self, pos: Pos, name: str) -> float:
        """L'impact d'un bloc, voiles comprises quand il en porte.

        Le palier d'helice porte l'impact de tout son rotor : les voiles ne
        sont pas des membres du reseau, elles sont dans la contraption.
        """
        impact = self.props.stress_impact(name)
        if not impact or name not in self.per_sail:
            return impact
        bearing = self.model.organs["paliers"].at(pos)
        if bearing is None:
            return impact
        if not bearing.sails_known:
            self.unknown_rotors.append(pos)
            return impact
        return impact * bearing.sails

    def recompute(self) -> None:
        kin = self.model.organs["cinetique"]
        source_at = {src.pos for src in kin.sources}
        self.per_sail = frozenset(
            self.tables.get("stress.impact_scales_with_sails"))
        self.unknown_rotors = []
        self.networks = []
        for i, cells in enumerate(kin.components):
            net = NetworkStress(i, cells)
            for pos in cells:
                name = kin.nodes[pos]["name"]
                impact = self._impact_at(pos, name)
                if impact:
                    net.loads.append((pos, name, impact))
                capacity = self.props.stress_capacity(name)
                if capacity and pos in source_at:
                    net.generators.append((pos, name, capacity))
            if net.loads or net.generators:
                self.networks.append(net)

    # -- somme a la volee, avec les regimes du tick courant -----------------
    def budget(self, speeds: dict[Pos, float], source_rpm: dict[Pos, float],
               demand: dict[Pos, float] | None = None,
               overloaded: set[int] | None = None) -> list[dict]:
        """Le bilan par reseau, aux regimes du tick.

        `demand` porte les regimes d'AVANT l'arret pour surcharge. Sur un
        reseau qui a disjoncte, ce sont eux qu'il faut publier : les regimes
        retenus valent zero, et un bilan a « 0 SU demandes, pas de surcharge »
        laisserait un vaisseau arrete sans aucune explication.
        """
        overloaded = overloaded or set()
        out: list[dict] = []
        for net in self.networks:
            tripped = net.index in overloaded
            speeds_here = demand if (tripped and demand) else speeds
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
                rpm = abs(speeds_here.get(pos, 0.0))
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
                "surcharge": bool(tripped or (capacity > 0 and stress > capacity)),
                "disjoncte": tripped,
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
