"""Edition de niveau 2 (F6, lot L5) : eprouver une variante sans la construire.

Les trois garde-fous du cahier structurent ce fichier, et chacun a son test qui
cherche a le prendre en defaut plutot qu'a le confirmer :

    non destructif   le fichier source n'est JAMAIS ecrit, quoi qu'on fasse
    export .nbt      une variante se relit par le simulateur, types compris
    diff chiffre     une variante se mesure contre l'etat charge, pas dans
                     l'absolu, et sous les memes commandes
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import nbtlib
import pytest

from createsim.data.nbt import Structure, retag
from createsim.model.vehicle import VehicleModel
from createsim.sim.scenario import Scenario, Step
from createsim.sim.state import SimOptions
from createsim.sim.tick import Simulation
from createsim.sim.variant import (Baseline, apply_ops, diff, export_variant,
                                   measure, ops_to_json, variant_diff,
                                   variant_filename)

FIXTURES = Path(__file__).parent / "fixtures"
CARGO = FIXTURES / "cargo_airship.nbt"


def _digest(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _some(model, name_part: str):
    return next(p for p, b in sorted(model.structure) if name_part in b["name"])


def _free_cell_next_to(model, pos):
    for d in ((0, 1, 0), (1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1), (0, -1, 0)):
        q = (pos[0] + d[0], pos[1] + d[1], pos[2] + d[2])
        if model.structure.inside(q) and q not in model.structure.blocks:
            return q
    pytest.skip("aucune case libre autour de %s" % (pos,))


# --- le fichier source n'est jamais ecrit (F6.5) ----------------------------
def test_aucun_geste_n_ecrit_le_fichier_source(tmp_path):
    """Le garde-fou principal, pris a revers : on fait TOUT, puis on compare
    l'empreinte du fichier source avant et apres."""
    source = tmp_path / "vaisseau.nbt"
    source.write_bytes(CARGO.read_bytes())
    avant = _digest(source)

    model = VehicleModel.load(str(source))
    bloc = _some(model, "planks")
    model.delete(bloc)
    model.add(bloc, "minecraft:oak_planks")
    libre = _free_cell_next_to(model, bloc)
    model.move(bloc, libre)
    model.undo()
    model.redo()
    model.revert()
    export_variant(model, str(tmp_path / "variante.nbt"))

    assert _digest(source) == avant, "le fichier source a ete modifie"


def test_l_export_refuse_le_fichier_source(tmp_path):
    source = tmp_path / "vaisseau.nbt"
    source.write_bytes(CARGO.read_bytes())
    model = VehicleModel.load(str(source))
    with pytest.raises(PermissionError):
        model.structure.export(str(source))


def test_l_export_ne_remplace_aucun_fichier(tmp_path):
    """« Un fichier NOUVEAU » : deux exports ne s'ecrasent jamais."""
    model = VehicleModel.load(str(CARGO))
    cible = tmp_path / "variante.nbt"
    model.structure.export(str(cible))
    with pytest.raises(FileExistsError):
        model.structure.export(str(cible))


# --- l'export relit ce qu'il a ecrit (F6.7) ----------------------------------
def _blocks(f):
    pal = f["palette"]
    return {tuple(int(x) for x in b["pos"]): (pal[int(b["state"])], b.get("nbt"))
            for b in f["blocks"]}


def test_un_export_sans_edition_est_sans_perte(tmp_path):
    """Types compris : un bloc de structure en jeu lit une valeur au mauvais
    type comme zero, sans erreur. `Speed` doit rester un Float."""
    cible = tmp_path / "rt.nbt"
    VehicleModel.load(str(CARGO)).structure.export(str(cible))
    avant, apres = nbtlib.load(str(CARGO)), nbtlib.load(str(cible))
    assert _blocks(avant) == _blocks(apres)
    assert set(avant.keys()) == set(apres.keys())


