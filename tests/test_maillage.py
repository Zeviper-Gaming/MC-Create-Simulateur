"""Le maillage : faces internes supprimees, rectangles fusionnes.

Ce module est le poste couteux du rendu, et il se teste sans fenetre — c'est
tout l'interet de l'avoir isole. Les tests qui suivent ne touchent ni Qt ni
OpenGL.
"""
from __future__ import annotations

import numpy as np
import pytest

from createsim.view.mesh import FAMILIES, build_mesh, families_from_model


class FakeStructure:
    """Une structure minimale, pour eprouver la geometrie seule."""

    def __init__(self, size, blocks):
        self.size = size
        self.blocks = {p: {"name": n, "props": {}} for p, n in blocks.items()}
        self.path = "fake.nbt"

    def is_air(self, pos):
        return pos not in self.blocks


def _solid(size, name="minecraft:stone"):
    blocks = {(x, y, z): name
              for x in range(size[0]) for y in range(size[1])
              for z in range(size[2])}
    return FakeStructure(size, blocks)


def _structure_family(pos, block):
    return "structure"


def test_un_bloc_seul_donne_six_faces():
    mesh = build_mesh(_solid((1, 1, 1)), _structure_family)
    assert mesh.blocks == 1
    assert mesh.faces_before_merge == 6
    assert mesh.quads == 6
    assert mesh.triangles == 12


def test_les_faces_internes_disparaissent():
    """Un cube plein de 4x4x4 : 384 faces au total, 96 seulement sont vues."""
    mesh = build_mesh(_solid((4, 4, 4)), _structure_family)
    assert mesh.blocks == 64
    assert mesh.faces_before_merge == 6 * 16      # une seule couche par cote
    # ... et chaque cote fusionne en UN rectangle
    assert mesh.quads == 6


def test_la_fusion_gloutonne_reduit_vraiment():
    """Une plaque 16x1x16 d'une seule famille : 2 grands rectangles pour le
    dessus et le dessous, plus les tranches."""
    mesh = build_mesh(_solid((16, 1, 16)), _structure_family)
    assert mesh.blocks == 256
    assert mesh.faces_before_merge == 2 * 256 + 4 * 16
    assert mesh.quads == 6, "chaque face plane doit fusionner en un rectangle"


def test_deux_familles_ne_fusionnent_pas():
    """La couleur est plate par famille : fusionner a travers les familles
    effacerait justement ce que le rendu doit montrer."""
    blocks = {(x, 0, 0): "bloc" for x in range(4)}
    structure = FakeStructure((4, 1, 1), blocks)

    def moitie(pos, block):
        return "cinetique" if pos[0] < 2 else "structure"

    fusionne = build_mesh(structure, _structure_family)
    separe = build_mesh(structure, moitie)
    assert separe.quads > fusionne.quads


def test_une_structure_vide_ne_casse_pas():
    mesh = build_mesh(FakeStructure((4, 4, 4), {}), _structure_family)
    assert mesh.blocks == 0
    assert mesh.quads == 0
    assert mesh.vertices == 0
    assert mesh.stats()["triangles"] == 0


def test_les_normales_sont_unitaires_et_axiales():
    mesh = build_mesh(_solid((3, 3, 3)), _structure_family)
    normals = mesh.normals.reshape(-1, 3)
    lengths = np.linalg.norm(normals, axis=1)
    assert np.allclose(lengths, 1.0)
    # chaque normale n'a qu'une seule composante non nulle
    assert np.all((np.abs(normals) > 0.5).sum(axis=1) == 1)


def test_les_sommets_restent_dans_la_boite():
    size = (5, 4, 7)
    mesh = build_mesh(_solid(size), _structure_family)
    points = mesh.positions.reshape(-1, 3)
    assert points.min() >= 0.0
    for axis in range(3):
        assert points[:, axis].max() <= size[axis]
    assert mesh.bounds == ((0.0, 0.0, 0.0), (5.0, 4.0, 7.0))


def test_les_tableaux_ont_la_meme_longueur():
    mesh = build_mesh(_solid((6, 3, 4)), _structure_family)
    assert mesh.positions.size == mesh.normals.size == mesh.colors.size
    assert mesh.positions.size % 9 == 0, "trois sommets par triangle"
    assert mesh.positions.dtype == np.float32


# --- sur un vrai vaisseau ---------------------------------------------------
def test_maillage_d_un_vaisseau_reel(cargo):
    mesh = build_mesh(cargo.structure, families_from_model(cargo))
    stats = mesh.stats()
    assert stats["blocs"] == 5039
    # l'immense majorite des faces est interne et ne sera jamais vue
    assert stats["faces_visibles"] < 6 * stats["blocs"] * 0.5
    assert stats["reduction_par_fusion"] > 0.5
    assert stats["triangles"] < stats["blocs"] * 2
    assert stats["octets_gpu"] < 4 * 1024 * 1024


def test_les_familles_couvrent_les_organes(cargo):
    family_at = families_from_model(cargo)
    trouvees = {family_at(pos, block) for pos, block in cargo.structure.blocks.items()}
    assert trouvees <= set(FAMILIES)
    assert "propulsion" in trouvees, "ce vaisseau a des helices"
    assert "cinetique" in trouvees
    assert "enveloppe" in trouvees


def test_le_maillage_tient_le_budget_de_chargement(cargo):
    """Le rendu se calcule une fois au chargement, pas a chaque tick."""
    import time
    start = time.perf_counter()
    build_mesh(cargo.structure, families_from_model(cargo))
    assert time.perf_counter() - start < 1.0
