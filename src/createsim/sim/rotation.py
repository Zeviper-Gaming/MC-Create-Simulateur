"""Tangage et roulis : l'attitude du vaisseau, par les couples (F2.3, lot L6).

Jusqu'ici le simulateur avait trois degres de liberte en translation et
affichait le desequilibre STATIQUE — l'ecart entre centre de portance et centre
de masse, et le couple qui en resulte a l'instant zero. Cela repondait a « ca
pique du nez ? » sans simuler la rotation. Ici, le vaisseau tourne vraiment.

Trois pieces :

    le tenseur d'inertie   tire de la geometrie, au centre de masse
    l'amortissement        une enveloppe qui tourne balaie l'air, et le couple
                           resistant a la meme forme qu'un tenseur d'inertie,
                           pondere par la trainee au lieu de la masse
    l'integration          implicite sur l'amortissement, donc stable quel que
                           soit le pas ; un schema explicite fait diverger un
                           vaisseau tres amorti

L'orientation vit dans un quaternion, pas dans trois angles : les angles
d'Euler se bloquent a la verticale (blocage de cardan), et un vaisseau qui
pique du nez a 90 degres est exactement le cas qu'on veut pouvoir regarder.

LIMITE ASSUMEE. Seul l'amortissement est implicite ; le terme gyroscopique
reste explicite, et les equations d'Euler integrees ainsi gagnent lentement de
l'energie. Sur un corps dissymetrique lance a plusieurs tours par seconde et
sans AUCUN amortissement, la vitesse angulaire finit par diverger — quelques
minutes de simulation. Le cas ne se produit pas : `universal_drag` s'applique a
tout vaisseau, et le taux de 0,09 par seconde suffit a eteindre une rotation
libre bien avant. Le garde-fou de `step` arrete la rotation plutot que de
laisser une valeur non finie corrompre l'assiette.
"""
from __future__ import annotations

import math

import numpy as np

#: quaternion neutre, (w, x, y, z)
IDENTITY = (1.0, 0.0, 0.0, 0.0)


def normalise(q) -> tuple[float, float, float, float]:
    n = math.sqrt(sum(c * c for c in q))
    if n < 1e-12:
        return IDENTITY
    return tuple(c / n for c in q)


def matrix(q) -> np.ndarray:
    """La matrice de rotation d'un quaternion (w, x, y, z)."""
    w, x, y, z = normalise(q)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ], dtype=float)


def advance(q, omega, dt: float):
    """Fait tourner `q` de la vitesse angulaire `omega` pendant `dt`.

    La derivee d'un quaternion vaut q' = 1/2 . w . q, avec w le quaternion pur
    de la vitesse angulaire. On renormalise a chaque pas : sans cela l'erreur
    d'integration l'etire, et la rotation se met a etirer le vaisseau avec.
    """
    w, x, y, z = q
    ox, oy, oz = omega
    dw = 0.5 * (-ox * x - oy * y - oz * z)
    dx = 0.5 * (ox * w + oy * z - oz * y)
    dy = 0.5 * (-ox * z + oy * w + oz * x)
    dz = 0.5 * (ox * y - oy * x + oz * w)
    return normalise((w + dw * dt, x + dx * dt, y + dy * dt, z + dz * dt))


def second_moment(products, total: float, centre) -> np.ndarray:
    """Le tenseur `somme w (|d|^2 E - d x d)` ramene a `centre`.

    `products` sont les sommes de w.r_i.r_j prises a l'origine, dans l'ordre
    xx, yy, zz, xy, xz, yz ; `total` la somme des poids. C'est la forme que
    prennent aussi bien l'inertie (poids = masse) que l'amortissement angulaire
    (poids = trainee par case).
    """
    xx, yy, zz, xy, xz, yz = products
    trace = xx + yy + zz
    tensor = np.array([[trace - xx, -xy, -xz],
                       [-xy, trace - yy, -yz],
                       [-xz, -yz, trace - zz]], dtype=float)
    if total > 0:
        c = np.asarray(centre, dtype=float)
        tensor -= total * (float(c @ c) * np.eye(3) - np.outer(c, c))
    return tensor


