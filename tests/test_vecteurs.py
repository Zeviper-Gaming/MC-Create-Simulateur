"""L'affichage des forces : geometrie, echelle, groupes, bras de levier.

Comme le maillage, tout se teste sans fenetre : ces fonctions ne produisent que
des tableaux de sommets.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from createsim.sim.forces import Force, lift_centre, longitudinal_axis, resultant
from createsim.view.vectors import (FORCE_COLORS, arc_arrow, arrow,
                                    build_force_overlay, octahedron)


def _force(family, vector, point, label="essai"):
    return Force(family=family, vector=vector, point=point, label=label)


# --- primitives -------------------------------------------------------------
def test_une_fleche_part_de_son_origine_et_atteint_sa_longueur():
    positions, _normals = arrow((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), 10.0, 0.5)
    ys = positions.reshape(-1, 3)[:, 1]
    assert ys.min() == pytest.approx(0.0, abs=1e-5)
    assert ys.max() == pytest.approx(10.0, abs=1e-5)


def test_une_fleche_suit_la_direction_demandee():
    for direction in ((1, 0, 0), (0, 0, -1), (0.6, 0.8, 0.0)):
        positions, _ = arrow((2.0, 3.0, 4.0), direction, 6.0, 0.3)
        points = positions.reshape(-1, 3) - np.array([2.0, 3.0, 4.0])
        unit = np.array(direction, float)
        unit /= np.linalg.norm(unit)
        # le point le plus avance doit etre a `longueur` le long de la direction
        assert (points @ unit).max() == pytest.approx(6.0, abs=1e-4)


def test_une_fleche_tres_courte_garde_une_pointe_visible():
    """Une force faible ne doit pas se reduire a un trait sans tete."""
    positions, _ = arrow((0, 0, 0), (0, 1, 0), 0.4, 0.5)
    assert len(positions) > 0
    assert positions.reshape(-1, 3)[:, 1].max() == pytest.approx(0.4, abs=1e-5)


def test_le_marqueur_est_centre_et_borne():
    positions, _ = octahedron((5.0, 6.0, 7.0), 0.5)
    points = positions.reshape(-1, 3)
    assert points.mean(axis=0) == pytest.approx([5.0, 6.0, 7.0], abs=1e-5)
    assert np.abs(points - np.array([5.0, 6.0, 7.0])).max() == pytest.approx(0.5)


def test_l_arc_de_couple_tourne_autour_de_son_axe():
    """Un couple autour de y doit rester dans le plan horizontal."""
    positions, _ = arc_arrow((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), 4.0, tube=0.2)
    ys = positions.reshape(-1, 3)[:, 1]
    assert np.abs(ys).max() < 0.75, "l'arc doit rester dans son plan"


def test_toutes_les_primitives_produisent_des_triangles():
    for positions, _ in (arrow((0, 0, 0), (0, 1, 0), 5.0, 0.4),
                         octahedron((0, 0, 0), 1.0),
                         arc_arrow((0, 0, 0), (1, 0, 0), 3.0)):
        assert len(positions) % 3 == 0
        assert positions.dtype == np.float32


# --- assemblage -------------------------------------------------------------
def test_l_echelle_rapporte_la_plus_grande_force_a_la_taille_du_vaisseau():
    """Deux vaisseaux de tailles differentes doivent se lire pareil."""
    forces = [_force("gravite", (0, -1000, 0), (0, 0, 0))]
    petit = build_force_overlay(forces, com=(0, 0, 0), span=20)
    grand = build_force_overlay(forces, com=(0, 0, 0), span=200)
    assert grand.reference == pytest.approx(petit.reference * 10)
    assert petit.scale * 1000 == pytest.approx(petit.reference)


def test_les_longueurs_restent_proportionnelles_aux_intensites():
    """C'est l'exigence F3.6 : comparer deux fleches a l'oeil doit avoir un sens."""
    forces = [_force("gravite", (0, -1000, 0), (0, 0, 0)),
              _force("ballon", (0, 500, 0), (0, 0, 0))]
    overlay = build_force_overlay(forces, com=(0, 0, 0), span=100)
    spans = {}
    for group, (first, count) in overlay.ranges.items():
        if group in ("centres", "resultante", "couple"):
            continue
        points = overlay.positions.reshape(-1, 3)[first:first + count]
        spans[group] = points[:, 1].max() - points[:, 1].min()
    assert spans["gravite"] == pytest.approx(2 * spans["ballon"], rel=1e-3)