def test_l_export_garde_ce_que_le_simulateur_ne_modelise_pas(tmp_path):
    """Colle, entites de contraption, `sub_levels` de Sable : sans eux, le
    vaisseau reimporte en jeu ne s'assemblerait plus."""
    cible = tmp_path / "rt.nbt"
    VehicleModel.load(str(CARGO)).structure.export(str(cible))
    avant, apres = nbtlib.load(str(CARGO)), nbtlib.load(str(cible))
    assert avant["entities"] == apres["entities"]
    assert avant["sub_levels"] == apres["sub_levels"]
    assert int(apres["DataVersion"]) == int(avant["DataVersion"])


def test_une_variante_exportee_se_relit_telle_quelle(tmp_path):
    model = VehicleModel.load(str(CARGO))
    bloc = _some(model, "planks")
    model.delete(bloc)
    cible = export_variant(model, str(tmp_path / "v.nbt"))
    relu = VehicleModel.load(cible)
    assert bloc not in relu.structure.blocks
    assert len(relu.structure) == len(model.structure)
    assert relu.organ("masse").total == pytest.approx(model.organ("masse").total)


def test_un_bloc_deplace_garde_ses_types(tmp_path):
    """Le bloc voyage ENTIER. Le reconstruire depuis son nom perdait le tag
    type, et l'export aurait ecrit des zeros."""
    model = VehicleModel.load(str(CARGO))
    arbre = next(p for p, b in sorted(model.structure) if "tag" in b
                 and "Speed" in (b.get("nbt") or {}))
    libre = _free_cell_next_to(model, arbre)
    model.move(arbre, libre)
    cible = export_variant(model, str(tmp_path / "v.nbt"))
    typed = {tuple(int(x) for x in b["pos"]): b for b in nbtlib.load(cible)["blocks"]}
    assert type(typed[libre]["nbt"]["Speed"]).__name__ == "Float"


def test_la_molette_du_bandeau_s_exporte_avec_le_bon_type():
    """Le bandeau ecrit dans le NBT aplati (la molette d'un bruleur). Le
    retypage prend le type du tag d'origine, ou Int pour une cle nouvelle."""
    tag = nbtlib.tag.Compound({"ScrollValue": nbtlib.tag.Int(3),
                               "Speed": nbtlib.tag.Float(1.5)})
    out = retag({"ScrollValue": 12, "Speed": 2.0, "Nouveau": 7}, tag)
    assert type(out["ScrollValue"]).__name__ == "Int" and int(out["ScrollValue"]) == 12
    assert type(out["Speed"]).__name__ == "Float"
    assert type(out["Nouveau"]).__name__ == "Int"


def test_le_nom_d_export_est_horodate_et_voisin_de_la_source():
    nom = variant_filename("C:/x/cachalot_volant_v4.nbt", "Hélice libérée",
                           when=0)
    assert Path(nom).parent == Path("C:/x")
    assert Path(nom).name.startswith("cachalot_volant_v4--h-lice-lib-r-e--")
    assert Path(nom).suffix == ".nbt"


# --- les quatre gestes (F6.2, F6.3) ------------------------------------------
def test_la_palette_est_restreinte_aux_types_charges(cargo):
    """« Palette restreinte aux types de blocs deja presents dans le fichier »."""
    assert "minecraft:oak_planks" in cargo.palette
    with pytest.raises(ValueError, match="palette"):
        cargo.add((0, 0, 0), "minecraft:diamond_block")


def test_la_palette_survit_a_la_suppression_du_dernier_bloc_d_un_type(cargo):
    rare = min(cargo.palette, key=lambda n: len(cargo.structure.positions_of(n)))
    for pos in sorted(cargo.structure.positions_of(rare)):
        cargo.delete(pos)
    assert not cargo.structure.positions_of(rare)
    assert rare in cargo.palette, "on doit pouvoir le reposer"


