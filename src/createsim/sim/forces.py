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

    Le sens suit l'orientation du palier et le signe du regime. Mesure en jeu
    (`data/mesures/jeu.json`) : les helices poussent bien le vaisseau vers
    l'avant, la convention n'est donc pas a renverser. Reste a lever sur quelle
    extremite de coque « l'avant » tombe pour le cachalot.
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


def fudge_friction(friction: float, tables) -> float:
    """`WheelMountBlockEntity.fudgeFriction` — et ce n'est PAS `min(f, 1)`.

        f < 1  ->  0,1 + 0,9 f        f >= 1  ->  f

    Consequence lue au bytecode : sur la glace (friction 0) le jeu laisse
    0,10 d'adherence, pas zero — un vehicule y avance encore. Et un frottement
    superieur a 1 passe inchange, ce qui compte pour la derive laterale.
    """
    if friction >= 1.0:
        return friction
    return (tables.get("forces.wheel_friction_fudge_offset")
            + tables.get("forces.wheel_friction_fudge_scale") * friction)


def wheel_grip(friction: float, tables) -> tuple[float, float]:
    """(adherence brute, adherence bornee) — l'asymetrie du moteur.

    Traction et freinage saturent a 1 ; la derive laterale utilise la valeur
    NON bornee. Sur sable des ames (1,65), un vehicule tient donc mieux en
    virage qu'il ne tracte.
    """
    grip = fudge_friction(friction, tables)
    return grip, min(grip, 1.0)


def wheel_brake(pos: Pos, nbt: dict, signals) -> float:
    """Le frein d'une roue : le signal redstone recu PAR AU-DESSUS, sur 15.

    `WheelMountBlockEntity.sable$physicsTick` offset 529 :
    `level.getSignal(pos.above(), UP) / 15.0`. C'est `frein` tel quel — le
    confondre avec le coefficient du freinage dynamique (0,075 + frein x 0,3)
    laissait une roue freinee a fond tracter encore a 62 %.
    """
    signal = int(signals.get(pos, (nbt or {}).get("SignalStrength", 0) or 0))
    return min(1.0, max(0.0, signal / 15.0))


def wheel_forces(structure, props, speeds: dict[Pos, float], signals,
                 friction: float, tables, on_ground: bool = True) -> list[Force]:
    """Traction = RPM x (1 - frein) x min(adherence, 1) x 1,75, au contact.

    Hors contact, la roue est toujours la mais ne pousse pas : sa force vaut
    zero, elle ne disparait pas de la liste.
    """
    coef = tables.get("forces.wheel_traction_coef")
    _grip, surface = wheel_grip(friction, tables)
    if not on_ground:
        surface = 0.0
    out: list[Force] = []
    for name in tables.get("forces.wheel_mount_blocks"):
        for pos in sorted(structure.positions_of(name)):
            block = structure.blocks[pos]
            rpm = speeds.get(pos, 0.0)
            brake = wheel_brake(pos, block.get("nbt"), signals)
            magnitude = abs(rpm) * (1.0 - brake) * surface * coef
            vec = FACING_VEC.get(block["props"].get("facing"), (0.0, 0.0, 1.0))
            sign = math.copysign(1.0, rpm) if rpm else 1.0
            point = (pos[0] + 0.5, pos[1] + 0.5, pos[2] + 0.5)
            out.append(Force("roue", tuple(c * magnitude * sign for c in vec),
                             point, "roue a %.0f tr/min, frein %.0f%%"
                             % (abs(rpm), brake * 100), pos))
    return out


