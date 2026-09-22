"""Une variante : ce qu'une edition change, chiffre, et rejouable (F6, lot L5).

Trois choses font d'une edition autre chose qu'un jeu de l'esprit.

Le diff chiffre (F6.6). Une variante s'affiche par rapport a l'etat charge,
jamais dans l'absolu : masse, portance, centre de masse, marge de Stress Units,
vitesse de pointe, altitude d'equilibre, chacun avec son ecart signe. C'est ce
qui transforme une intuition en mesure.

Et la comparaison se fait SOUS LES MEMES COMMANDES. Sans cela, pousser une
manette apres avoir supprime un bloc ferait passer l'effet de la manette pour
celui de l'edition. D'ou la reference : une copie intacte du vaisseau, evaluee
avec les commandes courantes de la session.

Les intentions (F6.8). Une edition se consigne comme on la dirait — « supprimer
12,4,7 », « deplacer 5,3,9 vers 5,6,9 » — et non comme deux etats de bloc. Un
scenario les porte, les rejoue sur le fichier source, et deux variantes du meme
vaisseau se comparent courbe contre courbe.

L'export (F6.7), dans un fichier nouveau, nomme et horodate : c'est ce qui
ferme la boucle — on eprouve hors-jeu, on rapporte en jeu.
"""
from __future__ import annotations

import math
import re
import time
from pathlib import Path

from ..model.vehicle import VehicleModel
from .compare import Delta
from .state import SimOptions
from .tick import Simulation

#: les grandeurs du diff, dans l'ordre du cahier : (nom, unite, tolerance)
QUANTITIES = (
    ("masse", "", 1e-6),
    ("portance max", "", 1e-6),
    ("centre de masse x", "bloc", 1e-6),
    ("centre de masse y", "bloc", 1e-6),
    ("centre de masse z", "bloc", 1e-6),
    ("marge SU", "su", 1e-6),
    ("vitesse de pointe", "blocs/s", 1e-6),
    ("altitude d'equilibre", "m", 1e-6),
)

#: familles de force qui poussent le vaisseau a l'horizontale
PROPULSION = ("helice", "roue")


def top_speed(sim: Simulation) -> float | None:
    """La vitesse horizontale vers laquelle la poussee COURANTE entraine.

    Evaluee avec l'amortissement reel, axe par axe, et a la vitesse atteinte :
    le levitite freine beaucoup a l'arret et presque plus a pleine vitesse, et
    l'ignorer sous-estimerait la vitesse de pointe du cruiser d'un ordre de
    grandeur. Point fixe : la vitesse fixe l'amortissement qui fixe la vitesse.

    `None` quand rien ne pousse — pas zero : un vaisseau sans poussee n'a pas
    une vitesse de pointe nulle, il n'en a pas.
    """
    st = sim.state
    thrust = [0.0, 0.0, 0.0]
    for force in sim.current_forces(st):
        if force.family in PROPULSION:
            for i in range(3):
                thrust[i] += force.vector[i]
    if abs(thrust[0]) < 1e-9 and abs(thrust[2]) < 1e-9:
        return None
    velocity = [0.0, 0.0, 0.0]
    for _ in range(12):
        damping = sim._damping(st, velocity)
        new = [thrust[i] / damping[i] if damping[i] > 1e-12 else math.inf
               for i in (0, 2)]
        if any(math.isinf(v) for v in new):
            return math.inf
        velocity = [new[0], 0.0, new[1]]
    return math.hypot(velocity[0], velocity[2])


def measure(sim: Simulation) -> dict[str, float | None]:
    """Les grandeurs du diff, lues sur une simulation a son etat courant."""
    report = sim.report()
    bilan = report.get("bilan") or {}
    com = report.get("centre_de_masse") or [0.0, 0.0, 0.0]
    margins = [n["marge_su"] for n in report.get("stress") or []
               if n.get("capacite_su", 0) > 0]
    return {
        "masse": report.get("masse"),
        "portance max": bilan.get("portance_max"),
        "centre de masse x": com[0],
        "centre de masse y": com[1],
        "centre de masse z": com[2],
        # le reseau le plus proche de disjoncter : c'est lui qui borne le vaisseau
        "marge SU": min(margins) if margins else None,
        "vitesse de pointe": top_speed(sim),
        "altitude d'equilibre": bilan.get("altitude_equilibre"),
    }