def test_un_bloc_pose_est_un_clone_independant(cargo):
    """Copie profonde : regler la molette du clone ne doit pas regler
    l'original."""
    source = next(p for p, b in sorted(cargo.structure) if b.get("nbt"))
    name = cargo.structure.name(source)
    libre = _free_cell_next_to(cargo, source)
    cargo.add(libre, name)
    clone = cargo.structure.blocks[libre]
    clone["nbt"]["__essai__"] = 1
    assert "__essai__" not in (cargo.structure.blocks[source].get("nbt") or {})
    assert "__essai__" not in (cargo.palette[name].get("nbt") or {})


def test_une_case_occupee_est_refusee(cargo):
    """F6.3 : un bloc par case."""
    a, b = sorted(cargo.structure.blocks)[:2]
    with pytest.raises(ValueError, match="superposition"):
        cargo.add(a, cargo.structure.name(b))
    with pytest.raises(ValueError, match="superposition"):
        cargo.move(a, b)


def test_hors_de_la_structure_est_refuse(cargo):
    bloc = next(iter(sorted(cargo.structure.blocks)))
    with pytest.raises(ValueError, match="hors"):
        cargo.move(bloc, (-1, 0, 0))


def test_changer_une_propriete_s_annule(cargo):
    palier = next(p for p, b in sorted(cargo.structure)
                  if "facing" in b.get("props", {}))
    avant = cargo.structure.blocks[palier]["props"]["facing"]
    autre = next(v for v in cargo.property_choices(
        cargo.structure.name(palier), "facing") if v != avant)
    cargo.set_property(palier, "facing", autre)
    assert cargo.structure.blocks[palier]["props"]["facing"] == autre
    cargo.undo()
    assert cargo.structure.blocks[palier]["props"]["facing"] == avant


def test_les_choix_d_axe_sont_toujours_les_trois(cargo):
    arbre = next(p for p, b in sorted(cargo.structure)
                 if "axis" in b.get("props", {}))
    assert cargo.property_choices(cargo.structure.name(arbre), "axis") == [
        "x", "y", "z"]


def test_annuler_refaire_et_retour_a_l_original(cargo):
    """F6.5 : sans limite, et l'original en une commande."""
    depart = dict(cargo.structure.blocks)
    blocs = [p for p, b in sorted(cargo.structure) if "planks" in b["name"]][:12]
    for pos in blocs:
        cargo.delete(pos)
    for _ in blocs:
        assert cargo.undo()
    assert not cargo.undo(), "plus rien a annuler"
    for _ in blocs:
        assert cargo.redo()
    assert cargo.revert() == len(blocs)
    assert cargo.structure.blocks.keys() == depart.keys()
    assert not cargo.redone, "le retour a l'original vide aussi le refaire"


# --- l'invalidation selective (F6.4) ----------------------------------------
@pytest.mark.parametrize("organe", ["trainee", "voiles", "paliers", "cinetique",
                                    "redstone", "ballons"])
def test_supprimer_un_bloc_d_un_organe_le_recalcule(cargo, organe):
    """L'organe des voiles ne regardait que le NOM du bloc touche : une voile
    supprimee, devenue de l'air, le laissait compter une voile fantome."""
    o = cargo.organ(organe)
    bloc = {
        "trainee": lambda: min(o.cells),
        "voiles": lambda: o.sails[0].pos,
        "paliers": lambda: o.bearings[0].pos,
        "cinetique": lambda: min(o.nodes),
        "redstone": lambda: o.levers[0].pos,
        "ballons": lambda: tuple(o.pockets[0].burners[0]["pos"]),
    }[organe]()
    avant = o.recomputes
    cargo.delete(bloc)
    assert o.recomputes > avant, "%s n'a pas vu la suppression" % organe


def test_une_voile_supprimee_ne_compte_plus(cargo):
    voiles = cargo.organ("voiles")
    assert voiles.count == 44
    cargo.delete(voiles.sails[0].pos)
    assert voiles.count == 43
    cargo.undo()
    assert voiles.count == 44


