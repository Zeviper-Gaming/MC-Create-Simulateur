# Journal de remise à niveau physique

Ce journal suit la mission « audit physique et remise à niveau ». La partie 1 est le
rapport d'audit tel qu'il a été validé le 29/09/2026 ; la partie 2 consigne chaque étape
exécutée, avec ses résultats chiffrés face à la référence.

## Partie 1 — Audit physique de Sim Create — rapport (phases 1-2) et plan de remise à niveau (phase 3)

### 🔓 Autorisations demandées

**Pendant l'audit : rien n'a été modifié.** Ce fichier est le seul écrit. Le simulateur n'a été lancé
qu'en ligne de commande, sans fenêtre et sans écrire de fichier (`PYTHONDONTWRITEBYTECODE=1`). Les jars
ont été lus en mémoire ou via `javap -cp`, sans rien extraire.

**Pour la phase 4, une étape à la fois, après ton feu vert pour chacune :**

| Fichier | Édition prévue | Étape |
|---|---|---|
| `tools/extraire_masses.py` | création — lit les jars de l'instance (lecture seule) et produit la table | 1 |
| `data/tables/masses_resolues.json` | création — masse par bloc et par état, avec la source de chaque valeur | 1 |
| `src/createsim/data/tables.py` | `BlockProperties.mass(nom, état)` lit la table résolue ; les mots-clés ne servent plus qu'en repli signalé | 1 |
| `src/createsim/data/nbt.py` | lecture des contraptions de `entities` et des `sub_levels` | 2 |
| `src/createsim/model/bearings.py`, `mass.py`, `kinetics.py` | voiles et masse des rotors assemblés | 2 |
| `src/createsim/sim/forces.py`, `sim/tick.py`, `model/balloons.py` | pression lue au bon point (ballon, voile, grappe) : refonte ciblée de l'API des forces | 3 |
| `src/createsim/sim/forces.py`, `model/bearings.py`, `sim/tick.py` | petites hélices, paliers gyroscopiques, anomalie « bloc à force ignoré » | 4 |
| `src/createsim/model/sails.py`, `sim/forces.py` | voiles de moulin assemblées comme surfaces portantes | 5 |
| `src/createsim/sim/forces.py`, `model/levitite.py`, `model/mass.py`, `sim/integrator.py`, `sim/tick.py` | couple de gradient des ballons, plafond de lévitite, inertie du volant, sous-pas, montée en régime | 6-7 |
| `src/createsim/sim/state.py`, `sim/tick.py`, `view/hud.py` | état initial et libellés du bilan (selon ta décision D2) | 8 |
| `tests/test_*.py` | un test par correction, qui échoue avant et passe après | toutes |
| `data/mesures/jeu.json` | tes nouvelles mesures en jeu (V1 à V6) | toutes |
| `data/scenarios/references/*.csv` | re-bénédiction, uniquement après le bilan « avant/après » | toutes |
| `docs/journal-remise-a-niveau.md`, `README.md` | journal des corrections et limites mises à jour | toutes |

**Ce qui n'aura PAS lieu :** aucune écriture dans l'instance CurseForge, dans les jars des mods ni dans
le plugin `minecraft.plugin`. Aucun appel réseau autre que `git push`. Aucune réécriture d'historique,
aucun `--force`. Aucun test supprimé : un test qui fige une loi fausse sera corrigé, avec la raison
écrite. Aucune fonctionnalité nouvelle hors de ce plan, aucune refonte opportuniste, aucune fenêtre
ouverte par les tests. Commit + push vers `origin/main` **seulement à la fin d'une étape que tu as
validée** (déjà autorisé pour ce projet). Rien n'est commité pendant l'audit.

---

### Contexte

Symptôme rapporté : le comportement simulé ne ressemble pas à celui observé en jeu. La consigne est de
ne faire confiance ni au code ni au plan d'origine, et de rattacher chaque loi au code source des mods
ou à une mesure en jeu.

Sources lues pour cet audit, toutes en lecture seule :

- les jars de l'instance « La Bonne Compagnie » : Sable 2.0.5, Aeronautics 1.3.1 et les sous-jars
  Simulated et Offroad, Create 6.0.10 ;
- Minecraft 1.21.1 et NeoForge 21.1.248, pour les tags ;
- les configs `sable-*.toml` et `aeronautics-server.toml` ;
- les 9 `.nbt` de la flotte ;
- le plugin `mc-create-engineer`, source physique d'origine ;
- le code et les tests du simulateur, commit `51a4fed`.

Légende. **Gravité** : 🔴 fausse le verdict (vole ou pas, sens, écart > 10 %) · 🟠 écart chiffrable de
2 à 10 %, ou faux dans certains cas · 🟡 mineur (< 2 % ou cas rare). **Certitude** : *vérifié*
(bytecode, données du mod ou mesure) · *probable* · *hypothèse*.

---

### Synthèse — à lire en premier

1. **Le moteur d'intégration est sain.** Les trois cas analytiques tombent juste au dix-millième :
   chute libre amortie, poussée seule et vitesse limite (§2.3). **Aucune refonte du moteur physique
   n'est justifiée.**