def test_une_force_negligeable_n_est_pas_dessinee_mais_reste_annoncee():
    forces = [_force("gravite", (0, -1000, 0), (0, 0, 0)),
              _force("trainee", (0, 0, 0.0001), (0, 0, 0))]
    overlay = build_force_overlay(forces, com=(0, 0, 0), span=50)
    trainee = next(e for e in overlay.legend if e["groupe"] == "trainee")
    assert trainee["dessinees"] == 0
    assert trainee["negligeable"] == 1
    assert "trainee" not in overlay.ranges


def test_chaque_groupe_est_filtrable_separement():
    """F3.10 : le filtre d'affichage par famille de force."""
    forces = [_force("gravite", (0, -1000, 0), (0, 0, 0)),
              _force("ballon", (0, 900, 0), (1, 2, 3)),
              _force("helice", (200, 0, 0), (4, 5, 6))]
    overlay = build_force_overlay(forces, com=(0, 0, 0), span=60,
                                  lift_centre=(1, 2, 3),
                                  torque=(10.0, 0, 0), resultant=(0, -100, 0))
    assert {"gravite", "ballon", "helice", "resultante", "couple",
            "centres"} <= set(overlay.ranges)
    # les plages ne se chevauchent pas et couvrent tous les sommets
    spans = sorted(overlay.ranges.values())
    for (first, count), (next_first, _) in zip(spans, spans[1:]):
        assert first + count <= next_first
    assert sum(c for _f, c in spans) == overlay.vertices


def test_la_resultante_et_le_couple_sont_distincts_des_forces(  ):
    """F3.8 : ils ne doivent pas se confondre avec les forces elementaires."""
    forces = [_force("gravite", (0, -1000, 0), (0, 0, 0))]
    overlay = build_force_overlay(forces, com=(0, 0, 0), span=40,
                                  torque=(0, 0, 500.0), resultant=(0, -1000, 0))
    groupes = {e["groupe"] for e in overlay.legend}
    assert "resultante" in groupes and "couple" in groupes
    couple = next(e for e in overlay.legend if e["groupe"] == "couple")
    assert couple["unite"] == "N.bloc", "un couple n'est pas une force"


def test_le_bras_de_levier_affiche_est_l_horizontal():
    """Seule la composante horizontale produit un moment sous une force
    verticale : afficher l'ecart 3D ferait croire a un desequilibre inexistant."""
    forces = [_force("gravite", (0, -100, 0), (0, 0, 0))]
    overlay = build_force_overlay(forces, com=(0.0, 0.0, 0.0), span=50,
                                  lift_centre=(3.0, 40.0, 4.0))
    centres = next(e for e in overlay.legend if e["groupe"] == "centres")
    assert centres["intensite"] == pytest.approx(5.0)   # hypot(3, 4), pas 40
    assert "horizontal" in centres["unite"]


def test_un_vaisseau_sans_force_ne_casse_pas():
    overlay = build_force_overlay([], com=(0, 0, 0), span=30)
    assert overlay.scale == 0.0
    assert overlay.vertices >= 0


# --- sur un vrai vaisseau ---------------------------------------------------
def test_surimpression_d_un_vaisseau_reel(sim):
    forces = sim.current_forces()
    overlay = build_force_overlay(
        forces, com=sim.mass.com, span=max(sim.model.structure.size),
        lift_centre=lift_centre(forces), resultant=resultant(forces))
    assert overlay.vertices > 0
    assert "gravite" in overlay.ranges
    assert "ballon" in overlay.ranges
    assert "centres" in overlay.ranges
    assert overlay.scale > 0
    assert np.isfinite(overlay.positions).all()


def test_le_centre_de_portance_est_celui_des_forces_montantes(sim):
    forces = sim.current_forces()
    centre = lift_centre(forces)
    assert centre is not None
    montantes = [f for f in forces if f.vector[1] > 0]
    assert len(montantes) >= 1
    attendu = [sum(f.vector[1] * f.point[i] for f in montantes)
               / sum(f.vector[1] for f in montantes) for i in range(3)]
    assert list(centre) == pytest.approx(attendu)


def test_l_axe_longitudinal_est_la_plus_grande_dimension_horizontale():
    """Le calculateur statique supposait x ; ces vaisseaux sont longs en z."""
    assert longitudinal_axis((34, 38, 67)) == 2      # cargo_airship
    assert longitudinal_axis((31, 37, 176)) == 2     # c1_air_cruiser
    assert longitudinal_axis((69, 27, 25)) == 0      # cachalot_volant
    assert longitudinal_axis((10, 99, 10)) == 0      # la hauteur ne compte pas


def test_le_tangage_est_rapporte_au_bon_axe(sim):
    tangage = sim.report()["bilan"]["tangage"]
    assert tangage["axe_longitudinal"] == "z"
    assert abs(tangage["bras_longitudinal"]) > abs(tangage["bras_lateral"])
    assert tangage["sens"] in ("cabre", "pique", "neutre")
