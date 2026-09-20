"""Invalidation selective (F6) : ne refaire que ce que l'edition concerne.

C'est le point dur du cahier, et le seul qui engage l'architecture. Une edition
n'est pas couteuse en elle-meme ; ce qui coute, c'est ce qu'elle invalide.

Les deux exigences explicites du cahier sont verifiees ici :
  - le remplissage n'est relance que sur LA POCHE CONCERNEE ;
  - une edition qui ne touche ni un bloc etanche ni l'interieur d'une poche ne
    declenche AUCUN flood-fill — deplacer un coffre dans la soute ne doit rien
    couter.
"""
from __future__ import annotations

import pytest


def _bloc_anodin(model):
    """Un bloc de soute : ni etanche, ni cinetique, ni dans une poche."""
    bal = model.organ("ballons")
    kin = model.organ("cinetique")
    rs = model.organ("redstone")
    pal = model.organ("paliers")
    for pos, b in sorted(model.structure.blocks.items()):
        if pos in bal.sensitive or pos in kin.sensitive or pos in rs.sensitive:
            continue
        if any(b_.in_front(pos) or pos in b_.rotor for b_ in pal.bearings):
            continue
        if model.props.is_airtight(b["name"]) or model.props.mass(b["name"]) <= 0:
            continue
        return pos, b
    return None, None


def test_un_bloc_de_soute_ne_declenche_aucun_flood_fill(cargo):
    pos, block = _bloc_anodin(cargo)
    assert pos is not None, "aucun bloc anodin trouve dans cette structure"

    bal = cargo.organ("ballons")
    avant_fills = bal.fills
    avant_recomputes = bal.recomputes

    touches = cargo.edit(pos, None)

    assert bal.fills == avant_fills, (
        "un bloc de soute a declenche %d flood-fill(s)" % (bal.fills - avant_fills))
    assert bal.recomputes == avant_recomputes
    assert "ballons" not in touches or touches["ballons"] == "delta"
    assert "masse" in touches, "la masse doit toujours etre reprise"


def test_la_masse_est_reprise_a_chaque_edition(cargo):
    pos, block = _bloc_anodin(cargo)
    masse = cargo.organ("masse")
    avant = masse.total
    attendu = avant - cargo.props.mass(block["name"])

    cargo.edit(pos, None)
    assert masse.total == pytest.approx(attendu, abs=1e-9)

    cargo.undo()
    assert masse.total == pytest.approx(avant, abs=1e-9)


def test_le_differentiel_egale_le_recalcul_complet(cargo):
    pos, _ = _bloc_anodin(cargo)
    masse = cargo.organ("masse")
    cargo.edit(pos, None)
    differentiel = (masse.total, masse.com, masse.unknown_total)
    masse.recompute()
    complet = (masse.total, masse.com, masse.unknown_total)
    assert differentiel[0] == pytest.approx(complet[0], abs=1e-6)
    for a, b in zip(differentiel[1], complet[1]):
        assert a == pytest.approx(b, abs=1e-9)
    assert differentiel[2] == complet[2]


def test_un_bloc_d_enveloppe_relance_le_remplissage(cargo):
    bal = cargo.organ("ballons")
    cible = next((p for p in sorted(bal.pockets[0].shell)
                  if cargo.props.is_airtight(cargo.structure.name(p))), None)
    assert cible is not None, "aucun bloc etanche au contact de la poche"

    avant = bal.fills
    cargo.edit(cible, None)
    assert bal.fills > avant, "retirer un bloc d'enveloppe doit refaire la poche"


def test_le_reseau_cinetique_suit_ses_propres_voisins(cargo):
    kin = cargo.organ("cinetique")
    stress = cargo.organ("stress")
    pos = next(iter(sorted(kin.nodes)))
    avant_kin, avant_stress = kin.recomputes, stress.recomputes

    touches = cargo.edit(pos, None)

    assert "cinetique" in touches
    assert kin.recomputes > avant_kin
    # le bilan Stress Units est derive du reseau : il suit
    assert stress.recomputes > avant_stress, touches


def test_pile_d_editions_annuler_refaire_et_retour_a_l_original(cargo):
    structure = cargo.structure
    masse = cargo.organ("masse")
    origine = masse.total
    blocs = len(structure)

    positions = [p for p, _ in [(_bloc_anodin(cargo))]]
    pos = positions[0]
    cargo.edit(pos, None)
    assert len(structure) == blocs - 1
    assert cargo.edited

    assert cargo.undo() is True
    assert len(structure) == blocs
    assert masse.total == pytest.approx(origine, abs=1e-9)

    assert cargo.redo() is True
    assert len(structure) == blocs - 1

    assert cargo.revert() >= 1
    assert len(structure) == blocs
    assert masse.total == pytest.approx(origine, abs=1e-9)
    assert not cargo.edited


def test_le_fichier_source_n_est_jamais_ecrit(cargo):
    from pathlib import Path
    source = Path(cargo.structure.path)
    empreinte = (source.stat().st_size, source.stat().st_mtime_ns)
    pos, _ = _bloc_anodin(cargo)
    cargo.edit(pos, None)
    cargo.revert()
    assert (source.stat().st_size, source.stat().st_mtime_ns) == empreinte


def test_une_superposition_est_refusee(cargo):
    occupe = next(iter(sorted(cargo.structure.blocks)))
    autre = next(p for p in sorted(cargo.structure.blocks) if p != occupe)
    with pytest.raises(ValueError, match="superposition"):
        cargo.move(autre, occupe)