def wheel_friction_forces(wheel_organ, velocity: Vec, signals, friction: float,
                          tables, on_ground: bool = True) -> list[Force]:
    """Freinage longitudinal et derive laterale — le frottement DYNAMIQUE.

    `WheelMountBlockEntity.sable$physicsTick`, offsets 555 a 669 :

        freinage = -v_long x (0,075 + frein x 0,3) x min(adherence,1) x strengthMul
        derive   = -v_lat  x 0,6                   x adherence        x strengthMul

    Le moteur multiplie l'ensemble par `dt` et l'applique en impulsion : les
    coefficients sont donc PAR SECONDE, et non par tick. C'est ce qui fixe la
    constante de temps a 0,67 s frein relache et 0,13 s frein a fond.

    Ces deux forces sont lineaires en v : elles entrent dans l'amortissement du
    schema, pas dans la somme explicite. Elles sont tout de meme publiees pour
    que la decomposition des forces les montre.
    """
    base = tables.get("forces.wheel_brake_base")
    step = tables.get("forces.wheel_brake_per_signal")
    lateral_coef = tables.get("forces.wheel_lateral_coef")
    grip, surface = wheel_grip(friction, tables)
    if not on_ground:
        grip = surface = 0.0

    out: list[Force] = []
    for wheel in wheel_organ.wheels:
        nbt = wheel_organ.s.blocks[wheel.pos].get("nbt")
        brake = wheel_brake(wheel.pos, nbt, signals)
        k_long = (base + brake * step) * surface * wheel.strength_mul
        k_lat = lateral_coef * grip * wheel.strength_mul
        point = (wheel.pos[0] + 0.5, wheel.pos[1] + 0.5, wheel.pos[2] + 0.5)

        vector = [0.0, 0.0, 0.0]
        vector[wheel.longitudinal_axis] = -k_long * velocity[wheel.longitudinal_axis]
        vector[wheel.lateral_axis] += -k_lat * velocity[wheel.lateral_axis]
        out.append(Force("frottement", tuple(vector), point,
                         "roue : freinage k=%.0f, derive k=%.0f" % (k_long, k_lat),
                         wheel.pos))
    return out


def wheel_damping(wheel_organ, signals, friction: float, tables,
                  on_ground: bool = True) -> list[float]:
    """L'amortissement par axe qu'ajoutent les roues.

    Anisotrope par nature : le freinage agit sur l'axe du support, la derive
    sur l'axe perpendiculaire, et rien sur la verticale.
    """
    damping = [0.0, 0.0, 0.0]
    if not on_ground:
        return damping
    base = tables.get("forces.wheel_brake_base")
    step = tables.get("forces.wheel_brake_per_signal")
    lateral_coef = tables.get("forces.wheel_lateral_coef")
    grip, surface = wheel_grip(friction, tables)
    for wheel in wheel_organ.wheels:
        nbt = wheel_organ.s.blocks[wheel.pos].get("nbt")
        brake = wheel_brake(wheel.pos, nbt, signals)
        damping[wheel.longitudinal_axis] += (
            (base + brake * step) * surface * wheel.strength_mul)
        damping[wheel.lateral_axis] += lateral_coef * grip * wheel.strength_mul
    return damping


def sail_forces(sail_organ, velocity: Vec, pressure: float, tables) -> list[Force]:
    """Portance des voiles de coque — le seul modele d'aile de l'ecosysteme.

    `BlockSubLevelLiftProvider.sable$contributeLiftAndDrag`, offsets 182-531 :

        n  = normale de la voile        v = vitesse du bloc      P = pression
        D∥ = n (n . v) C∥ P             D0 = v C0 P
        L  = n |v - D∥| CL P
        force -= D∥ + D0 + L

    Les deux trainees sont lineaires en v et rejoignent l'amortissement ; seule
    la portance est rendue ici, parce qu'elle est dirigee et non dissipative.

    Une simplification assumee : le moteur retranche a la vitesse un D∥ deja
    multiplie par son pas de temps, ce qui vaut environ 2 % — on garde |v|.
    """
    if not sail_organ.sails:
        return []
    lift_create = tables.get("forces.sail_lift_scalar")
    lift_sym = tables.get("forces.symmetric_sail_lift_scalar")
    speed = math.sqrt(sum(v * v for v in velocity))

    by_axis: dict[tuple[int, float], float] = {}
    for sail in sail_organ.sails:
        coef = lift_sym if sail.symmetric else lift_create
        if not coef:
            continue
        vec = sail.vector
        key = (sail.axis, math.copysign(1.0, vec[sail.axis]))
        by_axis[key] = by_axis.get(key, 0.0) + coef * speed * pressure

    out: list[Force] = []
    for (axis, sign), magnitude in sorted(by_axis.items()):
        vector = [0.0, 0.0, 0.0]
        vector[axis] = -sign * magnitude
        out.append(Force("portance_voile", tuple(vector), sail_organ.centre,
                         "voiles de coque, axe %s" % "xyz"[axis]))
    return out


