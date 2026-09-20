# Simulateur de véhicules Create

Banc d'essai **hors-jeu** pour véhicules Create (Aeronautics / Simulated / Offroad / Sable).
Il charge un fichier de structure Minecraft `.nbt`, reconstruit le véhicule qu'il contient,
et le fait fonctionner selon les équations du moteur du jeu — sans lancer Minecraft, sans
monde, sans serveur.

Le but n'est pas de montrer *ce que* le véhicule fait, mais **quelle force en est
responsable**. En jeu, on voit le résultat et jamais la décomposition.

> **État : lot L0 livré** — le noyau physique, sans interface, en ligne de commande.
> Les deux niveaux de validation automatiques passent, ce qui est le critère de
> livrabilité du lot. L'interface 3D (L1) et le bandeau de contrôle (L2) suivront.

---

## Installation

Python ≥ 3.11 (développé sur 3.14.7). Une seule dépendance d'exécution.

```bash
pip install nbtlib
```

Le paquet vit dans `src/` ; sans installation, préfixer les commandes par
`PYTHONPATH=src`.

```bash
pip install -e ".[dev]"
```

## Usage

```bash
createsim analyse mon_vaisseau.nbt --json rapport.json
```

Rapport statique complet : masse, centre de masse, réseau cinétique, bilan Stress Units,
poches de ballon, hélices, traînée, budget de forces, diagnostic.

```bash
createsim run mon_vaisseau.nbt --ticks 6000 --gaz vide --csv trace.csv
```

Simulation temps réel, pas de 1/20 s, avec export de la trace. `--gaz vide` part ballons
vides pour observer la montée. `--altitude`, `--sol`, `--friction` et
`--commande X,Y,Z=N` règlent la situation et les leviers.

```bash
createsim validate
createsim tables show --filtre hot_air
createsim tables import ".../config/create-server.toml" --appliquer
```

## Ce que le logiciel ne fait pas

Ce n'est **pas un éditeur de construction** : on part toujours d'un véhicule existant.
Ce n'est **pas un clone de Minecraft** : pas de monde, pas de terrain, pas de multijoueur.
Ce n'est **pas un moteur de collision** : le véhicule évolue en espace libre, au-dessus
d'un plan de sol optionnel. Il ne simule pas ce qui n'est pas mécanique : ni logistique
d'items, ni fluides, ni électricité, ni recettes.

---

## Architecture

Quatre couches, avec une règle dure : **le noyau ne dépend jamais de l'interface**. Il
tourne sans fenêtre, ce qui le rend testable et rejouable automatiquement.

| Couche | Dossier | Rôle |
|---|---|---|
| Données | `src/createsim/data/` | Tables de constantes et lecteur NBT. Aucune logique physique. |
| Modèle | `src/createsim/model/` | Le véhicule après analyse. Recalculé **par organe**. |
| Simulation | `src/createsim/sim/` | L'état qui évolue. Aucune dépendance à l'affichage. |
| Présentation | `src/createsim/cli.py` | Lit l'état, écrit les commandes, rien d'autre. |

**Distinction essentielle** : le *modèle* ne bouge que lorsqu'on édite un bloc ; l'*état*
change à chaque tick. Remettre à zéro, c'est jeter l'état et garder le modèle — donc
instantané, sans relire le fichier.

### Invalidation sélective

Une édition n'est pas coûteuse en elle-même ; ce qui coûte, c'est ce qu'elle invalide.
Chaque organe déclare ce qui le salit, en O(1). L'édition de blocs elle-même arrive en L5,
mais cette architecture se conçoit au départ : la greffer ensuite reviendrait à réécrire
le modèle.

| Organe | Coût | Condition de recalcul |
|---|---|---|
| Masse, centre de masse | négligeable, différentiel | à chaque édition |
| Traînée | faible, comptage | si le bloc touché est étanche |
| Levitite | faible, comptage | si le bloc touché est de la levitite |
| Redstone | faible | levier, liaison ou consommateur |
| Rotor d'un palier, voiles | moyen, parcours borné | dans le demi-espace avant d'un palier |
| Réseau cinétique, régimes | faible, propagation locale | bloc cinétique ou voisin d'un bloc cinétique |
| Bilan Stress Units | faible, dérivé du réseau | avec le réseau |
| Géométrie des ballons | **élevé, flood-fill** | bloc étanche, ou intérieur/contact d'une poche |

Deux garanties sont testées : le remplissage n'est relancé que sur **la poche concernée**,
et déplacer un coffre dans la soute ne déclenche **aucun** flood-fill.

### Tick

```
commandes → signaux redstone → solveur cinétique → bilan Stress Units
          → (surcharge : consommateurs à l'arrêt, RPM = 0)
          → producteurs de force → somme forces et couples
          → intégration → pression à la nouvelle altitude
```