class Baseline:
    """L'etat charge, intact, evalue sous les commandes de la session.

    Une copie du vaisseau relue depuis le fichier source : elle ne recoit
    jamais d'edition. Construite a la demande — la premiere edition la paie,
    une session qui n'edite rien ne la paie pas.
    """

    def __init__(self, path: str, tables=None, options: SimOptions | None = None):
        self.model = VehicleModel.load(path, tables)
        self.sim = Simulation(self.model, options or SimOptions())
        self._cache: tuple | None = None
        self._values: dict[str, float | None] = {}

    def measure(self, commands: dict, state=None) -> dict[str, float | None]:
        """Les grandeurs de l'etat charge, sous ces commandes et a cet etat.

        `state` : celui de la session. Sans lui, la reference resterait a son
        altitude de depart pendant que la variante vole a 150 m — autre
        pression, autre trainee, et deux vitesses de pointe qui ne se
        comparent pas. Position et contact au sol sont donc recopies.
        """
        key = (tuple(sorted(commands.items())),
               None if state is None else (tuple(state.position),
                                           bool(state.on_ground)))
        if key == self._cache:
            return self._values
        st = self.sim.state
        if state is not None:
            st.position = list(state.position)
            st.on_ground = bool(state.on_ground)
            st.pressure = self.sim.curve.at(st.position[1])
        for lever, value in commands.items():
            self.sim.set_command(lever, value)
        self.sim._solve(st)
        self._values = measure(self.sim)
        self._cache = key
        return self._values


def diff(before: dict, after: dict) -> list[Delta]:
    """Chaque grandeur, avant et apres, avec son ecart signe."""
    return [Delta(name, before.get(name), after.get(name), unit, tol)
            for name, unit, tol in QUANTITIES]


def variant_diff(sim: Simulation, baseline: Baseline) -> list[Delta]:
    """Le diff de la session courante contre l'etat charge, memes commandes."""
    reference = baseline.measure(dict(sim.state.commands), sim.state)
    return diff(reference, measure(sim))


# ---------------------------------------------------------------------------
# Intentions : ce qu'un scenario consigne et rejoue (F6.8)
# ---------------------------------------------------------------------------
def _pos(value) -> tuple[int, int, int]:
    if isinstance(value, str):
        x, y, z = (int(v) for v in value.replace(" ", "").split(","))
        return (x, y, z)
    x, y, z = (int(v) for v in value)
    return (x, y, z)


def _fmt(value) -> str:
    return "%d,%d,%d" % tuple(value)


def ops_to_json(ops: list[dict]) -> list[dict]:
    """Les intentions du modele, au format lisible a la main des scenarios."""
    out = []
    for op in ops:
        kind = op.get("op")
        if kind == "supprimer":
            out.append({"op": "supprimer", "pos": _fmt(op["pos"])})
        elif kind == "poser":
            entry = {"op": "poser", "pos": _fmt(op["pos"]), "bloc": op["bloc"]}
            if op.get("props"):
                entry["props"] = dict(op["props"])
            out.append(entry)
        elif kind == "deplacer":
            out.append({"op": "deplacer", "de": _fmt(op["de"]),
                        "vers": _fmt(op["vers"])})
        elif kind == "propriete":
            out.append({"op": "propriete", "pos": _fmt(op["pos"]),
                        "cle": op["cle"], "valeur": op["valeur"]})
        else:
            raise ValueError("intention non rejouable : %r" % (op,))
    return out


def apply_ops(model: VehicleModel, ops: list[dict]) -> None:
    """Rejoue des intentions sur un modele fraichement charge."""
    for op in ops:
        kind = op.get("op")
        if kind == "supprimer":
            model.delete(_pos(op["pos"]))
        elif kind == "poser":
            model.add(_pos(op["pos"]), op["bloc"], op.get("props"))
        elif kind == "deplacer":
            model.move(_pos(op["de"]), _pos(op["vers"]))
        elif kind == "propriete":
            model.set_property(_pos(op["pos"]), op["cle"], op["valeur"])
        else:
            raise ValueError("intention inconnue : %r" % (op,))


# ---------------------------------------------------------------------------
# Export (F6.7)
# ---------------------------------------------------------------------------
def variant_filename(source: str, label: str = "variante",
                     when: float | None = None) -> str:
    """`<source>--<variante>--<AAAAMMJJ-HHMMSS>.nbt`, a cote du fichier source.

    Nomme et horodate, comme le demande le cahier : deux exports ne se
    remplacent jamais, et on retrouve d'un coup d'oeil de quel vaisseau et de
    quel essai ils viennent.
    """
    source = Path(source)
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "variante"
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(when))
    return str(source.with_name("%s--%s--%s.nbt" % (source.stem, slug, stamp)))


def export_variant(model: VehicleModel, path: str | None = None,
                   label: str = "variante") -> str:
    """Ecrit la variante courante dans un fichier nouveau et renvoie son chemin.

    Le fichier source n'est jamais ecrit, et aucun fichier existant n'est
    remplace : `Structure.export` refuse les deux.
    """
    target = path or variant_filename(model.structure.path, label)
    return model.structure.export(target)