2. **L'écart vient de ce qu'on donne au moteur**, pas de la façon dont il intègre :
   - **Masses** : l'appartenance d'un bloc à une classe de masse est devinée par mots-clés au lieu des
     tags. Le cargo est sous-estimé de **13,1 %** : 102 blocs de fer comptés 1 au lieu de 4.
   - **Rotors assemblés invisibles.** Les contraptions stockées dans `entities` ne sont jamais lues :
     une hélice assemblée — l'état normal en vol — a **0 voile, donc 0 poussée**. Le cachalot v3 perd
     181 blocs (137 voiles de moulin, hélices de 12/16/12 voiles), le cruiser ses 2 hélices.
   - **Pression lue au mauvais point.** Le jeu évalue la pression au barycentre du gaz, le simulateur
     au centre de masse : **+4,9 % de portance** sur le cargo.
   - **Producteurs de force absents** : petites hélices (24 sur le cruiser), paliers gyroscopiques,
     voiles de moulin qui portent comme des ailes, buses, aimants, pivots.
3. **Effet cumulé chiffré** sur le cargo, 1 800 m³ de gaz : le simulateur place l'équilibre du centre de
   masse à **y = 156**. Masse et pression corrigées, le calcul donne **y = 109**, soit **47 blocs
   d'écart** — prédiction vérifiable en jeu (mesure V1). Indice concordant, mais pas une preuve : les
   entités du fichier situent ce centre de masse vers y ≈ 111 au moment de la sauvegarde.
4. **Chargés tels qu'enregistrés, 4 vaisseaux sur 5 ne tiennent pas l'air.** Trois tombent en
   culbutant (brûleurs éteints dans le fichier) et le cruiser coule doucement (portance/poids 0,96 à
   0,98). Seul le cargo vole.
5. **Aucune mesure en jeu ne porte sur une trajectoire.** Les tests vérifient la cohérence interne, 4
   lectures de Stressometer et le sens de poussée. Aucune altitude, vitesse, durée de montée ni
   assiette n'a jamais été confrontée au jeu, et la non-régression fige des sorties sans les valider.
6. **Le plan d'origine (plugin, puis cahier) était juste sur l'essentiel des lois.** Les écarts
   majeurs sont surtout des **erreurs de transposition** dans le simulateur, dont une partie de mon
   fait. Détail au §2.5.

---

### Phase 1 — Le modèle implémenté, reformulé

**Repère et unités.**

- x, y, z sont ceux de la structure, y vers le haut.
- `position` est le centre de masse dans le monde, en blocs.
- Les vecteurs de force sont exprimés dans le monde ; leurs points d'application dans le repère du
  vaisseau (tournés par l'assiette).
- La masse est en « unités Sable » (1 par bloc normal), g = 11 bloc/s², les forces en masse·bloc/s².

**Temps.**

- Pas fixe de 1/20 s.
- Translation : intégration exponentielle exacte, axe par axe, dans le repère du vaisseau
  (`sim/integrator.py`).
- Rotation : amortissement implicite, terme gyroscopique explicite, quaternion (`sim/rotation.py`).
- Gaz : relaxation une fois par tick.

**Forces implémentées** (`sim/forces.py`, `sim/tick.py`) :

- gravité ;
- ballons (par poche) ;
- lévitite ;
- hélices de palier ;
- roues (traction, freinage, dérive) ;
- traînée d'enveloppe et amortissement universel ;
- voiles de coque ;
- contact au sol.

**Couples** : autour du centre de masse. S'y ajoute un amortissement angulaire (tenseur des blocs
étanches + 0,09 × inertie).

**Ce que fait le simulateur** (lancé en ligne de commande, état du fichier, 120 s, sans sol) :

