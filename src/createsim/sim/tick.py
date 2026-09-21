"""La boucle de simulation, et le rapport qu'elle sait produire.

Enchainement d'un tick, tel que le cahier le decrit :

    commandes -> signaux redstone -> solveur cinetique -> bilan Stress Units
              -> (surcharge : consommateurs a l'arret, RPM = 0)
              -> producteurs de force -> somme forces et couples
              -> integration -> pression a la nouvelle altitude
"""
from __future__ import annotations

from ..data.nbt import Pos
from ..model.vehicle import VehicleModel
from . import forces as F
from .atmosphere import FlatGround, NoGround, PressureCurve
from .integrator import TICKS_PER_SECOND, clamp_to_ground, integrate, terminal_motion
from .kinetics import concordance, solve_speeds
from .state import SimOptions, SimState

#: familles LINEAIRES EN v : elles entrent dans l'amortissement du schema, pas
#: dans la somme explicite, sous peine de les compter deux fois et de perdre
#: l'exactitude de l'integration exponentielle.
IMPLICIT_FAMILIES = ("trainee", "frottement")


class Simulation:
    """Le noyau. Tourne sans fenetre, ce qui le rend testable et rejouable."""

    def __init__(self, model: VehicleModel, options: SimOptions | None = None):
        self.model = model
        self.tables = model.tables
        self.options = options or SimOptions()
        self.curve = PressureCurve.from_tables(self.tables)
        self.ground = NoGround()
        self.rebuild_ground()
        self.state = SimState()
        self.reset()

    def rebuild_ground(self) -> None:
        """Refait le sol d'apres les options.

        Changer `options` ne suffisait pas : le sol etait fige a la
        construction, et charger un scenario avec un sol sur une session sans
        sol donnait une chute sans fin. Un seul endroit le construit desormais.
        """
        self.ground = (FlatGround(self.options.ground_altitude,
                                  self.options.ground_friction, True)
                       if self.options.ground_enabled else NoGround())

    # -- raccourcis vers les organes --------------------------------------
    @property
    def mass(self):
        return self.model.organ("masse")

    @property
    def kin(self):
        return self.model.organ("cinetique")

    @property
    def balloons(self):
        return self.model.organ("ballons")

    @property
    def bearings(self):
        return self.model.organ("paliers")

    @property
    def drag(self):
        return self.model.organ("trainee")

    @property
    def levitite(self):
        return self.model.organ("levitite")

    @property
    def redstone(self):
        return self.model.organ("redstone")

    @property
    def stress(self):
        return self.model.organ("stress")

    @property
    def wheels(self):
        return self.model.organ("roues")

    @property
    def sails(self):
        return self.model.organ("voiles")

    # -- remise a zero -----------------------------------------------------
    def reset(self) -> None:
        """Jette l'etat, garde le modele. Instantane, sans relire le fichier."""
        self.rebuild_ground()
        opt = self.options
        st = SimState()
        st.position = [0.0, float(opt.altitude), 0.0]
        st.velocity = list(opt.velocity)
        st.commands = {lv.pos: lv.initial for lv in self.redstone.levers}
        st.signals = self.redstone.signals(st.commands)
        if opt.initial_gas == "vide":
            st.gas = [0.0 for _ in self.balloons.pockets]
        else:
            st.gas = [min(p.demand(st.signals), float(p.capacity))
                      for p in self.balloons.pockets]
        st.pressure = self.curve.at(st.position[1])
        self.state = st
        self._solve(st)

    def set_command(self, lever: Pos, value: int) -> None:
        self.state.set_command(lever, value)

    # -- un tick -----------------------------------------------------------
    def _solve(self, st: SimState) -> None:
        """Signaux, regimes, et l'arret des reseaux en surcharge."""
        st.signals = self.redstone.signals(st.commands)
        solution = solve_speeds(self.kin, st.signals)
        overloaded = self.stress.overloaded_networks(solution.speeds,
                                                     solution.source_rpm)
        st.demand_speeds = solution.speeds if overloaded else {}
        if overloaded:
            # Un reseau en surcharge met ses consommateurs a l'arret (F2.6).
            solution = solve_speeds(self.kin, st.signals, stopped=overloaded)
        st.speeds = solution.speeds
        st.source_rpm = solution.source_rpm
        st.conflicts = solution.conflicts
        st.overloaded = overloaded

    def _damping(self, st: SimState) -> list[float]:
        """L'amortissement par axe : tout ce qui est lineaire en v.

        Isotrope pour la trainee d'enveloppe et l'amortissement universel ;
        anisotrope pour les roues (axe du support et perpendiculaire), les
        voiles (leur normale) et le levitite (vertical / horizontal).
        """
        isotropic = self.drag.coefficient(st.pressure, self.mass.total)
        wheels = F.wheel_damping(self.wheels, st.signals,
                                 self.options.ground_friction, self.tables,
                                 bool(st.on_ground))
        sails = F.sail_damping(self.sails, st.pressure, self.tables)
        levitite = F.levitite_damping(self.levitite, tuple(st.velocity),
                                      self.tables)
        return [isotropic + a + b + c
                for a, b, c in zip(wheels, sails, levitite)]

    def current_forces(self, st: SimState | None = None) -> list[F.Force]:
        st = st or self.state
        t = self.tables
        out: list[F.Force] = []
        out.append(F.gravity(self.mass.total, self.mass.com, t))
        out.extend(F.balloon_forces(self.balloons.pockets, st.gas, st.pressure, t))
        lev = F.levitite_force(self.levitite, self.mass.total, t)
        if lev is not None:
            out.append(lev)
        out.extend(F.propeller_forces(
            self.bearings.of_type("aeronautics:propeller_bearing"), st.speeds, t))
        out.extend(F.wheel_forces(self.model.structure, self.model.props,
                                  st.speeds, st.signals,
                                  self.options.ground_friction, t,
                                  on_ground=bool(st.on_ground)))
        out.append(F.drag_force(self.drag, tuple(st.velocity), st.pressure, t,
                                self.mass.total))
        out.extend(F.wheel_friction_forces(
            self.wheels, tuple(st.velocity), st.signals,
            self.options.ground_friction, t, bool(st.on_ground)))
        out.extend(F.sail_forces(self.sails, tuple(st.velocity), st.pressure, t))
        return out

    def step(self) -> SimState:
        st = self.state
        self._solve(st)
        st.gas = F.step_gas(st.gas, self.balloons.pockets, st.signals, self.tables)
        st.pressure = self.curve.at(st.position[1])
        st.forces = self.current_forces(st)
        # Les forces LINEAIRES EN v sont retirees de la somme explicite : elles
        # entrent dans le schema par leur coefficient, traite exactement. C'est
        # le cas de la trainee, et du frottement des roues depuis qu'il existe.
        external = F.resultant([f for f in st.forces
                                if f.family not in IMPLICIT_FAMILIES])
        integrate(st.position, st.velocity, external, self._damping(st),
                  self.mass.total)
        floor = self.ground.height_at(st.position[0], st.position[2])
        if floor != float("-inf"):
            floor += self.mass.com[1]      # le sol porte le point le plus bas
        st.on_ground = clamp_to_ground(st.position, st.velocity, floor)
        st.pressure = self.curve.at(st.position[1])
        st.tick += 1
        return st

    def run(self, ticks: int, trace=None):
        if trace is not None:
            trace.record(self)
        for _ in range(ticks):
            self.step()
            if trace is not None:
                trace.record(self)
        return self.state

    def run_until_stable(self, max_ticks: int = 20000,
                         tolerance: float = 1e-3, trace=None) -> int:
        """Mode statique : converge vers l'equilibre sans regarder le transitoire."""
        for n in range(max_ticks):
            before = list(self.state.position)
            self.step()
            if trace is not None:
                trace.record(self)
            moved = max(abs(self.state.position[i] - before[i]) for i in range(3))
            if moved < tolerance and self.state.tick > 10:
                return n + 1
        return max_ticks

    # -- rapport -----------------------------------------------------------
    def equilibrium_altitude(self) -> float | None:
        vol_max = sum(min(p.max_demand, p.capacity) for p in self.balloons.pockets)
        if vol_max <= 0:
            return None
        lift = self.tables.get("forces.hot_air_strength")
        target = self.mass.total / (vol_max * lift)
        return self.curve.altitude_for(target)

    def report(self) -> dict:
        st = self.state
        t = self.tables
        m = self.mass
        structure = self.model.structure

        speeds_for_report = dict(st.speeds)
        speeds_for_report.update(self.kin.recorded)   # la mesure du jeu prime

        rep: dict = {
            "fichier": (structure.path or "").replace("\\", "/").split("/")[-1],
            "taille": list(structure.size),
            "blocs": len(structure),
            "provenance": t.provenance(),
        }
        rep.update(m.report())

        conc = concordance(self.kin, st.speeds)
        rep["cinetique"] = {
            **conc,
            "blocs": len(self.kin.nodes),
            "reseaux": len(self.kin.components),
            "sources": [s.report() for s in self.kin.sources],
            "entraines": sum(1 for v in speeds_for_report.values() if abs(v) > 1e-9),
            "regime_max": round(max((abs(v) for v in speeds_for_report.values()),
                                    default=0.0), 2),
            "conflits": st.conflicts,
        }

        # Sur un reseau qui a disjoncte, on publie la DEMANDE : les regimes
        # retenus sont nuls, et « 0 SU demandes » n'expliquerait pas l'arret.
        rep["stress"] = self.stress.budget(speeds_for_report, st.source_rpm,
                                           demand=st.demand_speeds,
                                           overloaded=st.overloaded)
        rep["surcharge"] = any(r["surcharge"] for r in rep["stress"])
        rep["redstone"] = self.redstone.concordance()
        names = self.model.names
        rep["commandes"] = []
        for lv in self.redstone.levers:
            entry = lv.report(st.commands.get(lv.pos, lv.initial))
            given = names.get("levier", lv.pos)
            if given:
                entry["nom"] = given
            rep["commandes"].append(entry)
        if names:
            rep["noms"] = dict(sorted(names.entries.items()))

        rep["ballons"] = self.balloons.report(st.gas)
        rep["levitite"] = self.levitite.report(m.total)
        rep["helices"] = [{**b.report(),
                           "rpm": round(abs(speeds_for_report.get(b.pos, 0.0)), 2),
                           "poussee": round(
                               (b.sails ** t.get("forces.propeller_sail_exponent"))
                               * abs(speeds_for_report.get(b.pos, 0.0))
                               * t.get("forces.propeller_bearing_thrust"), 1)}
                          for b in self.bearings.of_type(
                              "aeronautics:propeller_bearing")]
        rep["roues"] = [f.report() for f in F.wheel_forces(
            structure, self.model.props, speeds_for_report, st.signals,
            self.options.ground_friction, t)]
        rep["voiles"] = self.sails.report()
        rep["suspensions"] = self.wheels.report()
        rep["trainee"] = self.drag.report(st.pressure, self.mass.total)
        rep["trainee"]["amortissement_par_axe"] = [
            round(v, 1) for v in self._damping(st)]
        rep["situation"] = {**self.options.report(), "sol": self.ground.report(),
                            "pression": round(st.pressure, 4)}

        # --- budget de forces ---
        lift_now = sum(b["portance_actuelle"] for b in rep["ballons"])
        lift_max = sum(b["portance_max"] for b in rep["ballons"])
        lev = rep["levitite"]
        if lev:
            lift_now += lev["portance_effective"]
            lift_max += lev["portance_effective"]
        thrust = sum(h["poussee"] for h in rep["helices"])
        traction = sum(f["intensite"] for f in rep["roues"])
        forces = self.current_forces(st)
        lift_forces = [f for f in forces if f.family in ("ballon", "levitite")]

        rep["forces"] = [f.report() for f in forces]
        rep["resultante"] = [round(c, 2) for c in F.resultant(forces)]
        rep["couple_net"] = [round(c, 2) for c in F.torque_about(forces, m.com)]
        rep["bilan"] = {
            "poids": round(m.total * t.get("pressure.gravity"), 1),
            "portance_actuelle": round(lift_now, 2),
            "portance_max": round(lift_max, 2),
            "ratio_portance_poids": round(lift_max / m.total, 3) if m.total else None,
            "vole": lift_max >= m.total,
            "volume_requis_niveau_mer_m3": round(
                m.total / t.get("forces.hot_air_strength"), 1),
            "altitude_equilibre": _round(self.equilibrium_altitude(), 1),
            "poussee_actuelle": round(thrust, 1),
            "traction_roues": round(traction, 1),
            "tangage": F.pitch_balance(
                m.total, m.com, lift_forces, t,
                F.longitudinal_axis(structure.size)),
        }
        total_push = thrust + traction
        rep["mouvement"] = (terminal_motion(total_push,
                                            self.drag.coefficient(1.0, self.mass.total),
                                            m.total) if total_push else None)
        rep["type_probable"] = classify(rep)
        rep["anomalies"] = self.diagnose(rep)
        return rep

    # -- diagnostic (F5) ---------------------------------------------------
    def diagnose(self, rep: dict | None = None) -> list[dict]:
        """Les defauts invisibles en jeu, qui coutent des heures."""
        rep = rep or {}
        out: list[dict] = []
        names = self.model.names

        for b in self.bearings.bearings:
            if b.contacts:
                out.append({
                    "code": "F5.1", "gravite": "grave",
                    "titre": "rotor de palier en contact avec la coque",
                    "organe": names.describe("palier", b.pos,
                                             "palier %s" % (list(b.pos),)),
                    "detail": ("le palier en %s touche la structure : en jeu il "
                               "refuse de s'assembler" % (list(b.pos),)),
                    "blocs": [c["vers"] for c in b.contacts[:8]],
                })
        for i, p in enumerate(self.balloons.pockets):
            if p.max_demand > p.capacity:
                out.append({
                    "code": "F5.2", "gravite": "moyen",
                    "titre": "poche de ballon saturee",
                    "organe": names.describe("poche", i, "poche %d" % (i + 1)),
                    "detail": ("poche %d : demande %.0f m3 pour %d m3 de capacite, "
                               "le surplus est perdu"
                               % (i + 1, p.max_demand, p.capacity)),
                    "blocs": [list(b["pos"]) for b in p.burners],
                })
            elif p.capacity and p.max_demand < p.capacity * 0.5:
                out.append({
                    "code": "F5.3", "gravite": "faible",
                    "titre": "poche sous-exploitee",
                    "organe": names.describe("poche", i, "poche %d" % (i + 1)),
                    "detail": ("poche %d : %.0f m3 demandes sur %d disponibles, "
                               "de la portance dort" % (i + 1, p.max_demand,
                                                        p.capacity)),
                    "blocs": [list(b["pos"]) for b in p.burners],
                })
        for r in (rep.get("stress") or []):
            if r["surcharge"]:
                out.append({
                    "code": "F5.4", "gravite": "grave",
                    "titre": "reseau cinetique en surcharge",
                    "detail": ("%.0f SU demandes pour %.0f SU disponibles : "
                               "le reseau disjoncte et TOUS ses consommateurs "
                               "s'arretent, pas seulement celui de trop"
                               % (r["stress_su"], r["capacite_su"])),
                    "blocs": [c["pos"] for c in r["consommateurs"][:8]],
                })
            elif r["sans_source"]:
                out.append({
                    "code": "F5.7", "gravite": "limite du modele",
                    "titre": "consommateurs sans source identifiee",
                    "detail": ("le solveur n'a pas relie ce reseau a son "
                               "generateur. C'est une limite du modele, PAS un "
                               "defaut du vaisseau."),
                    "blocs": [c["pos"] for c in r["consommateurs"][:8]],
                })
        for c in self.state.conflicts:
            out.append({"code": "F5.5", "gravite": "moyen",
                        "titre": "conflit de regime entre deux sources",
                        "detail": "%s : %s" % (c["bloc"], c["regimes"]),
                        "blocs": [c["pos"]]})
        for key, sides in self.redstone.channels.items():
            if not sides["tx"] or not sides["rx"]:
                out.append({
                    "code": "F5.6", "gravite": "faible",
                    "titre": "liaison redstone sans correspondant",
                    "detail": ("canal %s : %d emetteurs, %d recepteurs"
                               % (list(key), len(sides["tx"]), len(sides["rx"]))),
                    "blocs": [list(p) for p in (sides["tx"] + sides["rx"])[:8]],
                })
        if self.mass.unknown_total:
            out.append({
                "code": "F5.8", "gravite": "limite du modele",
                "titre": "blocs hors table",
                "detail": ("%d blocs retombent sur la masse par defaut de 1,0 ; "
                           "le ratio portance/poids porte cette incertitude"
                           % self.mass.unknown_total),
                "blocs": [],
            })
        for pos in sorted(set(self.stress.unknown_rotors)):
            out.append({
                "code": "F5.9", "gravite": "limite du modele",
                "titre": "impact d'helice sous-estime",
                "organe": names.describe("helice", pos, "helice %s" % list(pos)),
                "detail": ("rotor assemble : ses voiles ne sont plus dans le "
                           "fichier, et l'impact d'un palier se compte PAR "
                           "VOILE. Le SU affiche pour ce reseau est un "
                           "PLANCHER, pas une estimation."),
                "blocs": [list(pos)],
            })
        if self.wheels.count:
            out.append({
                "code": "F5.10", "gravite": "limite du modele",
                "titre": "masse portee par roue approchee",
                "detail": ("le moteur tire la masse portee de la matrice de "
                           "masse inverse au point de contact ; faute de "
                           "tenseur d'inertie complet (L6), elle est ici "
                           "repartie a parts egales entre les %d roues."
                           % self.wheels.count),
                "blocs": [list(w.pos) for w in self.wheels.wheels[:8]],
            })
        if self.levitite.cells:
            out.append({
                "code": "F5.11", "gravite": "limite du modele",
                "titre": "melange lent/rapide du levitite approche",
                "detail": ("le facteur gaussien du moteur porte une correction "
                           "d'etalement spatial de la grappe, ignoree ici : on "
                           "garde exp(-1,5 (v/3)^2). L'ecart se voit surtout "
                           "sur un vaisseau tres etale."),
                "blocs": [list(p) for p in sorted(self.levitite.cells)[:8]],
            })
        for b in self.bearings.bearings:
            if not b.reliable and not b.contacts:
                out.append({
                    "code": "F6.9", "gravite": "limite du modele",
                    "titre": "comptage de voiles incertain",
                    "detail": ("palier en %s : le parcours a probablement mordu "
                               "sur la coque, %d voiles est un majorant"
                               % (list(b.pos), b.sails)),
                    "blocs": [list(b.pos)],
                })
        return out


def classify(rep: dict) -> str:
    if rep.get("roues"):
        return "vehicule terrestre"
    if rep.get("levitite") and rep.get("ballons"):
        return "aeronef mixte (ballon + levitite)"
    if rep.get("levitite"):
        return "aeronef a levitite"
    if rep.get("ballons"):
        return "dirigeable"
    if rep.get("helices"):
        return "aeronef a propulsion seule"
    return "contraption sans systeme de sustentation detecte"


def _round(v, n):
    return None if v is None else round(v, n)
