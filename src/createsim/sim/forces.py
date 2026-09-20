"""Les producteurs de force, et la dynamique des ballons.

Chaque producteur renvoie un VECTEUR et son POINT D'APPLICATION, jamais un
scalaire : c'est ce que la fenetre 3D affichera sans rien recalculer, et c'est
ce qui permet de voir le bras de levier qui fait piquer du nez.

Convention d'unites, heritee du calculateur statique et verifiee contre lui :
  - les vitesses sont en blocs par seconde ;
  - l'equation integree est m.dv/dn = somme(F), ou n compte les TICKS ;
  - d'ou v_max = poussee / k et tau = m / k en ticks (soit m/(20k) secondes).
La portance est exprimee en equivalent masse (kg souleves) et convertie en force
par la gravite, comme le fait le bilan du mod : un vaisseau vole si sa portance
depasse sa masse.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..data.nbt import Pos

Vec = tuple[float, float, float]

FACING_VEC: dict[str, Vec] = {
    "east": (1.0, 0.0, 0.0), "west": (-1.0, 0.0, 0.0),
    "up": (0.0, 1.0, 0.0), "down": (0.0, -1.0, 0.0),
    "south": (0.0, 0.0, 1.0), "north": (0.0, 0.0, -1.0),
}

FAMILIES = ("gravite", "ballon", "levitite", "helice", "roue", "trainee")


@dataclass(frozen=True)
class Force:
    """Une force, son point d'application, et de quoi l'etiqueter a l'ecran."""

    family: str
    vector: Vec
    point: Vec
    label: str
    source: Pos | None = None

    @property
    def magnitude(self) -> float:
        return math.sqrt(sum(c * c for c in self.vector))

    @property
    def key(self) -> str:
        """Identite stable d'une force, d'un tick a l'autre et d'un run a l'autre.

        Le separateur est un point et non une virgule : la clef devient un nom
        de colonne CSV, et une virgule forcerait le guillemetage de tout
        l'en-tete — le fichier doit rester lisible a la main.
        """
        if self.source is None:
            return self.family
        return "%s@%d.%d.%d" % ((self.family,) + tuple(self.source))

    def report(self) -> dict:
        return {"famille": self.family, "libelle": self.label,
                "vecteur": [round(c, 3) for c in self.vector],
                "intensite": round(self.magnitude, 2),
                "point": [round(c, 2) for c in self.point],
                "origine": list(self.source) if self.source else None}


# ---------------------------------------------------------------------------
# Dynamique du gaz : ServerBalloon.updateGasAmounts()
# ---------------------------------------------------------------------------
def gas_nudge(quantity: float, target: float, capacity: float, tables) -> float:
    """Un pas de remplissage ou de vidange, sur un tick.

    Un ballon ne repond pas instantanement : c'est ce qui rend un dirigeable
    delicat a piloter, et la principale raison d'etre d'un simulateur temps reel
    plutot que d'un calcul statique.

        scale = min(capacite / cible, 1)        le surplus est perdu
        diff  = cible x scale - quantite
        x     = diff / (0,05 x capacite)
        nudge = diff / 180 x (1 + 5 / (1 + 3x^2))
    """
    if capacity <= 0:
        return 0.0
    scale = min(capacity / target, 1.0) if target > 0 else 0.0
    diff = target * scale - quantity
    if abs(diff) < 1e-12:
        return 0.0
    span = (tables.get("forces.gas_filling_time") if diff > 0
            else tables.get("forces.gas_emptying_time"))
    factor = tables.get("forces.gas_responsiveness_factor")
    window = tables.get("forces.gas_responsiveness_range")
    x = diff / (window * capacity)
    return (diff / span) * (1.0 + factor / (1.0 + 3.0 * x * x))


def step_gas(quantities: list[float], pockets, signals, tables) -> list[float]:
    """Avance le remplissage de chaque poche d'un tick."""
    out: list[float] = []
    for q, pocket in zip(quantities, pockets):
        cap = float(pocket.capacity)
        target = pocket.demand(signals)
        nq = q + gas_nudge(q, target, cap, tables)
        out.append(max(0.0, min(nq, cap)))
    return out