| Vaisseau | Masse sim | Portance max / poids | Après 120 s | Assiette | Poussée d'hélice |
|---|---|---|---|---|---|
| `cargo_airship` | 1 856,8 | 2,42 | vole, y = 156,3, v = 0 | −9,8° / −1,3° | 0 (manette à l'arrêt) |
| `cachalot_volant_v3` | 2 070,8 | 2,31 | **tombe, y = −1 998** | −29° / **46°** | 0 (rotors assemblés : 0 voile) |
| `cachalot_volant_v4` | 2 116,2 | 2,33 | **tombe, y = −1 091** | −19° / −43° | 0 |
| `beeliner_mki_v2` | 1 905,5 | 4,72 | **tombe, y = −868** | 17° / 0° | 0 |
| `c1_air_cruiser` | 16 643,5 | **0,96** | coule, y = 36,9 | **24°** / 1° | 0 (2 rotors assemblés) |

Le bilan annonce une « altitude d'équilibre » calculée à **capacité maximale** (283 pour le cargo),
alors que l'état simulé converge vers 156. Ce libellé trompe (S2).

---

### Phase 2 — Audit physique

#### 2.1 Inventaire des lois, chacune avec sa source

| Loi / constante | Dans le simulateur | Source dans les mods | Statut |
|---|---|---|---|
| Gravité | g = 11 | `DimensionPhysics.DEFAULT_GRAVITY = (0, −11, 0)` | ✅ vérifié |
| Courbe de pression | Hermite, points −38,4 / 63 / 263 / 280 / 320 | `createDefault` + `BezierResourceFunction.evaluateFunction` | ✅ vérifié, écart max 4·10⁻¹⁶ de y = −100 à 339 |
| Amortissement universel | 0,09 × masse, en taux | `createDefault` offset 273 → `Rapier3D.initialize` (rapport frottement §2) | ✅ vérifié ; forme de discrétisation dans le natif, non lue |
| Classes de masse | 0 / 0,25 / 0,5 / 1 / 2 / 4 / 1000 | `data/sable/physics_block_properties/*.json` | ✅ valeurs vérifiées — **❌ appartenance par mots-clés** (C2) |
| Masse nulle sans collision | liste de 21 blocs | `PhysicsBlockPropertyHelper.getMass` → `isSolid` = forme de collision non vide | ✅ principe vérifié ; liste à la main |
| Inertie propre d'un bloc | m/6 par axe | `MassTracker.addBlockInertia` : `identity × m / 6` | ✅ vérifié (sauf `create:flywheel`, C7) |
| Centre de masse d'un bloc | centre du cube | `MassTracker$1` : centre de la forme de collision | ⚠️ écart, C7 |
| Brûleur | molette × signal / 15 | `HotAirBurnerBlockEntity.getGasOutput` | ✅ vérifié |
| Gaz | relaxation 180 ticks, facteur 5, plage 0,05, surplus perdu | `ServerBalloon.updateGasAmounts` + `DefaultLiftingGas` (180 / 180 / 5 / 0,05) | ✅ vérifié, appelé par `tick()` à 20 Hz |
| Portance des ballons | `gaz × 1,5 × p × g`, avec **p au centre de masse** | `ServerBalloon.applyForces` : `F = −g · L · p(barycentre du gaz) · dt`, L = Σ gaz × 1,5 (`hotAirStrength`) | ⚠️ loi vérifiée, **point de pression faux** (C3), **couple de gradient absent** (C6) |
| Gaz vapeur | évent vapeur traité comme brûleur (5 000) | `SteamLiftingGas` : même dynamique, `steamStrength` 1,5 | ✅ probable |
| Lévitite | 10 × g par bloc, plafond de flottaison neutre | matériau flottant `levitite.json` + `FloatingBlockController.applyLift` | ✅ loi vérifiée ; **plafond calculé en accélération** (C11) |
| Traînée d'enveloppe | 0,33 × N × p × v | `balloon_drag.json` + `simple_drag.json` + `applyFriction` | ✅ vérifié (rapport frottement §1) ; p au centre de masse (C3) |
| Voiles de coque | CL 0,475, C∥ 0,75, C₀ 0,0689 ; symétriques C∥ 1,75 | `sable$contributeLiftAndDrag` | ✅ vérifié ; p au centre de masse, sans ω×r (C3, S3) |
| Hélice de palier | `−voiles^1,5 × v × 0,2 × airflow × p`, axe négatif × molette | `getThrust`, `getAirflow` + Sable `getScaledThrust` | ✅ vérifié (port exact du 28/09) |
| Portance des voiles de rotor d'hélice | aucune | mixin Aeronautics : `sable$liftProviders()` renvoie une map vide | ✅ vérifié, cohérent |
| Petites hélices (bois, andésite, smart) | **aucune force** | poussée = RPM × 1,0, airflow 0,1 (plugin §7) | ❌ absent (C4) ; loi à relire au bytecode |
| Palier gyroscopique | **aucune force** (anomalie F5.12) | `GyroscopicPropellerBearingBlockEntity.sable$physicsTick` | ❌ absent (C4) |
| Roues | traction, frein signal/15, dérive, fudgeFriction | `WheelMountBlockEntity.sable$physicsTick` | ✅ vérifié ; `normalMass` approchée (rapport frottement §3) |
| Solveur cinétique | rapports signés, règle de signe des boîtes, ancrage sur les régimes enregistrés | Create `RotationPropagator` | ✅ mesuré aujourd'hui sur la flotte : 100/103 régimes en module (3 écarts sur `test_01`) ; signes 99/103 (4 faux sur le cruiser) |
| Transmission analogique | 16 crans, linéaire | mesure en jeu (niveau 3) | ✅ vérifié en jeu |
| Stress (SU) | configs + 2,0 su/tr/voile | configs, 4 lectures au Stressometer et une loi relevée sur 5 points | ✅ vérifié en jeu |
| Sous-pas physiques | 1/20 s | `sable-server.toml` : `sub_level_substeps_per_tick = 2` → 1/40 s, impulsions F·dt | ⚠️ C9 |
| Amortissement angulaire universel | 0,09 × I (hypothèse de L6) | natif Rapier, non lisible | ❓ non vérifié (C8) |
| Contact au sol | contrainte + Coulomb (conçu le 23/09) | collisions Rapier bloc à bloc, `sable:friction` 1,0, enveloppes « bouncy » 0,5 | ❓ approximation assumée, non vérifiée (C10) |

#### 2.2 Constats

| # | Où | Quoi | Grav. | Certitude | Impact attendu sur l'écart avec le jeu |
|---|---|---|---|---|---|
| **C1** | `data/nbt.py` (ne lit que `blocks` et `palette`), `model/bearings.py` (`sails_known = not assembled`) | Les **contraptions assemblées** de `entities` sont ignorées. Cachalot v3 : 181 blocs (moulin 137 voiles ; hélices 12, 16, 12). Cruiser : 72 blocs (2 × 19 voiles, 4 affûts de canon). Cachalot v2 : 17 blocs. | 🔴 | vérifié | Poussée **nulle** au lieu de ≈ 470 (v3, 16 tr/min) ; masse −2,2 % (v3) ; moulin sans ses voiles. Tout vaisseau sauvegardé en vol est touché. |
| **C2** | `data/tables/masses.json`, `data/tables.py` | Masse devinée par **mots-clés** au lieu des tags, et **état ignoré** (`type=double`). Masse recalculée par les tags réels du modpack : | 🔴 | vérifié | cargo **−13,1 %** (1 856,8 au lieu de 2 135,5), beeliner +1,0 %, cruiser +2,5 %, cachalots 0 %. Cargo : équilibre −35 blocs, temps de réponse plus longs, centre de masse déplacé (fer). |
| **C3** | `sim/tick.py` : une **pression scalaire** `st.pressure` au centre de masse est passée aux ballons, voiles, traînée et amortissement angulaire | Le jeu lit la pression au **barycentre du gaz** (ballons), à **chaque voile** et au centre de chaque **grappe**. | 🟠 | vérifié | Cargo : +4,9 % de portance, **+12 blocs** d'altitude d'équilibre. Effet moindre sur voiles et traînée. |
| **C4** | `sim/forces.py` | **Producteurs de force absents** : petites hélices (24 sur le cruiser), paliers gyroscopiques (4, poussée + stabilisation), ventilateurs/buses (`NozzleHoveringMixin` de Sable, 3), aimants (`MagnetPair`, 4), pivots (`SwivelBearingPlate`, 8 cruiser, 4 cargo), ressorts, volants en roues de réaction (20), recul des canons. | 🔴 cruiser / 🟡 reste | vérifié (existence) | Le verdict du cruiser — vole ou non, assiette 24° — n'est **pas fiable**. Plusieurs de ces blocs sont ignorés **en silence**. |
| **C5** | `model/sails.py` | Les voiles d'un **moulin assemblé** sont des surfaces portantes à chaque sous-pas (`KinematicContraption.sable$liftProviders`, pose locale tournante). | 🟠 | vérifié (mécanisme) / probable (effet) | Cachalot v3 : ≈ +14 % de traînée le long de l'axe du moulin (137 × 0,75 contre 0,33 × 2 288), plus de la portance. |
| **C6** | `sim/forces.py` (ballons) | Couple de gradient absent : `τ = [p₀·r_c + (1/n)·M·∇p] × (−g·L)`, où M est le produit extérieur des cellules de gaz. | 🟡 | vérifié | Cargo à 10° : centre de poussée décalé d'environ 0,26 bloc (≈ 2 % du bras de redressement). |
| **C7** | `model/mass.py` | Centre de masse de chaque bloc pris au centre du cube au lieu du centre de sa forme (dalles, escaliers…). Inertie propre du volant ignorée (2,25 / 1,125 × m). | 🟡 | vérifié | Centre de masse et inertie à ≈ 1 % près. |
| **C8** | `sim/tick.py` `_universal_angular_damping` | L'amortissement universel est aussi appliqué à la rotation (0,09 × I). **Hypothèse** : `Rapier3D.initialize` ne reçoit qu'une valeur, et son usage angulaire est dans la DLL. | 🟠 | hypothèse | Vitesse de retour à l'équilibre d'assiette. |
| **C9** | `sim/integrator.py` | Sable intègre **2 sous-pas de 1/40 s** ; le simulateur fait 1 pas de 1/20 s, exponentiel exact. | 🟡 | vérifié | Négligeable pour τ ≫ 0,05 s. Sensible pour le contact, les roues raides et la rotation. |
| **C10** | `sim/forces.py` `ground_contact` | Contact au sol **conçu**, non tiré du mod. Le jeu passe par des collisions Rapier, un frottement par bloc et une restitution de 0,5 pour les enveloppes. | 🟠 | hypothèse par construction | Posé, rebond, glissade : non comparables au jeu sans mesure. |
| **C11** | `model/levitite.py` | Plafond de la lévitite : le jeu le calcule en **accélération** (masse et inertie inverse, bras de levier compris), le simulateur en flottaison neutre scalaire. | 🟡 | vérifié (structure) | Cruiser : assiette et sustentation près du plafond. |
| **C12** | `sim/forces.py` (hélices) | **Montée en régime** absente : `rotationSpeed` rejoint sa cible par un lissage de facteur 0,4/√voiles à chaque tick. | 🟡 | vérifié | ≈ 0,8 s de retard pour 40 voiles sur une manœuvre de manette. |
| **C13** | `data/nbt.py` | `sub_levels` ignorés : sous-vaisseaux amarrés. | 🟡 | vérifié | Cargo : 3 blocs (un connecteur d'amarrage, un levier et un troisième bloc). |
| **C14** | `model/kinetics.py` | Sens de rotation **non ancré** quand le fichier est sauvegardé moteur à l'arrêt (F5.13) ; 4 signes faux sur le cruiser (F5.14) ; les deux hélices du cargo s'annulent alors que le cargo avance en jeu. | 🟠 | vérifié | Sens et annulation des poussées : question des molettes en suspens (V5). |
| **C15** | `model/kinetics.py` | 3 régimes enregistrés non retrouvés sur 103 (tous sur `test_01`) ; blocs tiers non modélisés (cardan, gyroscope Aeroworks) ; conflits de sources arbitrés autrement que dans le jeu. | 🟡 | vérifié | Régime local faux sur ces réseaux. |

#### 2.3 Cas simples vérifiés analytiquement

| Cas | Référence | Simulé | Verdict |
|---|---|---|---|
| Chute libre amortie (cargo, gaz vide, sans rotation) | `v_lim = −m g / k` local = −14,5451 ; à 1 s : −8,49 | −14,5451 à 20 s ; −8,505 à 1 s (k varie avec la pression) | ✅ intégrateur exact |
| Poussée seule (cachalot v4, hélice centrale à 256 tr/min) | `v = T / k` = −3,464 bloc/s, souffle à 93 % | −3,464 | ✅ |
| Vitesse limite (niveau 2 du cahier) | `τ = m / k` | 0,000 % | ✅ |
| Équilibre statique (cargo, 1 800 m³) | `L · p(y) = m` avec les entrées **du jeu** | simulateur 156,3 · masse seule corrigée 121,5 · pression seule 144,3 · **les deux 109,4** | ❌ entrées fausses, 47 blocs |

Le moteur fait exactement ce qu'on lui demande. L'erreur est dans ce qu'on lui demande.

#### 2.4 Audit logiciel

| # | Constat | Grav. | Certitude |
|---|---|---|---|
| S1 | État par défaut « tel qu'enregistré » : brûleurs éteints, donc 3 vaisseaux sur 5 tombent en culbutant (cachalot v3 à y = −1 998). Ce n'est pas un bug physique, mais l'outil montre d'emblée un comportement que tu ne vois pas en jeu. | 🟠 | vérifié |
| S2 | « Altitude d'équilibre » et « portance/poids » calculées à capacité **maximale** (cargo 283), sans lien avec l'état simulé (156). | 🟠 | vérifié |
| S3 | **Couplage** : toutes les forces reçoivent une pression scalaire et la vitesse linéaire seule. C'est la cause racine de C3, et des voiles et de la traînée qui ignorent ω×r. | 🟠 | vérifié |
| S4 | **Aucune validation en jeu au niveau trajectoire.** 408 tests : cohérence interne, 4 lectures SU, sens de poussée. La non-régression fige des sorties : chaque correction physique ré-bénit les traces sans dire si c'est mieux. | 🔴 méthode | vérifié |
| S5 | La couche données ne lit que `blocks` et `palette` (cause de C1 et C13). | 🟠 | vérifié |
| S6 | `BlockProperties.mass(nom)` ne reçoit pas l'état du bloc : les surcharges `type=double`, `extended=true`, etc. sont impossibles. | 🟡 | vérifié |
| S7 | Un bloc hors table reçoit masse 1 avec l'anomalie F5.8 ✅, mais un **bloc à force non modélisé** (petite hélice, buse, aimant, pivot) est ignoré **sans avertissement**. | 🟠 | vérifié |
| S8 | Tests manquants : masse par tags, contraptions, pression au bon point, producteurs absents, trajectoires de référence. | 🟠 | vérifié |

#### 2.5 Le plan d'origine, franchement

Source physique d'origine : le plugin `mc-create-engineer` (`physique-moteur.md`, `aero_constants.py`),
repris dans le cahier des charges puis dans le plan L0.

- **Juste, et vérifié au bytecode :** gravité, courbe de pression, loi de portance
  `F = −g × L × p(y)`, dynamique du gaz, loi du brûleur, classes de masse, coefficients de voiles,
  module de poussée et airflow des hélices, stress. Le plugin signalait même le couple de gradient des
  ballons (non reproduit), la masse 4 des blocs de métal, le ×2 des dalles doubles et la loi des
  petites hélices.
- **Faux ou incomplet dans le plan :**
  - l'amortissement universel était **omis** (corrigé au lot frottement, ×6,4 sur le cruiser) ;
  - « pression(y) » ne disait pas **quel y**, et l'implémentation a pris le mauvais (C3) ;
  - le sens de poussée « selon son axe » était ambigu (corrigé le 28/09) ;
  - la **résolution des tags était reportée « hors L0 »**, d'où la table à mots-clés ;
  - le périmètre ignorait les contraptions assemblées (l'état de vol), les sous-pas et plusieurs
    producteurs de force.
- **Ma part :** le mot-clé `_block_of_` rate `iron_block` alors que le plugin disait « blocs de métal » ;
  `type=double` est connu du plugin mais pas implémenté ; `entities` n'a jamais été lu ; la pression
  est restée au centre de masse. **Ce sont des erreurs de transposition, pas de loi.**

#### 2.6 Ce que je n'ai pas pu vérifier

- **Le code natif de Rapier** (DLL) : forme exacte de l'amortissement (`1/(1+dt·c)` ou exponentielle),
  application de `universal_drag` à la vitesse angulaire (C8), solveur de contact (C10).
- **Le plafond exact de la lévitite** : structure lue, fin du calcul d'accélération non décodée (C11).
- **La géométrie des poches de ballon** (`BalloonFiller`, reprise du plugin) : non relue face au
  `BalloonBuilder` d'Aeronautics. Une mesure de capacité aux lunettes la validerait.
- **Les pivots, ressorts, aimants, buses et le palier gyroscopique** : existence et point d'entrée
  vérifiés, lois non lues.
- **Les formes de collision des blocs** (centres de masse exacts, blocs « solides ») : elles
  n'existent qu'à l'exécution du jeu.
- **L'altitude du cargo au moment de la sauvegarde** (≈ 111) : ce n'est un indice que s'il était à
  l'équilibre à cet instant. Les cachalots ont été sauvegardés vers y = −60.

---

### Phase 3 — Plan de remise à niveau

Chaque étape est petite, a son test (échoue avant, passe après), un effet attendu chiffré et une
mesure de référence quand il en existe une. **Je m'arrête à la fin de chaque étape** pour te montrer
le bilan avant de passer à la suivante.

| Étape | Type | Contenu | Test (échoue avant → passe après) | Effet attendu |
|---|---|---|---|---|
| **0** | décision + mesures | Toi : mesures V1, V4, V5 (ci-dessous), si possible avant l'étape 1. Elles servent de référence au bilan. | — | Référence « jeu » pour tout le reste |
| **1** 🔴 | correction sur place (couche données) | Masses par **tags résolus** : un extracteur lit les jars de l'instance et produit `masses_resolues.json` (source par valeur, états `type=double` compris). Mots-clés gardés en repli, avec anomalie. | cargo = 2 135,5 (aujourd'hui 1 856,8) ; `oak_slab[type=double]` = 0,5 ; `iron_block` = 4 | Cargo : équilibre 156 → 121 |
| **2** 🔴 | correction sur place (couche données) | Lire les **contraptions** de `entities` (hélice, moulin, affût) et les `sub_levels`, les rattacher au palier (position − facing), y compter voiles et masse. | v3 : voiles 12 / 16 / 12 et poussée > 0 ; masse +46,25 ; moulin à 137 voiles | v3 et cruiser : hélices actives |
| **3** 🟠 | **refonte ciblée de l'API des forces** (justifiée par S3) | Les producteurs reçoivent la pose et une fonction `pression(y monde)` à la place d'un scalaire. Ballons au barycentre du gaz, voiles une par une, grappes à leur centre, ω×r pour voiles et traînée. | cargo : portance à y fixé −4,9 % ; hélices et niveaux 1-2 inchangés | Cargo : équilibre 121 → 109 |
| **4** 🔴 | correction sur place | **Petites hélices** et **palier gyroscopique** (lois relues au bytecode avant d'écrire), et une anomalie « bloc à force non modélisé » listant buses, aimants, pivots, ressorts, volants et canons présents. | cruiser : 24 petites hélices poussent ; l'anomalie liste les blocs ignorés | Verdict du cruiser comparable à V4 |
| **5** 🟠 | correction sur place | Voiles de **moulin assemblé** comme surfaces portantes (loi des voiles existante, orientation du rotor). | v3 : traînée le long de l'axe du moulin +≈ 103 × p | Vitesse de croisière du cachalot |
| **6** 🟡 | correction sur place | Couple de gradient des ballons (M·∇p) ; plafond de lévitite en accélération (après lecture complète) ; inertie propre du volant. | cargo à 10° : décalage du centre de poussée ≈ 0,26 bloc | Assiette à ~2 % près |
| **7** 🟡 | décision D4, puis correction | 2 sous-pas de 1/40 s (gaz par tick, forces par sous-pas) ; montée en régime des hélices. | niveaux 1-2 inchangés ; manœuvre de manette : retard ≈ 0,8 s | Transitoires |
| **8** | décision D2, puis correction | État initial et libellés du bilan (S1, S2). | bilan : « équilibre à l'état actuel » = 156 (puis 109) | Lisibilité |
| **9** | contrôle | Bilan final simulé / référence (V1-V6), non-régression, re-bénédiction justifiée, journal. | — | — |

**Refonte du moteur physique : non justifiée.** L'intégrateur passe les trois cas analytiques. La
seule refonte proposée est l'**interface** entre l'état et les producteurs de force (étape 3), parce
que la pression scalaire est la cause structurelle de C3.

#### Décisions qui t'appartiennent

| # | Question | Ma recommandation |
|---|---|---|
| D1 | Masses tirées de **ton instance** (exactes pour ton modpack, régénérées à chaque mise à jour) ou d'une table figée livrée avec l'outil ? | Extracteur + table générée, versionnée, régénérable à la demande |
| D2 | État initial : « tel qu'enregistré » (fidèle au fichier) ou « en vol stabilisé » (brûleurs réglés pour tenir l'altitude) ? | Garder « tel qu'enregistré », mais afficher en tête « brûleurs éteints : ce vaisseau va tomber » |
| D3 | Producteurs absents : **modéliser** (petites hélices, palier gyroscopique) ou **signaler seulement** (buses, aimants, pivots, ressorts, volants, canons) ? | Modéliser les deux premiers ; signaler le reste |
| D4 | Passer à 2 sous-pas de 1/40 s comme Sable (coût de calcul ×2) ? | Oui : large marge (500 ticks/s sur le cruiser) |
| D5 | Contact au sol : garder l'approximation signalée, ou viser des collisions bloc à bloc ? | Garder l'approximation : les collisions bloc à bloc sont un chantier hors mission |

#### Scénarios de validation — mesures en jeu demandées

| # | Protocole en jeu | Ce que ça tranche | Simulé aujourd'hui → attendu après correction |
|---|---|---|---|
| **V1** | Cargo, levier des brûleurs sur 9, autres leviers comme dans le fichier. Attendre l'équilibre (plus de montée pendant 30 s), relever au F3 le Y d'un bloc repère (le bloc portant le diagramme, local y = 14). | masses (C2) + point de pression (C3) | centre de masse 156,3 → ≈ 109 (le bloc repère : Y ≈ 109) |
| **V2** | Même cargo : durée pour monter du sol à l'équilibre, ou pour gagner 20 blocs. | dynamique du gaz + masse | à chiffrer après l'étape 1 |
| **V3** | Cachalot v3 (rotors assemblés), hélices à fond, en palier : vitesse de croisière (blocs parcourus en 10 s). | C1, C5 | 0 (pas de poussée) → T/k |
| **V4** | Cruiser : tient-il l'altitude sans rien toucher ? Quelle assiette (Y de la proue et de la poupe) ? | C2, C4, C11 | coule, 24° → à comparer |
| **V5** | Cargo : lire aux lunettes la molette des deux paliers d'hélice (« tire / pousse en sens horaire »). | C14 | contradiction levée ou confirmée |
| **V6** | Cargo en V1 : Y de la proue et de la poupe, pour mesurer l'assiette. | rotation, C6 | −9,8° simulés |

V1 et V5 prennent cinq minutes et tranchent à elles seules les deux plus gros constats.

---

### Vérification (phase 4)

À chaque étape :

- le test de la correction échoue avant et passe après (`python -m pytest tests/<fichier> -q`) ;
- `createsim validate` : niveaux 1 et 2 inchangés, sauf effet annoncé dans le tableau ;
- `python -m pytest -q` complet, fenêtres hors écran ;
- `createsim nonregression` : les grandeurs qui bougent doivent être **celles annoncées**, sinon je
  m'arrête et je te le dis ; re-bénédiction seulement après ce constat ;
- une ligne ajoutée au tableau « simulé contre référence » (mesures V1 à V6 quand tu les as fournies) ;
- une entrée au journal `docs/journal-remise-a-niveau.md`.

Bilan final : trois colonnes, **corrigé**, **non vérifié** et **risques**, et le tableau complet
simulé contre référence, avant et après.

## Partie 2 — Journal d'exécution

### Étape 1 — Masses résolues comme le jeu (30/09/2026)

**Constat traité : C2** (🔴, vérifié). La classe de masse d'un bloc était devinée par
mots-clés ; elle est maintenant résolue comme Sable la résout.

**Ce qui a été fait.**

| Fichier | Changement |
|---|---|
| `tools/extraire_masses.py` | nouveau — lit les 118 jars de l'instance en lecture seule, résout 821 tags, reproduit l'ordre du jeu |
| `data/tables/masses_resolues.json` | nouveau — 11 définitions de masse, 3 160 affectations, la source de chacune |
| `src/createsim/data/tables.py` | `ResolvedMasses` ; `BlockProperties.mass(nom, état)` ; `mass_source()` ; mots-clés en repli |
| `src/createsim/model/mass.py` | l'état du bloc est transmis ; le rapport dit d'où viennent les masses |
| `src/createsim/sim/tick.py` | anomalie F5.15 si la table résolue manque |
| `tests/test_masses_resolues.py` | nouveau — 21 tests |

**Source de chaque règle** — lue au bytecode, rien de supposé :

- masse par défaut 1,0 : `PhysicsBlockPropertyTypes.MASS` ;
- priorité par défaut 1 000 : codec de `PhysicsBlockPropertiesDefinition` ;
- masse nulle sans forme de collision : `PhysicsBlockPropertyHelper.getMass` → `isSolid` ;
- ordre : `SimpleJsonResourceReloadListener.prepare` (une `HashMap`, dans le Minecraft
  patché par NeoForge), remplie dans l'ordre de `MultiPackResourceManager.listResources`
  (une `TreeMap`) ; `ResourceLocation.compareTo` (chemin, puis espace de noms) et
  `hashCode` (`31 × espace + chemin`) ; tri stable par priorité dans
  `PhysicsBlockPropertiesDefinitionLoader.apply`.

L'émulation du hachage Java est vérifiée sur des valeurs connues (`"hello"` → 99162322,
`"polygenelubricants"` → −2147483648).

**Deux égalités de priorité tranchées par cet ordre**, écrites dans la table :

- `sable:light` / `sable:normal` → `normal` l'emporte : les 9 dalles de pierre valent 1,0,
  ce pour quoi `normal.json` existe ;
- `sable:light` / `sable:super_heavy` → `super_heavy` l'emporte : `create:cardboard_block`
  vaut 4, là où l'ancienne table le mettait à 1.

**Tests.** Les 21 tests de `test_masses_resolues.py` ont été lancés sur le code d'avant
(reconstitué par `git archive HEAD`) : 19 échouent, les 2 qui passent testent l'émulation du
hachage, indépendante du simulateur. Sur le nouveau code : 21 sur 21.

**Résultats face à la référence.**

| Grandeur | Avant | Après | Référence |
|---|---|---|---|
| Masse du cargo | 1 856,75 | **2 135,50** | tags du jeu : 2 135,5 ✅ — jeu : V0/V1 |
| Centre de masse du cargo | (16,54 ; 14,44 ; 31,41) | (16,50 ; 13,32 ; 34,09) | — |
| Équilibre du cargo, 1 800 m³, y du centre de masse | 156,3 | **121,5** | annoncé par l'audit : 121 ✅ — jeu : V1 (≈ 109 attendu après l'étape 3) |
| Bras de levier du cargo | +2,09 (cabré) | **−0,59** (piqué) | — |
| Tangage d'équilibre du cargo | −9,75° | **+2,57°** | arctan(bras/hauteur) = 2,56° ✅ — jeu : V6 |
| Portance max / poids du cargo | 2,424 | 2,107 | — |
| Cachalots v3 et v4 | 2 070,75 / 2 116,25 | inchangés | audit : 0 % d'écart ✅ |
| Beeliner | 1 905,50 | 1 884,75 | audit 1 886,8 ; l'écart vient des panneaux, sans collision donc sans masse |
| Cruiser | 16 643,50 | 16 157,50 | audit 16 237,5 ; même cause (76 panneaux muraux) |

