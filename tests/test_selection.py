"""Selection au clic et maillage par troncons (F6.1, F6.4).

Deux proprietes a tenir, et chacune a son test qui cherche a la prendre en
defaut :

    le maillage incremental dessine EXACTEMENT ce qu'une reconstruction
    complete dessinerait — sinon une edition laisserait des faces fantomes ;

    un clic selectionne le bloc VU, jamais celui de derriere.
"""
from __future__ import annotations

import math
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from createsim.model.vehicle import VehicleModel
from createsim.view.chunks import ChunkedMesh
from createsim.view.mesh import build_mesh, families_from_model
from createsim.view.picking import pick, ray_from_pixel

INSTANCE = Path(r"C:/Users/Florian/curseforge/minecraft/Instances"
                r"/La Bonne Compagnie/schematics")


def _triangles(mesh) -> Counter:
    """Le multi-ensemble des triangles, couleur comprise, a l'arrondi pres."""
    pos = np.round(mesh.positions.reshape(-1, 9), 4)
    col = np.round(mesh.colors.reshape(-1, 3, 3)[:, 0, :], 4)
    return Counter(tuple(p) + tuple(c) for p, c in zip(pos, col))


def _area_by_normal(mesh) -> dict:
    tri = mesh.positions.reshape(-1, 3, 3)
    normals = np.round(mesh.normals.reshape(-1, 3, 3)[:, 0, :], 3)
    area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0],
                                         tri[:, 2] - tri[:, 0]), axis=1)
    out: dict = {}
    for n, a in zip(map(tuple, normals), area):
        out[n] = out.get(n, 0.0) + float(a)
    return out


# --- le maillage par troncons ------------------------------------------------
def test_les_troncons_couvrent_la_meme_surface_que_le_maillage_entier(cargo):
    """La fusion s'arrete aux frontieres, donc plus de triangles — mais la
    SURFACE dessinee, face par face, doit etre la meme."""
    fam = families_from_model(cargo)
    entier = build_mesh(cargo.structure, fam)
    troncons = ChunkedMesh(cargo.structure, fam).mesh()
    assert troncons.triangles >= entier.triangles
    a, b = _area_by_normal(entier), _area_by_normal(troncons)
    assert a.keys() == b.keys()
    for normal in a:
        assert b[normal] == pytest.approx(a[normal], rel=1e-9), normal


def test_la_mise_a_jour_dessine_ce_qu_une_reconstruction_dessinerait(cargo):
    """LE test du maillage incremental. Une face oubliee a une frontiere de
    troncon laisserait un trou — ou une face fantome — apres l'edition."""
    fam = families_from_model(cargo)
    chunked = ChunkedMesh(cargo.structure, fam)
    # des editions dispersees, dont une au bord d'un troncon
    cibles = [p for p in sorted(cargo.structure.blocks)
              if p[0] % 16 in (0, 15)][:3] + sorted(cargo.structure.blocks)[:3]
    for pos in cibles:
        cargo.delete(pos)
    chunked.update(cargo.structure, families_from_model(cargo))
    frais = ChunkedMesh(cargo.structure, families_from_model(cargo))
    assert _triangles(chunked.mesh()) == _triangles(frais.mesh())


def test_une_edition_qui_recolore_des_voisins_est_vue(cargo):
    """Retirer un arbre de transmission sort ses voisins du reseau cinetique :
    leur couleur change sans qu'on les ait touches. Le changement se lit par
    difference de grilles, pas en devinant."""
    kin = cargo.organ("cinetique")
    chunked = ChunkedMesh(cargo.structure, families_from_model(cargo))
    avant = chunked.grid.copy()
    arbre = next(p for p in sorted(kin.nodes)
                 if sum(1 for q, _ in cargo.structure.neighbours(p)
                        if q in kin.nodes) >= 2)
    cargo.delete(arbre)
    chunked.update(cargo.structure, families_from_model(cargo))
    changes = np.argwhere(chunked.grid != avant)
    assert len(changes) >= 1