# ---------------------------------------------------------------------------
# Producteurs
# ---------------------------------------------------------------------------
def gravity(mass: float, com: Vec, tables) -> Force:
    g = tables.get("pressure.gravity")
    return Force("gravite", (0.0, -mass * g, 0.0), com, "poids")


def balloon_forces(pockets, quantities: list[float], pressure: float,
                   tables) -> list[Force]:
    lift = tables.get("forces.hot_air_strength")
    g = tables.get("pressure.gravity")
    out: list[Force] = []
    for i, (pocket, q) in enumerate(zip(pockets, quantities)):
        mass_lifted = q * lift * pressure
        out.append(Force("ballon", (0.0, mass_lifted * g, 0.0), pocket.centre,
                         "poche %d : %.0f m3" % (i + 1, q)))
    return out


def levitite_force(organ, total_mass: float, tables) -> Force | None:
    if not organ.cells:
        return None
    g = tables.get("pressure.gravity")
    lift = organ.effective_lift(total_mass)
    label = "levitite x%d" % len(organ.cells)
    if organ.raw_lift > total_mass:
        label += " (plafonnee a la flottaison neutre)"
    return Force("levitite", (0.0, lift * g, 0.0), organ.centre, label)


def propeller_forces(bearings, speeds: dict[Pos, float], tables) -> list[Force]:
    """Poussee = voiles^1,5 x RPM x 0,2, appliquee au palier, selon son axe.

    Le sens suit l'orientation du palier et le signe du regime. C'est une
    convention : seule une mesure en jeu peut la trancher definitivement.
    """
    coef = tables.get("forces.propeller_bearing_thrust")
    exponent = tables.get("forces.propeller_sail_exponent")
    out: list[Force] = []
    for b in bearings:
        rpm = speeds.get(b.pos, 0.0)
        vec = FACING_VEC.get(b.facing)
        if vec is None:
            continue
        # Une helice a l'arret produit une force NULLE, pas une force absente :
        # sans cela la liste change d'un tick a l'autre, et une trace cesse
        # d'etre rejouable.
        magnitude = ((b.sails ** exponent) * abs(rpm) * coef
                     if rpm and b.sails else 0.0)
        sign = math.copysign(1.0, rpm) if rpm else 1.0
        point = (b.pos[0] + 0.5, b.pos[1] + 0.5, b.pos[2] + 0.5)
        label = "helice %d voiles a %.0f tr/min" % (b.sails, abs(rpm))
        if not b.reliable:
            label += " (comptage incertain)"
        out.append(Force("helice",
                         tuple(c * magnitude * sign for c in vec),
                         point, label, b.pos))
    return out


def wheel_forces(structure, props, speeds: dict[Pos, float], signals,
                 friction: float, tables, on_ground: bool = True) -> list[Force]:
    """Traction = RPM x (1 - frein) x friction x 1,75, au contact du sol.

    Hors contact, la roue est toujours la mais ne pousse pas : sa force vaut
    zero, elle ne disparait pas de la liste.
    """
    coef = tables.get("forces.wheel_traction_coef")
    brake_base = tables.get("forces.wheel_brake_base")
    brake_step = tables.get("forces.wheel_brake_per_signal")
    out: list[Force] = []
    for name in tables.get("forces.wheel_mount_blocks"):
        for pos in sorted(structure.positions_of(name)):
            block = structure.blocks[pos]
            rpm = speeds.get(pos, 0.0)
            nbt = block.get("nbt") or {}
            signal = int(signals.get(pos, nbt.get("SignalStrength", 0) or 0))
            brake = min(1.0, brake_base + (signal / 15.0) * brake_step)
            surface = min(friction, 1.0) if on_ground else 0.0
            magnitude = abs(rpm) * (1.0 - brake) * surface * coef
            vec = FACING_VEC.get(block["props"].get("facing"), (0.0, 0.0, 1.0))
            sign = math.copysign(1.0, rpm) if rpm else 1.0
            point = (pos[0] + 0.5, pos[1] + 0.5, pos[2] + 0.5)
            out.append(Force("roue", tuple(c * magnitude * sign for c in vec),
                             point, "roue a %.0f tr/min, frein %.0f%%"
                             % (abs(rpm), brake * 100), pos))
    return out