**Découvert en chemin.** Le `c1_air_cruiser` contient 1 171 blocs de trois mods absents de
l'instance : createdeco (852), copycats (229), createbigcannons (90). Il a été construit
ailleurs. F5.8 le signale, et la mesure V4 n'a de sens que dans son instance d'origine.

**Tests corrigés** — ils figeaient des valeurs issues de la masse devinée, pas une loi :

- `test_modele.py` : masse et centre de masse du cargo (1 856,75 → 2 135,5), rapport
  portance/poids (2,424 → 2,107) et altitude d'équilibre à capacité maximale (283,2 → 249,3) ;
- `test_assiette.py` : tangage d'équilibre du cargo (−9,75° → +2,57°), arc-tangente attendue
  (9,82° → −2,56°) ; le calcul d'inertie « à la main » du test oubliait l'état des blocs.

**Non-régression.** Seuls les trois scénarios du cargo ont bougé, comme annoncé ; les deux
scénarios du cachalot sont identiques. Équilibre 156,3 → 121,5, montée plus lente (+9,5 %),
chute plus rapide (+12,5 %). L'indicateur « montée » du scénario « brûleurs coupés » passe
de 49,25 s à 4,25 s. C'est un artefact : il date le premier passage à 63 % de l'écart entre
départ et fin, et le cargo, plus lourd, plonge maintenant à 22,5 au lieu de 31,4 avant que le
gaz ne le porte. Traces re-bénies, avec cette raison écrite dans chaque scénario.

**Non vérifié.** La liste des blocs sans forme de collision reste tenue à la main : la forme
n'existe qu'en jeu. Les datapacks propres à un monde ne sont pas lus. Aucune définition en
double n'a été trouvée ; s'il y en avait, l'ordre des mods déciderait, et il n'est pas connu
hors du jeu.

**Vérification rapide possible en jeu (V0, une minute).** Sable affiche la masse d'un bloc
dans son info-bulle. Une dalle de pierre doit montrer 1,0, une dalle de chêne 0,25 (0,5 en
dalle double) et un bloc de fer 4,0.
