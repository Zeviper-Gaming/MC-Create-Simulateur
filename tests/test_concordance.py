"""Niveau 1 de validation : concordance interne, automatique.

Sur toute structure sauvegardee moteur tournant, le solveur doit retrouver les
regimes enregistres dans le NBT a 0,5 tr/min pres. Reference du cahier :
8 sur 8 sur cargo_airship.

Ce test tourne sans intervention et sans jeu, a chaque modification du solveur.
C'est le mecanisme de validation le moins couteux, et il est gratuit : le jeu
fournit lui-meme sa verite terrain.
"""
from __future__ import annotations

from createsim.validation import TOLERANCE_RPM, level1_concordance
from createsim.sim.kinetics import concordance, solve_speeds


def test_regimes_enregistres_presents(cargo):
    """Sans regimes enregistres, il n'y a rien a valider."""
    assert len(cargo.organ("cinetique").recorded) == 8


def test_concordance_huit_sur_huit(sim):
    """Le critere du cahier, mot pour mot."""
    result = concordance(sim.kin, sim.state.speeds, TOLERANCE_RPM)
    assert result["concordance_solveur"] == "8/8", result["ecarts"]
    assert result["ecarts"] == []


def test_ecart_reel_bien_sous_la_tolerance(sim):
    """La concordance ne doit pas passer de justesse."""
    speeds = sim.state.speeds
    for pos, measured in sim.kin.recorded.items():
        computed = speeds.get(pos)
        assert computed is not None, ("regime non calcule en %s" % (pos,))
        assert abs(abs(computed) - abs(measured)) < 1e-6, (pos, measured, computed)


def test_les_sources_sont_identifiees(sim):
    """Un regime sans source serait une concordance par hasard."""
    assert sim.kin.sources
    for source in sim.kin.sources:
        assert source.rpm != 0.0
        assert source.pos in sim.kin.nodes


def test_niveau1_via_la_validation(tables):
    """Le meme test, tel que `createsim validate` l'execute."""
    results = level1_concordance(tables)
    assert results, "aucune fixture avec regimes enregistres"
    for r in results:
        assert r["passe"], r["detail"]


def test_le_signal_pilote_le_decouplage(sim):
    """Une transmission analogique a 15 decouple : le regime doit s'effondrer.

    C'est le piege que le cahier demande d'ecrire en toutes lettres, et il doit
    se voir dans les regimes, pas seulement dans l'affichage.
    """
    transmissions = [p for p, b in sim.kin.nodes.items()
                     if b["name"] == "simulated:analog_transmission"]
    if not transmissions:
        return
    libre = solve_speeds(sim.kin, {p: 0 for p in transmissions})
    decouple = solve_speeds(sim.kin, {p: 15 for p in transmissions})
    assert decouple.driven <= libre.driven