def test_deplacer_un_bloc_de_soute_ne_relance_aucun_remplissage(cargo):
    """Le cas d'ecole du cahier, pour le DEPLACEMENT : deux positions touchees,
    ni l'une ni l'autre etanche ou dans une poche, donc AUCUN flood-fill."""
    from test_invalidation import _bloc_anodin
    ballons = cargo.organ("ballons")
    bloc, _entry = _bloc_anodin(cargo)
    libre = _free_cell_next_to(cargo, bloc)
    if ballons.affected_by(libre):
        pytest.skip("la case libre touche une poche")
    avant = ballons.recomputes
    cargo.move(bloc, libre)
    assert ballons.recomputes == avant


# --- le diff chiffre (F6.6) --------------------------------------------------
def test_le_diff_est_signe_et_part_de_l_etat_charge():
    model = VehicleModel.load(str(CARGO))
    sim = Simulation(model, SimOptions())
    base = Baseline(str(CARGO))
    assert not any(d.bouge for d in variant_diff(sim, base)), \
        "sans edition, rien ne doit bouger"

    bloc = _some(model, "planks")
    masse_bloc = model.props.mass(model.structure.name(bloc))
    model.delete(bloc)
    sim._solve(sim.state)
    deltas = {d.nom: d for d in variant_diff(sim, base)}
    assert deltas["masse"].ecart == pytest.approx(-masse_bloc, abs=1e-6)


def test_le_diff_se_fait_sous_les_memes_commandes():
    """Pousser une manette sans rien editer ne doit rien faire bouger : la
    reference suit les commandes de la session."""
    model = VehicleModel.load(str(CARGO))
    sim = Simulation(model, SimOptions())
    base = Baseline(str(CARGO))
    sim.set_command((15, 13, 20), 15)
    sim._solve(sim.state)
    assert not any(d.bouge for d in variant_diff(sim, base))


def test_le_diff_couvre_les_grandeurs_du_cahier():
    values = measure(Simulation(VehicleModel.load(str(CARGO)), SimOptions()))
    for name in ("masse", "portance max", "centre de masse x", "marge SU",
                 "vitesse de pointe", "altitude d'equilibre"):
        assert name in values, name


def test_sans_poussee_la_vitesse_de_pointe_est_absente_pas_nulle():
    """Un vaisseau sans poussee n'a pas une vitesse de pointe nulle, il n'en a
    pas. Le diff le dit (« ABSENT ») plutot que d'afficher un zero."""
    values = measure(Simulation(VehicleModel.load(str(CARGO)), SimOptions()))
    assert values["vitesse de pointe"] is None


# --- une variante dans un scenario (F6.8) ------------------------------------
def test_les_intentions_se_rejouent(cargo):
    bloc = _some(cargo, "planks")
    libre = _free_cell_next_to(cargo, bloc)
    cargo.move(bloc, libre)
    cargo.delete(_some(cargo, "envelope"))
    ops = ops_to_json(cargo.ops)
    assert [o["op"] for o in ops] == ["deplacer", "supprimer"]

    frais = VehicleModel.load(str(CARGO))
    apply_ops(frais, ops)
    assert frais.structure.blocks.keys() == cargo.structure.blocks.keys()


def test_annuler_retire_l_intention(cargo):
    cargo.delete(_some(cargo, "planks"))
    cargo.delete(_some(cargo, "planks"))
    cargo.undo()
    assert len(cargo.ops) == 1
    cargo.redo()
    assert len(cargo.ops) == 2