def drag_force(drag_organ, velocity: Vec, pressure: float, tables) -> Force:
    """Trainee lineaire F = -k.v, k = 0,33 x N_etanches x pression."""
    k = drag_organ.coefficient(pressure)
    return Force("trainee", tuple(-k * v for v in velocity), drag_organ.centre,
                 "k = %.1f sur %d blocs etanches" % (k, drag_organ.count))


# ---------------------------------------------------------------------------
# Sommes
# ---------------------------------------------------------------------------
def resultant(forces: list[Force]) -> Vec:
    fx = fy = fz = 0.0
    for f in forces:
        fx += f.vector[0]
        fy += f.vector[1]
        fz += f.vector[2]
    return (fx, fy, fz)


def torque_about(forces: list[Force], pivot: Vec,
                 skip: tuple[str, ...] = ("gravite",)) -> Vec:
    """Couple net autour du centre de masse. Le poids s'y applique, donc ne
    produit aucun moment : on l'ecarte de la somme."""
    tx = ty = tz = 0.0
    for f in forces:
        if f.family in skip:
            continue
        rx = f.point[0] - pivot[0]
        ry = f.point[1] - pivot[1]
        rz = f.point[2] - pivot[2]
        fx, fy, fz = f.vector
        tx += ry * fz - rz * fy
        ty += rz * fx - rx * fz
        tz += rx * fy - ry * fx
    return (tx, ty, tz)


def lift_centre(forces: list[Force]) -> Vec | None:
    """Centre de portance : barycentre des forces vers le haut, pondere.

    C'est le point que le cahier demande de materialiser face au centre de
    masse (F3.9) : l'ecart entre les deux est le bras de levier, et c'est lui
    qui explique pourquoi un vaisseau pique du nez.
    """
    total = sum(f.vector[1] for f in forces if f.vector[1] > 0.0)
    if total <= 0.0:
        return None
    return tuple(
        sum(f.vector[1] * f.point[i] for f in forces if f.vector[1] > 0.0) / total
        for i in range(3))


def longitudinal_axis(size) -> int:
    """L'axe le plus long dans le plan horizontal : la longueur du vehicule.

    Sans cela le tangage et le roulis se confondent. Le calculateur statique
    supposait l'axe x, or `cargo_airship` mesure 34 x 38 x 67 et `c1_air_cruiser`
    31 x 37 x 176 : leur longueur est en z, et c'est un ecart de portance le
    long de CETTE direction qui fait piquer du nez.
    """
    return 0 if float(size[0]) >= float(size[2]) else 2


def pitch_balance(mass: float, com: Vec, lift_forces: list[Force], tables,
                  longitudinal: int = 2) -> dict | None:
    """Desequilibre STATIQUE : ecart entre centre de portance et centre de masse.

    Repond deja a « ca pique du nez ? » sans simuler la rotation. Le tangage
    complet, avec le tenseur d'inertie, est un lot ulterieur.
    """
    lifting = [f for f in lift_forces if f.vector[1] > 0]
    total = sum(f.vector[1] for f in lifting)
    if total <= 0:
        return None
    centre = [sum(f.vector[1] * f.point[i] for f in lifting) / total
              for i in range(3)]
    lateral = 2 if longitudinal == 0 else 0
    arm = centre[longitudinal] - com[longitudinal]
    return {
        "axe_longitudinal": "xyz"[longitudinal],
        "centre_de_portance": [round(v, 2) for v in centre],
        "bras_longitudinal": round(arm, 2),
        "bras_lateral": round(centre[lateral] - com[lateral], 2),
        "couple_longitudinal": round(arm * total, 1),
        "sens": "cabre" if arm > 0.01 else ("pique" if arm < -0.01 else "neutre"),
    }