def angular_damping(drag_organ, pressure: float, com) -> np.ndarray:
    """Le tenseur d'amortissement angulaire de l'enveloppe, au centre de masse.

    Chaque case etanche a la vitesse `omega x d` voit une force `-k.v` : le
    couple qu'elle rend vaut `-k (|d|^2 omega - d (d.omega))`. Somme sur les
    cases, c'est un tenseur — celui-la meme que Sable construit a coups de
    produits exterieurs dans `applyFriction`.

    Seule l'enveloppe est comptee. Voiles, levitite et roues ont aussi un bras,
    mais leur amortissement est anisotrope dans le repere du vaisseau et leur
    contribution est marginale devant celle de l'enveloppe : c'est une
    simplification, et elle est signalee comme telle.
    """
    products = getattr(drag_organ, "products", None)
    if not products or not drag_organ.cells:
        return np.zeros((3, 3))
    scale = drag_organ.tables.get("forces.drag_floating_scale") * pressure
    return scale * second_moment(products, float(len(drag_organ.cells)), com)


def step(orientation, omega, inertia_body: np.ndarray, torque,
         damping_body: np.ndarray, dt: float):
    """Un pas de rotation. Renvoie (orientation, omega) dans le repere du monde.

    Le couple gyroscopique `omega x (I omega)` est celui qui fait precesser un
    vaisseau dont les axes principaux ne sont pas alignes — l'omettre donne une
    rotation qui a l'air juste et ne l'est pas.

    L'amortissement est traite IMPLICITEMENT : on resout
    `(I + D dt) omega' = I omega + (couple - gyroscopique) dt`. Un schema
    explicite ferait osciller puis diverger une enveloppe tres amortie, ou
    `D dt / I` depasse 1 — exactement le cas du c1_air_cruiser.
    """
    rotation = matrix(orientation)
    inertia = rotation @ inertia_body @ rotation.T
    damping = rotation @ damping_body @ rotation.T
    omega = np.asarray(omega, dtype=float)
    torque = np.asarray(torque, dtype=float)

    # Le debordement est PREVU (voir la limite en tete de module) et c'est le
    # test de finitude, plus bas, qui tranche. Laisser numpy avertir noierait
    # la console sous des RuntimeWarning pour un cas deja traite.
    with np.errstate(over="ignore", invalid="ignore"):
        gyroscopic = np.cross(omega, inertia @ omega)
        right = inertia @ omega + (torque - gyroscopic) * dt
        left = inertia + damping * dt
        try:
            new_omega = np.linalg.solve(left, right)
        except np.linalg.LinAlgError:      # vaisseau vide : rien a tourner
            return orientation, (0.0, 0.0, 0.0)
    if not np.all(np.isfinite(new_omega)):
        return orientation, (0.0, 0.0, 0.0)
    return advance(orientation, new_omega, dt), tuple(float(v) for v in new_omega)


def euler(q) -> tuple[float, float, float]:
    """(tangage, roulis, lacet) en degres, pour l'affichage.

    Convention : tangage autour de x, roulis autour de z, lacet autour de y —
    celle que l'utilisateur lit sur un vaisseau pose a plat.
    """
    w, x, y, z = normalise(q)
    sin_pitch = 2.0 * (w * x + y * z)
    sin_pitch = max(-1.0, min(1.0, sin_pitch))
    pitch = math.asin(sin_pitch)
    roll = math.atan2(2.0 * (w * z - x * y), 1.0 - 2.0 * (x * x + z * z))
    yaw = math.atan2(2.0 * (w * y - x * z), 1.0 - 2.0 * (x * x + y * y))
    return (math.degrees(pitch), math.degrees(roll), math.degrees(yaw))
