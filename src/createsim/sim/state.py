"""L'etat de simulation : ce que l'utilisateur fait du vehicule.

Il change a chaque tick. Le modele, lui, ne bouge que si on edite un bloc.
Remettre a zero, c'est jeter cet etat et garder le modele — donc instantane,
sans relire le fichier.

`position` est celle du CENTRE DE MASSE dans le monde ; les points d'application
des forces restent en coordonnees locales de la structure, qui est ce que la
vue 3D dessine.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..data.nbt import Pos

Vec = tuple[float, float, float]


@dataclass
class SimOptions:
    """La « situation » du cahier : ce qui entoure le vehicule."""

    altitude: float = 63.0
    velocity: Vec = (0.0, 0.0, 0.0)
    ground_altitude: float = 0.0
    ground_enabled: bool = False
    ground_friction: float = 1.0
    initial_gas: str = "nbt"        # "nbt" (regime enregistre) ou "vide"
    #: tangage et roulis par les couples (F2.3). Coupe, le vaisseau reste a
    #: plat et ne garde que ses trois degres de liberte en translation.
    rotation: bool = True

    def report(self) -> dict:
        return {"altitude": self.altitude, "vitesse_initiale": list(self.velocity),
                "sol": {"actif": self.ground_enabled,
                        "altitude": self.ground_altitude,
                        "friction": self.ground_friction},
                "gaz_initial": self.initial_gas,
                "rotation": self.rotation}


@dataclass
class SimState:
    """L'etat mutable, et rien d'autre."""

    tick: int = 0
    position: list = field(default_factory=lambda: [0.0, 63.0, 0.0])
    velocity: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    commands: dict = field(default_factory=dict)
    gas: list = field(default_factory=list)
    on_ground: bool = False

    # derniers resultats du tick, pour lecture par la presentation
    #: attitude (quaternion w, x, y, z) et vitesse angulaire, monde (L6)
    orientation: tuple = (1.0, 0.0, 0.0, 0.0)
    angular_velocity: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    torque: tuple = (0.0, 0.0, 0.0)

    speeds: dict = field(default_factory=dict)
    source_rpm: dict = field(default_factory=dict)
    signals: dict = field(default_factory=dict)
    forces: list = field(default_factory=list)
    pressure: float = 1.0
    overloaded: set = field(default_factory=set)
    #: regimes AVANT l'arret pour surcharge : sans eux, un reseau qui disjoncte
    #: se lit « 0 SU demandes, pas de surcharge » et rien n'explique l'arret.
    demand_speeds: dict = field(default_factory=dict)
    conflicts: list = field(default_factory=list)

    @property
    def seconds(self) -> float:
        return self.tick / 20.0

    @property
    def altitude(self) -> float:
        return self.position[1]

    @property
    def speed(self) -> float:
        return sum(v * v for v in self.velocity) ** 0.5

    @property
    def horizontal_speed(self) -> float:
        return (self.velocity[0] ** 2 + self.velocity[2] ** 2) ** 0.5

    @property
    def vertical_speed(self) -> float:
        return self.velocity[1]

    def set_command(self, lever: Pos, value: int) -> None:
        self.commands[lever] = max(0, min(15, int(value)))

    def snapshot(self) -> dict:
        return {
            "tick": self.tick,
            "temps_s": round(self.seconds, 3),
            "altitude": round(self.altitude, 3),
            "position": [round(v, 3) for v in self.position],
            "vitesse": [round(v, 3) for v in self.velocity],
            "vitesse_horizontale": round(self.horizontal_speed, 3),
            "vitesse_verticale": round(self.vertical_speed, 3),
            "pression": round(self.pressure, 4),
            "gaz": [round(g, 2) for g in self.gas],
            "regime_max": round(max((abs(v) for v in self.speeds.values()),
                                    default=0.0), 2),
            "au_sol": self.on_ground,
            "reseaux_en_surcharge": sorted(self.overloaded),
        }
