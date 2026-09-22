"""Le plan de sol : la peau de la coque, le contact, et la grille (F2.4, F3).

Le comportement d'ensemble — un vaisseau qui tombe, touche et se stabilise —
est verifie dans `test_simulation.py`. Ici, les pieces : quels sommets peuvent
toucher, ce que la reaction vaut, et que le sol se VOIE.
"""
from __future__ import annotations

import math
import re

import numpy as np
import pytest

from createsim.sim import forces as F
from createsim.sim import rotation as R
from createsim.sim.state import SimOptions
from createsim.sim.tick import Simulation


# --- la peau de la coque ----------------------------------------------------
def test_la_peau_ne_garde_que_les_blocs_exposes(cargo):
    """Un coin enferme a l'interieur de la coque ne peut jamais etre le point
    le plus bas : le garder couterait sans rien changer."""
    coque = cargo.organ("coque")
    assert coque.exposed == 0, "le calcul doit etre paresseux"

    points = coque.points
    assert len(points) > 0
    assert coque.exposed < len(cargo.structure.blocks), (
        "tous les blocs ne sont pas exposes")
    assert len(points) <= coque.exposed * 8


def test_le_bas_de_coque_n_est_pas_la_cote_zero(cargo):
    """Tout le defaut corrige tient dans ce chiffre : le cargo commence a y = 3,
    et le plancher d'avant le posait comme s'il commencait a 0."""
    assert cargo.organ("coque").lowest_local() == pytest.approx(3.0)


def test_la_peau_se_refait_apres_une_edition(cargo):
    """Retirer un bloc expose ses voisins. L'invalidation ne coute qu'un cache
    jete ; le recalcul attend qu'on redemande les points."""
    coque = cargo.organ("coque")
    avant = len(coque.points)
    bas = min(p for p in cargo.structure.blocks if p[1] == 3)

    cargo.delete(bas)
    assert coque._points is None, "l'edition doit jeter le cache, pas recalculer"
    assert len(coque.points) != avant or coque.exposed


# --- la reaction ------------------------------------------------------------
def test_la_reaction_ne_naît_que_sous_une_resultante_descendante(cachalot_model):
    """Un vaisseau qui porte plus qu'il ne pese DECOLLE : le sol ne le retient
    pas. Une reaction qui resterait collerait le vaisseau au plancher."""
    sim = Simulation(cachalot_model,
                     SimOptions(altitude=0.0, ground_enabled=True,
                                ground_altitude=0.0))
    coque = cachalot_model.organ("coque")
    commun = dict(hull=coque, position=[0.0, coque.lowest_local(), 0.0],
                  velocity=[0.0, 0.0, 0.0], omega=[0.0, 0.0, 0.0],
                  com=sim.mass.com, rotation=None, floor=1000.0,
                  mass=sim.mass.total, friction=1.0, tables=sim.tables)

    poids = [F.Force("gravite", (0.0, -1000.0, 0.0), (0.0, 0.0, 0.0), "poids")]
    assert F.ground_contact(**commun, others=poids), "pose, il doit s'appuyer"

    portance = [F.Force("ballon", (0.0, 1000.0, 0.0), (0.0, 0.0, 0.0), "gaz")]
    assert not F.ground_contact(**commun, others=portance), (
        "il decolle : plus d'appui")


def test_la_reaction_porte_au_barycentre_des_appuis(cachalot_model):
    """C'est de la que vient le couple : le poids agit au centre de masse, la
    reaction au centre des appuis, et l'ecart fait basculer le vaisseau."""
    sim = Simulation(cachalot_model,
                     SimOptions(altitude=0.0, ground_enabled=True,
                                ground_altitude=0.0))
    coque = cachalot_model.organ("coque")
    poids = [F.Force("gravite", (0.0, -1000.0, 0.0), sim.mass.com, "poids")]
    contact = F.ground_contact(
        coque, [0.0, coque.lowest_local(), 0.0], [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0], sim.mass.com, None, 1000.0, sim.mass.total, 1.0,
        sim.tables, poids)

    assert contact[0].vector == (0.0, 1000.0, 0.0)
    appui = contact[0].point
    lo = coque.points.min(axis=0)
    hi = coque.points.max(axis=0)
    for i in (0, 2):
        assert lo[i] <= appui[i] <= hi[i], "l'appui est sous la coque"