def sail_damping(sail_organ, pressure: float, tables) -> list[float]:
    """Les deux trainees des voiles, par axe.

    La trainee parallele n'agit que selon la normale de la voile ; la trainee
    diffuse freine les trois axes.
    """
    damping = [0.0, 0.0, 0.0]
    if not sail_organ.sails:
        return damping
    c_parallel = tables.get("forces.sail_parallel_drag_scalar")
    c_sym = tables.get("forces.symmetric_sail_parallel_drag_scalar")
    c_diffuse = tables.get("forces.sail_directionless_drag_scalar")
    for sail in sail_organ.sails:
        damping[sail.axis] += (c_sym if sail.symmetric else c_parallel) * pressure
        for i in range(3):
            damping[i] += c_diffuse * pressure
    return damping


def levitite_damping(levitite_organ, velocity: Vec, tables) -> list[float]:
    """Le levitite freine, et beaucoup, a basse vitesse.

    `data/aeronautics/floating_materials/levitite.json` declare un profil
    complet que le simulateur ignorait entierement : vertical 2,0 lent /
    0,1 rapide, horizontal 1,5 / 0,05, transition a 3 blocs/s, et
    `scale_friction_with_gravity` — donc x 11.

    Le melange est ADDITIF, pas une interpolation : dans `applyFriction`, la
    matrice lente est mise a l'echelle du facteur gaussien tandis que la rapide
    garde la sienne. Le facteur se reduit, pour une grappe ponctuelle, a
    `exp(-1,5 (v / transition)^2)` — c'est la simplification assumee ici : le
    moteur y ajoute une correction d'etalement spatial de la grappe.
    """
    cells = getattr(levitite_organ, "cells", ())
    if not cells:
        return [0.0, 0.0, 0.0]
    transition = tables.get("forces.levitite_transition_speed")
    gravity = tables.get("pressure.gravity")
    speed = math.sqrt(sum(v * v for v in velocity))
    blend = math.exp(-1.5 * (speed / transition) ** 2) if transition else 0.0

    vertical = (tables.get("forces.levitite_slow_vertical_friction") * blend
                + tables.get("forces.levitite_fast_vertical_friction"))
    horizontal = (tables.get("forces.levitite_slow_horizontal_friction") * blend
                  + tables.get("forces.levitite_fast_horizontal_friction"))
    n = len(cells) * gravity
    return [horizontal * n, vertical * n, horizontal * n]


def drag_force(drag_organ, velocity: Vec, pressure: float, tables,
               mass: float = 0.0) -> Force:
    """Trainee lineaire F = -k.v.

    Deux termes qui n'ont pas la meme origine et qu'il faut pouvoir lire
    separement : l'enveloppe (0,33 par bloc etanche, x pression) et
    l'amortissement universel du moteur physique (un taux par seconde, donc
    x masse une fois ramene a un coefficient de force).
    """
    enveloppe = drag_organ.envelope_coefficient(pressure)
    universel = drag_organ.universal_coefficient(mass)
    k = enveloppe + universel
    return Force("trainee", tuple(-k * v for v in velocity), drag_organ.centre,
                 "k = %.0f (enveloppe %.0f sur %d blocs + universel %.0f)"
                 % (k, enveloppe, drag_organ.count, universel))


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
