"""Construction du maillage : fusion des faces internes, par famille de blocs.

La cible du cahier est un rendu simple et peu couteux, de la famille de ceux
qu'affiche createmod.com : des cubes a faces internes fusionnees, une couleur
plate par famille, un eclairage directionnel fixe, et rien de plus. L'image sert
a situer les organes et les forces, pas a faire joli.

Deux reductions successives :

  1. **Faces cachees supprimees.** Une face n'existe que si le voisin dans sa
     direction est vide. Sur un vaisseau plein, l'immense majorite des faces est
     interne et ne sera jamais vue.
  2. **Rectangles fusionnes.** Les faces coplanaires, de meme famille et de meme
     orientation, sont regroupees en rectangles aussi grands que possible
     (maillage glouton). Une coque de 20 000 blocs tombe ainsi a quelques
     milliers de quadrilateres.

Ce module ne connait ni Qt ni OpenGL : il produit des tableaux de sommets, et
se teste sans fenetre. C'est ce qui permet d'eprouver le poste de rendu avant
que le reste de l'interface existe.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# Familles du cahier (F3.1), et leur couleur plate.
FAMILIES = ("structure", "enveloppe", "cinetique", "commandes", "propulsion")
COLORS = {
    "structure": (0.62, 0.60, 0.57),
    "enveloppe": (0.86, 0.89, 0.94),
    "cinetique": (0.83, 0.62, 0.24),
    "commandes": (0.80, 0.33, 0.30),
    "propulsion": (0.30, 0.68, 0.62),
}
FAMILY_INDEX = {name: i for i, name in enumerate(FAMILIES)}

# Les six directions de face : (axe, sens)
FACES = ((0, +1), (0, -1), (1, +1), (1, -1), (2, +1), (2, -1))

# Coins d'un quadrilatere unite, dans le plan (u, v) des deux autres axes.
_CORNERS = ((0, 0), (1, 0), (1, 1), (0, 1))


@dataclass
class Mesh:
    """Sommets prets a etre envoyes au GPU, en triangles."""

    positions: np.ndarray = field(default_factory=lambda: np.empty(0, np.float32))
    normals: np.ndarray = field(default_factory=lambda: np.empty(0, np.float32))
    colors: np.ndarray = field(default_factory=lambda: np.empty(0, np.float32))
    quads: int = 0
    faces_before_merge: int = 0
    blocks: int = 0
    bounds: tuple = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))

    @property
    def vertices(self) -> int:
        return self.positions.size // 3

    @property
    def triangles(self) -> int:
        return self.vertices // 3

    @property
    def centre(self) -> tuple[float, float, float]:
        lo, hi = self.bounds
        return tuple((lo[i] + hi[i]) / 2.0 for i in range(3))

    @property
    def radius(self) -> float:
        lo, hi = self.bounds
        return max(1.0, max(hi[i] - lo[i] for i in range(3)) / 2.0)

    def stats(self) -> dict:
        reduction = (1.0 - self.quads / self.faces_before_merge
                     if self.faces_before_merge else 0.0)
        return {
            "blocs": self.blocks,
            "faces_visibles": self.faces_before_merge,
            "quadrilateres": self.quads,
            "triangles": self.triangles,
            "sommets": self.vertices,
            "reduction_par_fusion": round(reduction, 4),
            "octets_gpu": int(self.positions.nbytes + self.normals.nbytes
                              + self.colors.nbytes),
        }


def family_grid(structure, family_at) -> tuple[np.ndarray, tuple]:
    """Grille 3D des familles : -1 pour le vide, sinon l'index de famille."""
    size = tuple(int(v) for v in structure.size)
    grid = np.full(size, -1, dtype=np.int8)
    for pos, block in structure.blocks.items():
        if structure.is_air(pos):
            continue
        if not (0 <= pos[0] < size[0] and 0 <= pos[1] < size[1]
                and 0 <= pos[2] < size[2]):
            continue
        grid[pos] = FAMILY_INDEX.get(family_at(pos, block), 0)
    return grid, size