Le pas est **le tick Minecraft, 1/20 s**. Ce n'est pas un choix d'implémentation mais une
contrainte de fidélité : les constantes de remplissage des ballons sont exprimées en ticks.

---

## Fidélité et traçabilité

**Aucune constante n'est écrite sans sa source.** Chaque valeur des tables porte le fichier
d'où elle vient, et `createsim tables show` l'affiche à la demande. Les tables sont des
fichiers de données externes et versionnés, pas des constantes compilées.

| Table | Contenu |
|---|---|
| `data/tables/masses.json` | classes de masse Sable et règles de résolution |
| `data/tables/pressure.json` | gravité et profil de pression (Hermite cubique) |
| `data/tables/forces.json` | air chaud, levitite, hélices, roues, traînée |
| `data/tables/kinetics.json` | rapports de rotation, générateurs, plafond de régime |
| `data/tables/stress.json` | impact et capacité en Stress Units |
| `data/tables/manifest.json` | versions de mod dont proviennent les tables |

Extraites de `create-1.21.1-6.0.10`, `create-aeronautics-bundled-1.21.1-1.3.1` et
`sable-neoforge-1.21.1-2.0.5`. **Create Aeronautics est en alpha : ces valeurs bougeront.**
`createsim tables import` rejoue une mise à jour depuis les `*-server.toml` de l'instance
et affiche l'écart avant d'écrire quoi que ce soit.

**Mode expert.** Les constantes restent modifiables, mais derrière un interrupteur qui se
coupe : le couper restaure les valeurs sourcées sans redémarrage. Tant qu'il est actif,
tout rapport porte une marque disant que ses chiffres ne reposent plus sur les constantes
du jeu.

**La mesure du jeu prime sur le calcul.** Quand un fichier contient des régimes enregistrés,
le simulateur les affiche à côté des siens et publie l'écart.

---

## Validation

```bash
createsim validate
python -m pytest
```

| Niveau | Critère | Résultat |
|---|---|---|
| 1 — concordance interne | régimes du NBT retrouvés à 0,5 tr/min près | **8/8** sur `cargo_airship`, **53/53** sur `cachalot_volant_v3` |
| 2 — cohérence analytique | `v(t) = v_max(1−e^(−t/τ))`, τ = m/k, à mieux de 1 % | **0,000 %**, τ mesuré 2,260 s vs 2,260 s |
| 2b — transitoire du gaz | remplissage en ~9 s (180 ticks) | 63,2 % du volume en **7,00 s** |

Sur la flotte complète — six vaisseaux portant 131 régimes enregistrés — le solveur
en retrouve **124**, soit 94,7 %.

| Vaisseau | Concordance | Ce qu'il éprouve |
|---|---|---|
| `c1_air_cruiser` | **18/18** | moteur créatif, 147 entraînements à chaîne |
| `cachalot_volant_v3` | **53/53** | contraptions assemblées, jauges, transmission ×16 |
| `cargo_airship` | **8/8** | moulin à voiles, moteurs portables |
| `sledoger_t` | 18/20 | cinq moteurs, conflit de sources |
| `test_01` | 21/24 | banc d'essai |
| `dirt_bike_by_smokeyblade` | 6/8 | moteur surchauffé ; 2 blocs de mods tiers |

La topologie redstone est validée de la même façon : les signaux déduits des leviers sont
comparés à ceux enregistrés dans le NBT — **7/7** sur `cargo_airship`, 16/16 sur
`cachalot_volant_v4`, 18/18 sur `c1_air_cruiser`, sans aucun écart.

Seuils non fonctionnels, mesurés sur `c1_air_cruiser.nbt` (20 659 blocs) :

| Réf. | Seuil | Mesuré |
|---|---|---|
| NF1 | ≥ 20 ticks/s | **5 206** |
| NF3 | chargement + analyse < 3 s | **0,50 s** |
| NF5 | < 1 Go | **38 Mo** |

Les niveaux 3 (confrontation au jeu, Speedometer et Stressometer) et 4 (bibliothèque de
scénarios de non-régression) demandent une mesure humaine ou un corpus : ils viendront
avec L2 et L4.

---

## Ce qui manquait au solveur cinétique

La confrontation aux régimes enregistrés a fait passer la concordance de 30/131 à
124/131. Six mécanismes manquaient — aucun n'était une approximation à raffiner, tous
étaient des absences.

**L'axe de rotation d'une jauge.** Sur un compte-tours ou un manomètre, `facing`
désigne la face d'affichage ; l'axe se dérive de `facing` et `axis_along_first`
(Create `DirectionalAxisKineticBlock`). Les confondre coupait la transmission net :
sur le cachalot, la propagation s'arrêtait à 16 nœuds sur 88. C'est le correctif le
plus rentable du lot — à lui seul il fait passer ce vaisseau de 16/53 à 53/53.

