"""Niveau 2 de validation : coherence analytique.

La trainee etant lineaire, la vitesse a une solution exacte :

    v(t) = v_max (1 - exp(-t/tau))    avec v_max = P/k et tau = m/k

L'integrateur doit y coller a mieux de 1 %. Un ecart signale une erreur de
schema ou de pas de temps.
"""
from __future__ import annotations

import math

from createsim.sim.integrator import DT, TICKS_PER_SECOND, integrate
from createsim.validation import TOLERANCE_ANALYTIC, level2_analytic


def _course(mass, k, thrust, ticks):
    position, velocity = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    out = []
    for _ in range(ticks):
        integrate(position, velocity, (thrust, 0.0, 0.0), k, mass)
        out.append(velocity[0])
    return out


def test_pas_de_temps_est_le_tick_minecraft():
    """Ce n'est pas un choix d'implementation mais une contrainte de fidelite."""
    assert TICKS_PER_SECOND == 20.0
    assert DT == 0.05


def test_courbe_suivie_a_mieux_de_un_pourcent():
    mass, k, thrust = 1856.75, 821.7, 3238.2
    v_max, tau = thrust / k, mass / k
    worst = 0.0
    for n, v in enumerate(_course(mass, k, thrust, 1200), start=1):
        exact = v_max * (1.0 - math.exp(-(n * DT) / tau))
        worst = max(worst, abs(v - exact) / v_max)
    assert worst < TOLERANCE_ANALYTIC, "ecart %.4f %%" % (worst * 100)


def test_vitesse_de_pointe_est_poussee_sur_k():
    mass, k, thrust = 1856.75, 821.7, 3238.2
    final = _course(mass, k, thrust, 4000)[-1]
    assert abs(final - thrust / k) / (thrust / k) < 1e-6


def test_constante_de_temps_est_m_sur_k_en_secondes():
    """La correction de convention : tau est en SECONDES, pas en ticks."""
    mass, k, thrust = 1856.75, 821.7, 3238.2
    v_max, tau = thrust / k, mass / k
    seuil = v_max * (1.0 - 1.0 / math.e)
    course = _course(mass, k, thrust, 4000)
    previous = 0.0
    measured = None
    for n, v in enumerate(course, start=1):
        if v >= seuil:
            span = v - previous
            measured = (n - 1 + (seuil - previous) / span) * DT if span else n * DT
            break
        previous = v
    assert measured is not None
    assert abs(measured - tau) / tau < TOLERANCE_ANALYTIC
    assert 2.0 < measured < 2.5, "tau attendu autour de 2,26 s, obtenu %.3f" % measured


def test_stabilite_sur_un_vaisseau_leger_et_tres_etanche():
    """k.h/m > 2 ferait diverger un Euler explicite. Le schema doit tenir."""
    mass, k, thrust = 10.0, 5000.0, 1000.0
    course = _course(mass, k, thrust, 500)
    assert all(math.isfinite(v) for v in course)
    assert abs(course[-1] - thrust / k) < 1e-9


def test_sans_trainee_l_acceleration_est_constante():
    course = _course(1000.0, 0.0, 1000.0, 20)
    assert abs(course[0] - 1.0 * DT) < 1e-12
    assert abs(course[-1] - 20 * DT) < 1e-9


def test_niveau2_via_la_validation(tables):
    results = level2_analytic(tables)
    assert results
    for r in results:
        assert r["passe"], r["detail"]
