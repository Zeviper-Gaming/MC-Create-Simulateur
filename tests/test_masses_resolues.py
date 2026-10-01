"""Etape 1 de la remise a niveau : les masses telles que le jeu les resout.

Le simulateur devinait la classe de masse d'un bloc par mots-cles. Le jeu la
tire de ses datapacks — definitions `physics_block_properties`, rattachees a
des tags, appliquees dans un ordre lu au bytecode. `tools/extraire_masses.py`
reproduit cette resolution a partir des jars de l'instance, et ces tests en
figent le resultat.

Chaque valeur attendue ici a sa source dans `data/tables/masses_resolues.json`,
qui porte le jar et le chemin de la definition qui la fixe.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from createsim.data.tables import BlockProperties, Tables
from createsim.model.vehicle import VehicleModel
from createsim.sim.state import SimOptions
from createsim.sim.tick import Simulation

DEPOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEPOT / "tools"))

from extraire_masses import (java_string_hash, ordre_hashmap,  # noqa: E402
                             resource_location_hash)


@pytest.fixture(scope="module")
def blocs(tables) -> BlockProperties:
    props = BlockProperties(tables)
    assert props.resolved is not None, "data/tables/masses_resolues.json manquante"
    return props


# --- ce que la devinette ratait ----------------------------------------------
@pytest.mark.parametrize("nom, etat, masse", [
    # le constat de l'audit : les blocs de metal sont dans #c:storage_blocks,
    # donc #sable:super_heavy — aucun mot-cle ne le devinait
    ("minecraft:iron_block", None, 4.0),
    # l'etat compte : une dalle double pese le double
    ("minecraft:oak_slab", {"type": "bottom"}, 0.25),
    ("minecraft:oak_slab", {"type": "double"}, 0.5),
    # egalite de priorite entre `light` et `normal` : l'ordre de la HashMap
    # applique `normal` apres, et les dalles de pierre valent 1
    ("minecraft:stone_slab", {"type": "bottom"}, 1.0),
    ("minecraft:stone_slab", {"type": "double"}, 2.0),
    # Offroad range son support de roue dans #sable:heavy
    ("offroad:wheel_mount", None, 2.0),
    # Simulated range ses connecteurs de corde dans #sable:super_light
    ("simulated:rope_connector", None, 0.25),
    # l'autre egalite tranchee par la HashMap : `super_heavy` apres `light`
    ("create:cardboard_block", None, 4.0),
    # sans forme de collision, pas de masse (isSolid)
    ("minecraft:oak_wall_sign", None, 0.0),
    # ce qui ne change pas
    ("aeronautics:white_envelope", None, 0.25),
    ("create:flywheel", None, 4.0),
    ("minecraft:stone", None, 2.0),
    ("minecraft:stone_bricks", None, 1.0),
])
def test_la_masse_d_un_etat_de_bloc_est_celle_du_jeu(blocs, nom, etat, masse):
    assert blocs.mass(nom, etat) == pytest.approx(masse), blocs.mass_source(nom, etat)


def test_chaque_masse_dit_d_ou_elle_vient(blocs):
    """La regle d'or : une valeur sans source n'est pas une valeur."""
    for nom, etat in (("minecraft:iron_block", None),
                      ("minecraft:oak_slab", {"type": "double"}),
                      ("minecraft:stone_bricks", None)):
        source = blocs.mass_source(nom, etat)
        assert ".jar!/data/" in source or "PhysicsBlockPropertyTypes" in source, source


# --- sur les vaisseaux --------------------------------------------------------
def test_le_cargo_pese_ce_que_le_jeu_lui_attribue(tables):
    """Le cargo portait 102 blocs de fer comptes 1 au lieu de 4 : 13,1 % de
    masse en moins, et un centre de masse faux, puisque le fer est bas et a
    l'arriere."""
    cargo = VehicleModel.load(str(DEPOT / "tests" / "fixtures" / "cargo_airship.nbt"), tables)
    masse = cargo.organ("masse")
    assert masse.total == pytest.approx(2135.5)
    assert masse.com == pytest.approx((16.50, 13.32, 34.09), abs=0.01)


def test_une_dalle_double_retiree_rend_sa_vraie_masse(cargo):
    """La mise a jour differentielle doit, elle aussi, lire l'etat du bloc."""
    masse = cargo.organ("masse")
    dalle = next(p for p, b in cargo.structure.blocks.items()
                 if b["name"] == "minecraft:oak_slab"
                 and (b.get("props") or {}).get("type") == "double")
    avant = masse.total
    cargo.delete(dalle)
    assert avant - masse.total == pytest.approx(0.5)


def test_les_mods_absents_de_l_instance_restent_signales(cruiser_model):
    """Le cruiser vient d'une autre instance : createdeco, copycats et
    createbigcannons n'existent pas ici. Leurs blocs n'ont pas de masse
    connue, et le rapport doit le dire."""
    inconnus = cruiser_model.organ("masse").unknown
    espaces = {nom.split(":")[0] for nom in inconnus}
    assert espaces == {"createdeco", "copycats", "createbigcannons"}


# --- l'ordre du jeu, reproduit ------------------------------------------------
def test_le_hachage_est_celui_de_java():
    """Valeurs connues de `String.hashCode()`, debordement compris."""
    assert java_string_hash("hello") == 99162322
    assert java_string_hash("polygenelubricants") == -2147483648
    assert resource_location_hash("sable", "light") == \
        ((31 * java_string_hash("sable") + java_string_hash("light")
          + 2**31) % 2**32 - 2**31)


def test_l_ordre_d_une_hashmap_suit_les_cases():
    """Deux cles dans l'ordre d'insertion ressortent dans l'ordre des cases de
    la table, pas dans l'ordre alphabetique."""
    cles = [("sable", "light"), ("sable", "normal")]
    ordre = ordre_hashmap(cles)
    assert sorted(ordre) == sorted(cles)


def test_la_table_resolue_tranche_les_egalites_en_clair(blocs):
    """Les egalites de priorite ne sont pas cachees : la table les liste."""
    import json
    doc = json.loads(blocs.resolved.path.read_text(encoding="utf-8"))
    gagnantes = {tuple(e["definitions"]): e["gagnante"] for e in doc["egalites_tranchees"]}
    assert gagnantes[("sable:light", "sable:normal")] == "sable:normal"


# --- le repli, quand la table manque -----------------------------------------
def test_sans_table_resolue_les_masses_sont_devinees_et_c_est_dit(tmp_path):
    """Le repli existe pour qu'un depot sans la table reste utilisable — mais
    il doit se signaler, sinon on retombe sur 13 % d'erreur sans le savoir."""
    source = DEPOT / "data" / "tables"
    for fichier in source.glob("*.json"):
        if fichier.name != "masses_resolues.json":
            shutil.copy(fichier, tmp_path / fichier.name)
    sans = Tables.load(tmp_path)
    blocs = BlockProperties(sans)
    assert blocs.resolved is None
    assert blocs.mass("minecraft:iron_block") == 1.0          # la devinette
    assert "DEVINEE" in blocs.mass_source("minecraft:iron_block")

    cargo = VehicleModel.load(str(DEPOT / "tests" / "fixtures" / "cargo_airship.nbt"), sans)
    codes = {a["code"] for a in Simulation(cargo, SimOptions()).diagnose()}
    assert "F5.15" in codes
