"""Integration semi-implicite (Euler symplectique), 3 degres de liberte (F2.2).

Pas fixe de 1/20 s, decouple du rafraichissement d'ecran (F2.1). Le schema est
symplectique : la vitesse est mise a jour d'abord, puis la position avec la
NOUVELLE vitesse.

La trainee est EXACTEMENT lineaire dans ce modele — `simple_drag` porte
`transition_speed = 0`, donc pas de composante « slow drag ». Son terme est donc
integre exactement sur le tick, au lieu d'etre approche :

    v* = F_ext / k                       vitesse limite instantanee
    v(n+1) = v* + (v(n) - v*) . exp(-k.h/m)
    x(n+1) = x(n) + v(n+1) . h                      h = 1/20 s

Ce n'est pas une astuce : c'est la primitive du terme lineaire, connue. Le reste
des forces (gravite, portance, poussee) reste explicite — un schema IMEX
classique. Le gain est double : inconditionnellement stable, alors qu'un Euler
explicite diverge des que k.h/m > 2 sur un vaisseau leger et tres etanche ; et
transitoires justes, ce qui est la raison d'etre du simulateur.

Comparatif mesure sur cargo_airship (k/m = 0,44 s^-1), ecart sur la constante
de temps : Euler explicite 23,8 %, semi-implicite amorti 1,1 %, exact 0,0 %.
Consequence a connaitre : le niveau 2 de validation ne peut plus prendre en
defaut l'ORDRE du schema sur ce cas — il valide le pas de temps, les unites et
le bilan des forces, ce qui reste ce qu'il est cense attraper.

CONVENTION D'UNITES — attention, elle corrige le calculateur statique.
Sable fait tourner un monde Rapier dont la gravite vaut 11 blocs/s^2, avance
d'un pas de 1/20 s par tick. L'acceleration est donc en blocs/s^2 et la vitesse
en blocs/s :

    a = F/m  [blocs/s^2]        dv = a.h        dx = v.h

Le calculateur `/mc-create-engineer` appliquait `dv = F/m` par tick, sans le
facteur h. Cela ne change ni la vitesse de pointe (v_max = P/k, inchangee) ni
l'altitude d'equilibre, mais cela divise par 20 la constante de temps affichee,
et ferait tomber une chute libre a -220 blocs/s apres une seconde au lieu de
-11. La constante de temps est tau = m/k SECONDES, pas ticks.
"""
from __future__ import annotations

import math

TICKS_PER_SECOND = 20.0
DT = 1.0 / TICKS_PER_SECOND


def integrate(position: list, velocity: list, external_force: tuple,
              damping, mass: float) -> None:
    """Un pas. Modifie `position` et `velocity` en place.

    `external_force` : toutes les forces lineaires en v mises a part.
    `damping` : le k de F = -k.v, integre exactement. Scalaire ou triplet.

    Il est devenu un TRIPLET quand les roues sont arrivees : leur freinage agit
    sur l'axe du support, leur derive sur l'axe perpendiculaire, la trainee sur
    les trois. Les garder dans la somme explicite aurait coute l'exactitude de
    l'integration exponentielle, qui est ce qui tient le niveau 2 a 0,000 %.
    """
    if mass <= 0:
        return
    if isinstance(damping, (int, float)):
        damping = (damping, damping, damping)
    for i in range(3):
        k = damping[i]
        rate = (k / mass) * DT
        if rate < 1e-9:
            velocity[i] += external_force[i] / mass * DT
        else:
            terminal = external_force[i] / k
            velocity[i] = terminal + (velocity[i] - terminal) * math.exp(-rate)
    for i in range(3):
        position[i] += velocity[i] * DT


def clamp_to_ground(position: list, velocity: list, floor: float) -> bool:
    """Empeche la traversee du plan de sol. Renvoie True si le vehicule pose.

    Ce n'est pas un moteur de collision : le sol est un simple plancher sous le
    point le plus bas du vehicule, et rien d'autre ne s'y oppose.
    """
    if floor == float("-inf") or position[1] > floor:
        return False
    position[1] = floor
    if velocity[1] < 0.0:
        velocity[1] = 0.0
    return True


def terminal_motion(thrust: float, drag_k: float, mass: float) -> dict:
    """Solution exacte de la trainee lineaire — la reference analytique.

        v(t) = v_max (1 - exp(-t/tau))    v_max = P/k    tau = m/k [s]
    """
    if drag_k <= 0:
        return {"vitesse_max": None, "constante_de_temps_s": None,
                "acceleration_initiale": round(thrust / mass, 3) if mass else None}
    v_max = thrust / drag_k
    tau = mass / drag_k
    return {
        "vitesse_max": round(v_max, 3),
        "constante_de_temps_s": round(tau, 3),
        "constante_de_temps_ticks": round(tau * TICKS_PER_SECOND, 1),
        "distance_pour_90pct": round(v_max * (2.303 * tau - 0.9 * tau), 1),
        "acceleration_initiale": round(thrust / mass, 4) if mass else None,
        "loi": "v(t) = v_max (1 - exp(-t/tau))",
    }