def test_une_edition_ne_remaille_que_quelques_troncons(cargo):
    chunked = ChunkedMesh(cargo.structure, families_from_model(cargo))
    total = len(chunked.chunks)
    cargo.delete(sorted(cargo.structure.blocks)[len(cargo.structure) // 2])
    refaits = chunked.update(cargo.structure, families_from_model(cargo))
    assert 1 <= len(refaits) <= 8 < total


def test_remailler_le_cruiser_tient_dans_un_tick():
    """F6.4 : sans interruption perceptible. Remailler tout le cruiser coute
    219 ms ; un troncon doit tenir sous le tick de 50 ms, avec de la marge
    pour une machine plus lente."""
    path = INSTANCE / "c1_air_cruiser.nbt"
    if not path.is_file():
        pytest.skip("vaisseau hors depot")
    model = VehicleModel.load(str(path))
    chunked = ChunkedMesh(model.structure, families_from_model(model))
    bloc = sorted(model.structure.blocks)[len(model.structure) // 2]
    model.delete(bloc)
    depart = time.perf_counter()
    chunked.update(model.structure, families_from_model(model))
    chunked.mesh()
    ecoule = time.perf_counter() - depart
    assert ecoule < 0.1, "%.0f ms" % (ecoule * 1000)


# --- la selection au rayon ---------------------------------------------------
def _grid(cells, size=(8, 8, 8)):
    occupied = set(cells)
    return (lambda p: p in occupied), size


def test_un_rayon_vertical_touche_le_dessus_du_bloc():
    occupied, size = _grid([(3, 2, 4)])
    hit = pick(occupied, size, (3.5, 20.0, 4.5), (0.0, -1.0, 0.0))
    assert hit == ((3, 2, 4), (0, 1, 0))


def test_le_bloc_vu_est_celui_de_devant():
    """Deux blocs alignes : le clic doit prendre le premier traverse."""
    occupied, size = _grid([(2, 1, 1), (5, 1, 1)])
    hit = pick(occupied, size, (-3.0, 1.5, 1.5), (1.0, 0.0, 0.0))
    assert hit == ((2, 1, 1), (-1, 0, 0))


def test_un_rayon_oblique_ne_saute_aucune_case():
    """Amanatides et Woo : on franchit toujours la frontiere la plus proche,
    donc un rayon qui frole un coin ne traverse pas un bloc sans le voir."""
    occupied, size = _grid([(4, 4, 4)])
    direction = (1.0, 1.0, 1.0)
    norm = math.sqrt(3.0)
    hit = pick(occupied, size, (0.2, 0.2, 0.2),
               tuple(c / norm for c in direction))
    assert hit is not None and hit[0] == (4, 4, 4)


def test_un_rayon_qui_manque_la_structure_ne_rend_rien():
    occupied, size = _grid([(1, 1, 1)])
    assert pick(occupied, size, (-5.0, 50.0, -5.0), (0.0, 1.0, 0.0)) is None
    assert pick(occupied, size, (0.5, 0.5, 20.0), (0.0, 0.0, 1.0)) is None


def test_le_pixel_central_vise_la_cible_de_la_camera(cargo):
    """Le rayon du pixel central passe par la cible de l'orbite : c'est la
    verification que la base de la camera est bien celle de `lookAt`."""
    from createsim.view.cubes import OrbitCamera
    camera = OrbitCamera(centre=(10.0, 5.0, 20.0), radius=15.0)
    origin, direction = ray_from_pixel(camera, 400, 300, 800, 600)
    to_target = [camera.target[i] - origin[i] for i in range(3)]
    norm = math.sqrt(sum(c * c for c in to_target))
    cos = sum(direction[i] * to_target[i] / norm for i in range(3))
    assert cos == pytest.approx(1.0, abs=1e-9)


def test_un_clic_sur_le_vaisseau_selectionne_un_bloc_reel(cargo):
    from createsim.view.cubes import OrbitCamera
    chunked = ChunkedMesh(cargo.structure, families_from_model(cargo))
    mesh = chunked.mesh()
    camera = OrbitCamera(mesh.centre, mesh.radius)
    origin, direction = ray_from_pixel(camera, 400, 300, 800, 600)
    hit = pick(chunked.occupied, cargo.structure.size, origin, direction)
    assert hit is not None
    pos, normal = hit
    assert pos in cargo.structure.blocks
    assert sum(abs(c) for c in normal) == 1


def test_la_mise_a_jour_par_cases_egale_la_mise_a_jour_complete(cargo):
    """La mise a jour restreinte aux cases editees doit donner la meme image
    que la mise a jour qui recalcule la couleur de tout le vaisseau — tant que
    le reseau cinetique n'a pas ete refait, ce que l'appelant verifie."""
    fam = families_from_model(cargo)
    partielle = ChunkedMesh(cargo.structure, fam)
    kin = cargo.organ("cinetique")
    anodins = [p for p in sorted(cargo.structure.blocks)
               if p not in kin.sensitive][:6]
    for pos in anodins:
        avant = cargo.work["cinetique"]
        cargo.delete(pos)
        assert cargo.work["cinetique"] == avant, "choisir des cases hors reseau"
        partielle.update(cargo.structure, families_from_model(cargo), {pos})
    frais = ChunkedMesh(cargo.structure, families_from_model(cargo))
    assert _triangles(partielle.mesh()) == _triangles(frais.mesh())