**Le moteur créatif** n'était pas une source. Son réglage vit dans `ScrollValue` —
et non dans `Speed`, qui est la mesure que le solveur doit justement retrouver.

**Les entraînements à chaîne** étaient hors réseau : 147 blocs sur le seul
`c1_air_cruiser`. Deux voisins tournent à l'identique quand la direction qui les
sépare est perpendiculaire à leurs deux axes.

**L'étage ×2 du moteur portable**, que le cahier signalait sans l'expliquer, est la
surchauffe : `GeneratedSpeed` vaut 32 partout, et seul `SuperHeated` distingue les
moteurs à 64. Déduit de la mesure, pas du code — la table le signale comme tel.

**La transmission analogique** était mal modélisée. Le bloc siège à la vitesse de son
*arbre* ; sa roue dentée intégrée tourne à `(15 − signal)/16` de celle-ci. Appliquer
le rapport à chaque arrivée sur le bloc faisait s'emballer toute boucle qui y
repassait, jusqu'au plafond de 256 tr/min. Vérifié sur trois vaisseaux : 16 → 21,33
au signal 3, 32 → 4 au signal 13, 64 → 170,67 au signal 9.

**Les contraptions assemblées.** Quand un palier porte `Running: 1`, son rotor n'est
plus dans le fichier de structure : les voiles sont *inconnaissables*, pas nulles. Le
simulateur reprend alors `LastGenerated` et le dit, plutôt que d'annoncer un moulin à
l'arrêt.

Un sur-raccordement a été corrigé au passage : une boîte de vitesses ne se branche
que sur un voisin qui lui présente un bout d'arbre. Un arbre posé en `x` ne se
raccorde pas sous une boîte par le dessus — le simulateur entraînait à 256 tr/min une
branche que le jeu laisse à l'arrêt.

## Deux corrections apportées au calculateur statique

Le noyau reproduit à l'identique toutes les grandeurs de `/mc-create-engineer` — masse,
centre de masse, capacités de poche, régimes, bilan SU, ratio portance/poids, altitude
d'équilibre — sur `cargo_airship`, `cachalot_volant_v4` et `c1_air_cruiser`. Deux points
divergent, volontairement.

**La constante de temps était en ticks, elle est en secondes.** Sable fait tourner un monde
dont la gravité vaut 11 blocs/s² et qui avance de 1/20 s par tick ; l'accélération est donc
en blocs/s². Le calculateur appliquait `dv = F/m` par tick, sans le facteur `h = 1/20`.
La vitesse de pointe (`v_max = P/k`) et l'altitude d'équilibre sont inchangées, mais la
constante de temps affichée était divisée par 20 — 0,11 s au lieu de 2,26 s sur
`cargo_airship` — et une chute libre aurait atteint −220 blocs/s après une seconde au lieu
de −11. C'est la validation analytique qui l'a révélé : l'écart au modèle continu était
de 23,8 %.

**Le flood-fill des ballons était quadratique.** `upward_fill` reconstruisait l'union
`graph | added | layer` à chaque bloc visité. Remplacée par trois tests d'appartenance —
résultat identique, coût linéaire. L'analyse de `cargo_airship` passe de 1,25 s à 0,20 s.

## Limites assumées

Le logiciel doit le dire plutôt que de produire un chiffre faux.

| Limite | Conséquence | Atténuation |
|---|---|---|
| Tangage et roulis | translation seule (3 ddl) | déséquilibre **statique** affiché : centre de portance, centre de masse, bras de levier |
| Flottaison sur l'eau | les bateaux ne flottent pas | masse, cinétique et propulsion restent valides |
| Moteurs électriques | non reconnus comme sources | signalés comme réseau sans source (F5.7) |
| Comptage des voiles | heuristique bornée au demi-espace avant du palier | drapeau de fiabilité (F6.9) |
| Collisions | traverse les obstacles | plan de sol optionnel seulement |
| Mods tiers | masse par défaut de 1,0 | barre d'erreur affichée (F5.8) |
| Sens de poussée d'une hélice | convention orientation × signe du régime | à confirmer par une mesure en jeu |

Le solveur cinétique reste incomplet sur sept régimes de la flotte, et la concordance
affichée est le garde-fou : le rapport publie le score au lieu de le masquer. Deux
causes subsistent. Les **blocs de mods tiers** — `aeroworks:gyroscope`,
`aeronautics_utility_objects:brass_universal_joint` — dont la cinématique n'est pas
modélisée. Et le **conflit de sources** : quand plusieurs moteurs entraînent un même
réseau à des régimes différents, le solveur retient le premier atteint, là où le jeu
arbitre autrement.

La conclusion garde toujours la même forme : **le simulateur dit où chercher et de combien,
l'essai en jeu tranche.**