def test_deux_variantes_se_comparent_courbe_contre_courbe(tmp_path):
    """F6.8 : le meme vaisseau, la meme manoeuvre, deux structures."""
    from createsim.sim.compare import compare
    model = VehicleModel.load(str(CARGO))
    enveloppe = sorted(model.organ("trainee").cells)[:40]
    base = Scenario(nom="origine", vaisseau="cargo_airship.nbt", ticks=200,
                    echantillon=5, options=SimOptions(initial_gas="vide"),
                    commandes=(Step(0, (15, 13, 20), 9),))
    allegee = Scenario(**{**base.__dict__, "nom": "allegee",
                          "editions": [{"op": "supprimer", "pos": "%d,%d,%d" % p}
                                       for p in enveloppe]})
    chemin = allegee.save(tmp_path / "allegee.json")
    relu = Scenario.load(chemin)
    assert relu.editions == allegee.editions

    result = compare(base.run(), relu.run())
    assert not result.identique, "40 blocs d'enveloppe en moins doivent se voir"


def test_une_session_figee_emporte_sa_variante(cargo):
    sim = Simulation(cargo, SimOptions())
    cargo.delete(_some(cargo, "planks"))
    scenario = Scenario.from_simulation(sim, "essai", "cargo_airship.nbt", 20)
    assert scenario.editions and scenario.editions[0]["op"] == "supprimer"


# --- un ballon perce, puis referme -------------------------------------------
def _breche(model):
    """Un mur de la poche : l'enlever ouvre le ballon."""
    ballons = model.organ("ballons")
    return next(p for p in sorted(ballons.pockets[0].shell)
                if model.props.is_airtight(model.structure.name(p)))


def test_annuler_une_breche_referme_le_ballon(cargo):
    """Defaut de L0 que L5 a fait sortir. Apres une breche, la poche RETRECIT
    — la couche percee s'echappe — et son contour ne passe plus par le trou.
    Remettre le mur, meme par une annulation, n'etait vu par personne : la
    poche restait percee. Le cahier est pourtant clair : un flood-fill est du
    des qu'un bloc etanche est touche."""
    ballons = cargo.organ("ballons")
    intacte = [p.capacity for p in ballons.pockets]
    trou = _breche(cargo)
    cargo.delete(trou)
    assert [p.capacity for p in ballons.pockets] != intacte, "la breche doit se voir"
    assert trou in ballons.leak_zone, "le trou est la ou la poche a fui"
    cargo.undo()
    assert [p.capacity for p in ballons.pockets] == intacte


def test_reposer_le_mur_a_la_main_referme_aussi(cargo):
    ballons = cargo.organ("ballons")
    intacte = [p.capacity for p in ballons.pockets]
    trou = _breche(cargo)
    nom = cargo.structure.name(trou)
    cargo.delete(trou)
    cargo.add(trou, nom)
    assert [p.capacity for p in ballons.pockets] == intacte


def test_le_gaz_suit_les_poches_refaites(cargo):
    """`step_gas` apparie gaz et poches par position : une poche en plus
    tombait de la simulation sans un mot. Le gaz reste ou il etait, au prorata
    des cases d'air reprises ; ce qui a fui par la breche est perdu, et dit."""
    sim = Simulation(cargo, SimOptions())
    avant = sum(sim.state.gas)
    cargo.delete(_breche(cargo))
    message = sim.sync_pockets()
    assert message and "perdus" in message
    assert len(sim.state.gas) == len(cargo.organ("ballons").pockets)
    assert 0 < sum(sim.state.gas) < avant
    for gaz, poche in zip(sim.state.gas, cargo.organ("ballons").pockets):
        assert gaz <= poche.capacity
    assert sim.sync_pockets() is None, "rien de plus a refaire"


def test_la_reference_est_evaluee_a_l_altitude_de_la_session():
    """Sinon la reference reste a son altitude de depart pendant que la
    variante vole plus haut : autre pression, autre trainee, et un diff qui
    montre un ecart que personne n'a cree."""
    model = VehicleModel.load(str(CARGO))
    sim = Simulation(model, SimOptions(altitude=63.0))
    base = Baseline(str(CARGO))
    sim.state.position[1] = 200.0
    sim.state.pressure = sim.curve.at(200.0)
    sim._solve(sim.state)
    assert not any(d.bouge for d in variant_diff(sim, base))