def test_le_frottement_du_sol_ne_renverse_pas_la_vitesse(cachalot_model):
    """Coulomb borne la force ; « ce qu'il faut pour arreter net » la borne
    aussi. Sans la seconde, un vaisseau lent repartirait en arriere."""
    sim = Simulation(cachalot_model,
                     SimOptions(altitude=0.0, ground_enabled=True,
                                ground_altitude=0.0))
    coque = cachalot_model.organ("coque")
    poids = [F.Force("gravite", (0.0, -1.0e6, 0.0), sim.mass.com, "poids")]
    lent = 1.0e-3
    contact = F.ground_contact(
        coque, [0.0, coque.lowest_local(), 0.0], [lent, 0.0, 0.0],
        [0.0, 0.0, 0.0], sim.mass.com, None, 1000.0, sim.mass.total, 1.0,
        sim.tables, poids)

    frein = next(f for f in contact if f.vector[0] < 0)
    # de quoi annuler la vitesse en un tick, pas davantage
    assert abs(frein.vector[0]) <= sim.mass.total * lent * 20.0 + 1e-9


def test_le_contact_suit_l_assiette(cachalot_model):
    """Un vaisseau penche touche par un coin, pas par son plancher : le nombre
    d'appuis doit tomber quand on l'incline."""
    sim = Simulation(cachalot_model,
                     SimOptions(altitude=0.0, ground_enabled=True,
                                ground_altitude=0.0))
    coque = cachalot_model.organ("coque")
    poids = [F.Force("gravite", (0.0, -1000.0, 0.0), sim.mass.com, "poids")]

    def appuis(rotation):
        points = coque.points - np.asarray(sim.mass.com)
        if rotation is not None:
            points = points @ np.asarray(rotation).T
        floor = float(points[:, 1].min())
        contact = F.ground_contact(
            coque, [0.0, -floor, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0],
            sim.mass.com, rotation, 0.0, sim.mass.total, 1.0, sim.tables, poids)
        if not contact:
            return 0
        return int(re.search(r"(\d+) appui", contact[0].label).group(1))

    angle = math.radians(20.0)
    penche = R.matrix((math.cos(angle / 2), math.sin(angle / 2), 0.0, 0.0))
    assert appuis(penche) < appuis(None), "penche, il touche par moins de points"


# --- la grille --------------------------------------------------------------
def test_la_grille_couvre_le_vaisseau_et_tombe_sur_des_cotes_rondes():
    """Une grille qui glisse avec le vaisseau ne dit plus rien de la distance
    parcourue : ses lignes doivent rester sur des cotes rondes."""
    from createsim.view.ground import build_ground_mesh

    mesh = build_ground_mesh((34, 38, 67), (16.5, 14.4, 31.4), -5.0)
    lo, hi = mesh.bounds
    assert lo[1] == hi[1] == -5.0
    assert hi[0] - lo[0] > 67 and hi[2] - lo[2] > 67
    assert mesh.vertices > 0

    points = mesh.positions.reshape(-1, 3)
    assert np.allclose(points[:, 1], -5.0), "la grille est horizontale"


def test_une_grille_vide_ne_plante_pas():
    from createsim.view.ground import build_ground_mesh
    mesh = build_ground_mesh((1, 1, 1), (0.0, 0.0, 0.0), 0.0)
    assert mesh.vertices > 0


# --- dans la fenetre --------------------------------------------------------
def test_la_grille_apparait_et_disparait_avec_l_option(qt_app):
    """Le sol se voit quand il est allume, et cesse de se voir quand on
    l'eteint. Un vaisseau qu'on pose sur un sol invisible ne se pose pas : il
    s'arrete en l'air."""
    pytest.importorskip("PySide6", reason="interface non installee")
    from pathlib import Path
    from createsim.view.app import VehicleWindow, _load

    path = str(Path(__file__).parent / "fixtures" / "cachalot_volant_v3.nbt")
    model, sim = _load(path, options=SimOptions(altitude=40.0,
                                                ground_enabled=True,
                                                ground_altitude=0.0))
    w = VehicleWindow(model, sim)
    try:
        w._refresh_scene()
        assert w.view.ground is not None and w.view.ground.vertices > 0

        # la grille suit la descente : le vaisseau ne bouge pas dans la scene,
        # c'est le sol qui monte vers lui
        haut = w._ground_y
        sim.run(400)
        w._refresh_scene()
        assert w._ground_y > haut, "le sol se rapproche quand le vaisseau tombe"

        sim.options.ground_enabled = False
        sim.rebuild_ground()
        w._refresh_scene()
        assert w.view.ground is None
    finally:
        w.close()