def _exposed(grid: np.ndarray, axis: int, sign: int) -> np.ndarray:
    """Masque des cellules pleines dont le voisin dans cette direction est vide."""
    solid = grid >= 0
    shifted = np.zeros_like(solid)
    slicer_dst = [slice(None)] * 3
    slicer_src = [slice(None)] * 3
    if sign > 0:
        slicer_dst[axis] = slice(0, -1)
        slicer_src[axis] = slice(1, None)
    else:
        slicer_dst[axis] = slice(1, None)
        slicer_src[axis] = slice(0, -1)
    shifted[tuple(slicer_dst)] = solid[tuple(slicer_src)]
    return solid & ~shifted


def _greedy_rectangles(plane: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    """Regroupe un plan de familles en rectangles maximaux.

    `plane` porte l'index de famille, ou -1 pour « pas de face ici ». Renvoie
    une liste de (u, v, largeur, hauteur, famille). Algorithme glouton
    classique : on avance en largeur tant que la famille est la meme, puis on
    descend en hauteur tant que la ligne entiere concorde.
    """
    work = plane.copy()
    height, width = work.shape
    out: list[tuple[int, int, int, int, int]] = []
    for u in range(height):
        row = work[u]
        v = 0
        while v < width:
            fam = row[v]
            if fam < 0:
                v += 1
                continue
            # extension en largeur
            w = 1
            while v + w < width and row[v + w] == fam:
                w += 1
            # extension en hauteur, ligne entiere par ligne entiere
            h = 1
            while u + h < height:
                if not np.all(work[u + h, v:v + w] == fam):
                    break
                h += 1
            work[u:u + h, v:v + w] = -1
            out.append((u, v, w, h, int(fam)))
            v += w
    return out


def build_mesh(structure, family_at) -> Mesh:
    """Construit le maillage complet d'une structure."""
    grid, size = family_grid(structure, family_at)
    return build_from_grid(grid, size)


def build_cells_mesh(cells, size, color) -> Mesh:
    """Maille un simple ensemble de cellules, d'une seule couleur.

    Sert aux volumes qui ne sont pas des blocs : le gaz d'une poche de ballon
    occupe des cellules vides, et c'est pourtant un volume a montrer.
    """
    grid = np.full(tuple(int(v) for v in size), -1, dtype=np.int8)
    for pos in cells:
        if all(0 <= pos[i] < size[i] for i in range(3)):
            grid[pos] = 0
    return build_from_grid(grid, size, palette=np.array([color], np.float32))


def build_from_grid(grid: np.ndarray, size, palette=None) -> Mesh:
    """Le maillage glouton proprement dit, a partir d'une grille d'index."""
    blocks = int((grid >= 0).sum())
    if blocks == 0:
        return Mesh()

    positions: list[np.ndarray] = []
    normals: list[np.ndarray] = []
    colors: list[np.ndarray] = []
    quads = 0
    raw_faces = 0

    if palette is None:
        palette = np.array([COLORS[name] for name in FAMILIES], dtype=np.float32)

    for axis, sign in FACES:
        exposed = _exposed(grid, axis, sign)
        raw_faces += int(exposed.sum())
        u_axis, v_axis = [a for a in (0, 1, 2) if a != axis]
        masked = np.where(exposed, grid, np.int8(-1))

        normal = [0.0, 0.0, 0.0]
        normal[axis] = float(sign)
        normal_vec = np.array(normal, dtype=np.float32)

        for layer in range(size[axis]):
            plane = np.take(masked, layer, axis=axis)
            if not (plane >= 0).any():
                continue
            offset = layer + (1.0 if sign > 0 else 0.0)
            for u, v, w, h, fam in _greedy_rectangles(plane):
                quads += 1
                corners = []
                for cu, cv in _CORNERS:
                    point = [0.0, 0.0, 0.0]
                    point[axis] = offset
                    point[u_axis] = float(u + cu * h)
                    point[v_axis] = float(v + cv * w)
                    corners.append(point)
                # Deux triangles, enroules pour que la normale geometrique
                # coincide avec la normale annoncee.
                #
                # Piege : apres `np.take`, les deux axes restants gardent leur
                # ordre d'origine, soit (x, z) pour l'axe y. Ce reperage est
                # GAUCHER par rapport a +y, alors qu'il est droitier pour x et
                # pour z. Sans la correction, toutes les faces horizontales
                # sortaient enroulees a l'envers et le back-face culling les
                # eliminait : on voyait a travers chaque pont et chaque toit.
                reverse = (axis == 1) != (sign < 0)
                order = ((0, 2, 1), (0, 3, 2)) if reverse else ((0, 1, 2), (0, 2, 3))
                tri = np.array([corners[i] for triangle in order for i in triangle],
                               dtype=np.float32)
                positions.append(tri)
                normals.append(np.tile(normal_vec, (6, 1)))
                colors.append(np.tile(palette[fam], (6, 1)))

    mesh = Mesh(
        positions=np.concatenate(positions).ravel() if positions
        else np.empty(0, np.float32),
        normals=np.concatenate(normals).ravel() if normals
        else np.empty(0, np.float32),
        colors=np.concatenate(colors).ravel() if colors
        else np.empty(0, np.float32),
        quads=quads,
        faces_before_merge=raw_faces,
        blocks=blocks,
        bounds=((0.0, 0.0, 0.0), tuple(float(v) for v in size)),
    )
    return mesh


# ---------------------------------------------------------------------------
# Classement par famille, d'apres le modele
# ---------------------------------------------------------------------------
def families_from_model(model):
    """Renvoie un `family_at(pos, block)` qui lit les organes deja calcules.

    Le rendu n'a ainsi rien a redecouvrir : il colore ce que le modele sait.
    """
    kinetic = set(model.organ("cinetique").nodes)
    airtight = model.organ("trainee").cells
    levitite = model.organ("levitite").cells
    redstone = model.organ("redstone")
    commands = {lv.pos for lv in redstone.levers} | set(redstone.consumers)
    propulsion = {b.pos for b in model.organ("paliers").bearings}
    props = model.props

    def family_at(pos, block) -> str:
        if pos in propulsion or props.is_sail(block["name"]):
            return "propulsion"
        if pos in commands:
            return "commandes"
        if pos in kinetic:
            return "cinetique"
        if pos in airtight or pos in levitite:
            return "enveloppe"
        return "structure"

    return family_at


# ---------------------------------------------------------------------------
# Surbrillance du reseau cinetique (F3.12)
# ---------------------------------------------------------------------------
RPM_RAMP = (
    (0.30, 0.34, 0.40),   # a l'arret : gris, en retrait
    (0.30, 0.55, 0.95),   # lent
    (0.35, 0.85, 0.65),
    (0.95, 0.85, 0.30),
    (1.00, 0.55, 0.25),
    (1.00, 0.30, 0.30),   # au plafond de rotation
)
MUTED = (0.26, 0.27, 0.30)


def build_kinetic_mesh(structure, model, speeds, ceiling: float = 256.0) -> Mesh:
    """Le vaisseau en retrait, son reseau cinetique teinte par regime.

    Repond a « qu'est-ce qui tourne, et a quelle vitesse ? » sans ouvrir un
    tableau : un arbre rouge a cote d'un arbre bleu, c'est un rapport de
    demultiplication qu'on voit au lieu de le lire.
    """
    size = tuple(int(v) for v in structure.size)
    grid = np.full(size, -1, dtype=np.int8)
    kinetic = model.organ("cinetique").nodes
    for pos in structure.blocks:
        if structure.is_air(pos) or not all(0 <= pos[i] < size[i] for i in range(3)):
            continue
        if pos in kinetic:
            rpm = abs(speeds.get(pos, 0.0))
            if rpm <= 1e-9:
                index = 1
            else:
                # echelle logarithmique : les regimes utiles s'etalent de 4 a
                # 256 tr/min, une echelle lineaire ecraserait tout en bas
                ratio = math.log1p(rpm) / math.log1p(ceiling)
                step = min(len(RPM_RAMP) - 2, int(ratio * (len(RPM_RAMP) - 1)))
                index = 2 + step
        else:
            index = 0
        grid[pos] = index
    palette = np.array((MUTED,) + RPM_RAMP, dtype=np.float32)
    return build_from_grid(grid, size, palette=palette)