def test_retracer_les_seuls_paliers_touches_egale_tout_retracer(cargo):
    """Le delta des paliers ne retrace que les rotors touches. Il doit donner
    EXACTEMENT ce que donnerait un retracage de tous — sinon un rotor gagnerait
    ou perdrait des voiles en silence."""
    import random
    paliers = cargo.organ("paliers")
    random.seed(7)
    candidats = sorted({p for b in paliers.bearings for p in b.rotor})
    for pos in random.sample(candidats, min(12, len(candidats))):
        if pos in cargo.structure.blocks:
            cargo.delete(pos)

    def signature(organ):
        return [(b.pos, frozenset(b.rotor), b.sails, len(b.contacts), b.reliable)
                for b in organ.bearings]

    partiel = signature(paliers)
    paliers.recompute()
    assert partiel == signature(paliers)


# --- l'invalidation selective ne laisse rien de perime -----------------------
def _fingerprint(model) -> dict:
    """Tout ce que les organes exposent, sous une forme comparable."""
    o = model.organs
    kin = o["cinetique"]
    return {
        "masse": round(o["masse"].total, 6),
        "com": tuple(round(v, 6) for v in o["masse"].com),
        "etanches": frozenset(o["trainee"].cells),
        "levitite": frozenset(o["levitite"].cells),
        "leviers": tuple(sorted((lv.pos, frozenset(lv.targets))
                                for lv in o["redstone"].levers)),
        "roues": tuple((w.pos, w.strength_mul) for w in o["roues"].wheels),
        "paliers": tuple((b.pos, frozenset(b.rotor), b.sails, b.reliable,
                          len(b.contacts)) for b in o["paliers"].bearings),
        "voiles": frozenset(s.pos for s in o["voiles"].sails),
        "noeuds": frozenset(kin.nodes),
        "reseaux": frozenset(frozenset(c) for c in kin.components),
        "sources": tuple(sorted((s.pos, s.rpm) for s in kin.sources)),
        "stress": tuple(sorted((len(n.loads), len(n.generators))
                               for n in o["stress"].networks)),
        "poches": frozenset(frozenset(p.air) for p in o["ballons"].pockets),
    }


def _random_edits(model, count, seed):
    import random
    rng = random.Random(seed)
    positions = sorted(model.structure.blocks)
    for _ in range(count):
        pos = rng.choice(positions)
        if pos not in model.structure.blocks:
            continue
        roll = rng.random()
        try:
            if roll < 0.6:
                model.delete(pos)
            elif roll < 0.85:
                d = rng.choice(((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0),
                                (0, 0, 1), (0, 0, -1)))
                model.move(pos, (pos[0] + d[0], pos[1] + d[1], pos[2] + d[2]))
            else:
                name = rng.choice(sorted(model.palette))
                model.add((pos[0], pos[1] + 1, pos[2]), name)
        except ValueError:
            pass            # case occupee, hors structure : la regle F6.3 joue


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_apres_des_editions_chaque_organe_egale_un_recalcul_complet(tmp_path, seed):
    """Le garde-fou de toutes les optimisations d'invalidation : deltas,
    paliers retraces un par un, propagation guidee par ce que lisent les
    dependants. Un organe perime passerait tous les autres tests."""
    model = VehicleModel.load(str(CARGO))
    _random_edits(model, 40, seed)
    variante = export_variant(model, str(tmp_path / "v.nbt"))
    frais = VehicleModel.load(variante)
    assert _fingerprint(model) == _fingerprint(frais)


def test_le_retour_a_l_original_egale_un_chargement_neuf(cargo):
    _random_edits(cargo, 40, 11)
    assert cargo.edited
    cargo.revert()
    assert _fingerprint(cargo) == _fingerprint(VehicleModel.load(str(CARGO)))
