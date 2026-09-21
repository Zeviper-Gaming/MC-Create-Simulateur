# Les modèles de frottement de Create/Sable — relevé au bytecode

**Méthode.** Rien dans ce rapport ne vient d'un résumé ni d'une documentation. Les jars de
l'instance ont été dépaquetés et désassemblés à `javap`, depuis
`mods/create-aeronautics-bundled-1.21.1-1.3.1.jar` (qui contient en jar-in-jar
`aeronautics`, `offroad` et `simulated`), `mods/sable-neoforge-1.21.1-2.0.5.jar` et
`mods/create-1.21.1-6.0.10.jar`. Les datapacks JSON ont été lus directement.

Chaque constante ci-dessous porte la classe et le décalage où elle a été lue. Deux points
seulement restent des déductions, et ils sont signalés comme tels.

**Découverte de fond qui change le cadre :** le moteur physique est **Rapier** (Rust), lié
en natif via `dev.ryanhcode.sable.sable-sable_rapier`. Sable ne calcule pas l'intégration —
il prépare des forces et les remet à Rapier. Cela tranche plusieurs ambiguïtés d'un coup.

---

## 🔓 Ce que ce rapport propose de modifier

**Appliqué le 2026-09-21 après le TOP.** Voir la section 9 pour ce que l'application a
corrigé dans ce rapport lui-même. Récapitulatif, par ordre d'impact décroissant :

| # | Chemin | Édition | Impact |
|---|---|---|---|
| 1 | `sim/tick.py`, `model/drag.py`, `data/tables/pressure.json` | Amortissement universel | **τ du cruiser ÷ 6,4** |
| 2 | `sim/forces.py` (`wheel_forces`) | Correction d'un bug | roue freinée à fond |
| 3 | `sim/forces.py`, `data/tables/forces.json` | `fudgeFriction` | glace, boue, meule |
| 4 | `sim/forces.py`, `sim/integrator.py`, `model/wheels.py` (création) | Frottement dynamique | distance d'arrêt, virage |
| 5 | `sim/forces.py`, `model/sails.py` (création), `data/tables/forces.json` | Portance et traînée des voiles | traînée seule sur la flotte : ses 60 voiles de coque sont symétriques |
| 6 | `sim/forces.py`, `data/tables/forces.json` | Traînée du levitite | cruiser : τ ≈ 0,45 s à l'arrêt |
| 7 | `data/scenarios/references/*.csv` | Re-bénédiction après #1 | inévitable |

**Ce qui n'aura PAS lieu :** aucune écriture dans un `.nbt`, dans l'instance CurseForge ou
dans les jars ; aucun appel réseau ; aucune réécriture d'historique. Commit et push
`origin/main` comme d'habitude, tests au vert d'abord.

---

## 1. La traînée des blocs étanches — **exacte, confirmée**

`data/aeronautics/physics_block_properties/balloon_drag.json` applique à `#aeronautics:airtight` :
`floating_material = aeronautics:simple_drag`, `floating_scale = 0.33`.

`data/aeronautics/floating_materials/simple_drag.json` ne déclare que
`scale_with_pressure: true`, `lift_strength: 0.0`, `fast_vertical_friction: 1.0`,
`fast_horizontal_friction: 1.0`. Les champs absents prennent leur défaut, et le codec de
`FloatingBlockMaterial` (lambda$static$0, offsets 90/112/134/156/178) les met **tous à
`dconst_0`** : `transition_speed`, `slow_vertical_friction`, `slow_horizontal_friction`
valent 0.

Dans `FloatingBlockController.applyFriction`, la matrice de traînée est construite par
`getGravityMatrix(gravité, frottement_vertical, frottement_horizontal, out)` :

```
M = (ĝ ⊗ ĝ) × (h − v)  −  h × I
```

Pour une vitesse le long de la gravité on obtient `−v`, perpendiculairement `−h`. Avec
`v = h = 1` la matrice se réduit à **`−I`**, exactement comme annoncé. Deux gardes
`if (transitionSpeed == 0) → 0` (offsets 73 et 384) annulent la contribution lente.

```
F = −(0,33 × N_étanches × pression) × v
```

**C'est ce que fait déjà `DragOrgan.coefficient()`. Aucune correction.** Trois réserves
tout de même, documentées plus bas : la somme est un `totalScale` (somme des
`floating_scale` bloc par bloc, pas un comptage × 0,33), la traînée produit aussi un
**couple**, et elle s'applique **par grappe de matériau**.

---

## 2. La traînée universelle — **le plus gros écart du simulateur**

`DimensionPhysics.createDefault` (offset 273) : `ldc float 0.09f`, passé en
`Optional.of(...)` au champ `universalDrag`.

Sa consommation se lit en deux sauts :

```
SubLevelPhysicsSystem.initialize, offset 19
    DimensionPhysicsData.getUniversalDrag(level)  →  slot 2
SubLevelPhysicsSystem.initialize, offset 36
    PhysicsPipeline.init(gravité, drag)
RapierPhysicsPipeline.init, offset 24
    Rapier3D.initialize(gx, gy, gz, drag)  →  natif
```

**`universal_drag` est un paramètre de la scène physique, remis à Rapier à côté de la
gravité.** Ce n'est ni une traînée par bloc, ni une propriété de matériau : c'est
l'amortissement linéaire du corps rigide, exprimé **par seconde**. Rapier l'applique sous
la forme `v ← v / (1 + dt·c)`, soit une décroissance exponentielle de constante de temps
`τ = 1/c = 11,1 s`.

> La forme exacte de la discrétisation est le premier des deux points non lus directement
> (le code est en Rust, dans une DLL). Elle ne change rien : `1/(1+dt·c)` et `1−dt·c`
> donnent la même constante de temps. Ce qui est **certain** par le bytecode, c'est que le
> terme est global au corps, indépendant du nombre de blocs, et en s⁻¹.

### Conséquence chiffrée

Mon amortissement entre comme un coefficient de force (`rate = k/m × dt`), celui de Rapier
comme un taux. Pour les réconcilier il faut ajouter `k_universel = 0,09 × masse` :

| Vaisseau | masse | k actuel | τ actuel | k corrigé | τ corrigé | rapport |
|---|---|---|---|---|---|---|
| `cargo_airship` | 1 857 | 821,7 | 2,26 s | 988,8 | 1,88 s | ×1,20 |
| `cachalot_volant_v3` | 2 071 | 755,0 | 2,74 s | 941,4 | 2,20 s | ×1,25 |
| `cachalot_volant_v4` | 2 116 | 755,0 | 2,80 s | 945,5 | 2,24 s | ×1,25 |
| `c1_air_cruiser` | 16 644 | 276,9 | **60,11 s** | 1 774,8 | **9,38 s** | **×6,41** |

Le cruiser porte 20 659 blocs pour seulement 839 étanches : sa traînée d'enveloppe est
dérisoire devant sa masse, et l'amortissement universel devient l'essentiel de son
freinage. Son plafond est `τ = 11,1 s`, atteint quand la traînée d'enveloppe est nulle.

Les vitesses de croisière baissent dans le même rapport : ×0,83 pour le cargo,
**×0,16 pour le cruiser**.

### Pourquoi la correction du document de passation est à écarter

Elle propose `k += 0,09 × N_total`. C'est la bonne intuition — le terme compte énormément —
mais la mauvaise forme : 29 % d'erreur sur le cargo, 20 % sur le cruiser, et faux par
construction dès qu'un vaisseau s'écarte du ratio masse/bloc ≈ 1. Le document l'admettait
d'ailleurs en réserve. Le bytecode tranche : c'est la **masse**, parce que c'est un taux.

---

## 3. Les roues Offroad — trois écarts, dont un bug

Tout vient de `WheelMountBlockEntity.sable$physicsTick`, offsets 100 à 696.

### La suspension (offsets 100–170)

```java
normalMass        = 1 / massTracker.getInverseNormalMass(contact, UP)
stiffness         = strength.getValue()                    // molette, ScrollValue
normalMassScaling = min(normalMass / stiffness, 1) × 10
strengthMul       = stiffness × normalMassScaling × 2      // = 20 × min(normalMass, stiffness)
springStrength    = stiffness × normalMassScaling × 40
dampingStrength   = stiffness × normalMassScaling
```

`normalMass` n'est pas `masse/nb_roues` : c'est la masse effective au point de contact selon
l'axe vertical, tirée de la matrice de masse inverse du corps. C'est le second point non lu
directement — l'approximation `masse/nb_roues` est raisonnable au premier ordre, mais elle
ignore le tenseur d'inertie.

**Conséquence de conception, qui mérite d'être montrée :** sous saturation,
`strengthMul = 20 × normalMass` et la décélération devient `20 × coef × v`, **indépendante
de la masse**, comme le frottement réel. Au-delà, `strengthMul` plafonne à
`20 × stiffness` : *un véhicule surchargé sur suspension molle ne freine plus*.

### Le frottement du sol (offsets 481–520)

```java
touchingFriction = fudgeFriction(PhysicsBlockPropertyHelper.getFriction(blocSousLaRoue))
touchingFriction = max(touchingFriction, tire.minimumFriction())
```

et, offsets 0–16 de `fudgeFriction` :

```java
public static double fudgeFriction(double f) {
    return f < 1.0 ? 0.1 + 0.9 * f : f;
}
```

**Ce n'est pas `min(friction, 1)`.** C'est un remappage qui relève les frottements faibles
et laisse passer les forts :

| Bloc | `sable:friction` | après `fudgeFriction` | mon modèle |
|---|---|---|---|
| glace, glace bleue | 0,00 | **0,10** | 0,00 |
| meule | 0,05 | **0,145** | 0,05 |
| boue | 0,25 | **0,325** | 0,25 |
| défaut | 1,00 | 1,00 | 1,00 |
| sable des âmes, miel, tapis roulant | 1,65 | **1,65** | 1,00 (écrasé) |

Sur la glace, le jeu laisse **0,10** d'adhérence : un véhicule y avance encore. Mon modèle
le laisse totalement impuissant. `tire.minimumFriction()` vaut 0 pour les dix pneus
fournis (constructeur à 4 arguments, `fconst_0`) : ce plancher n'existe que pour un pneu de
datapack.

Le frottement est lu **sur le bloc réellement sous la roue**, obtenu par un lancer de rayon
(`computeMaxExtensionToTerrain`, `minInteractingBlock`). Mon scalaire `--friction` reste
donc une saisie de substitution, à assumer comme telle.

### Les trois forces (offsets 523–669)

```java
brake   = level.getSignal(pos.above(), UP) / 15.0     // le signal vient bien d'AU-DESSUS
surface = min(touchingFriction, 1.0)
coef    = (0.075 + brake * 0.3) * surface

queuedForce += longitudinal × [ −coef × strengthMul × (v · longitudinal)
                               + rpm × (1 − brake) × surface × 1.75 ] × dt
queuedForce += lateral      × [ −0.6 × touchingFriction × strengthMul × (v · lateral) ] × dt

forceTotal.applyImpulseAtPoint(subLevel, contact, queuedForce)
```

Trois choses à retenir.

**(a) `brake` est `signal/15`, brut.** Mon code fabrique son frein avec `0,075` et `0,3` —
les constantes du **freinage dynamique** — et l'injecte dans la traction. C'est un bug
actif :

| Signal | Poussée correcte | Ma poussée | Écart |
|---|---|---|---|
| 0 | 1,750 | 1,619 | −7 % |
| 10 | 0,583 | 1,269 | +118 % |
| **15** | **0,000** | **1,094** | la roue pousse encore |

**(b) L'asymétrie de friction est réelle et voulue.** Traction et freinage saturent à
`min(f, 1)` ; la dérive latérale utilise `touchingFriction` **non borné**. Sur sable des
âmes, un véhicule tient donc mieux en virage (1,65) qu'il ne tracte (1,0).

**(c) Tout est multiplié par `dt` et appliqué en impulsion.** Cela répond définitivement à
la question que j'avais laissée ouverte — par tick ou par seconde, facteur 20 — :
**les coefficients sont par seconde**. Le freinage donne

```
dv/dt = −20 × (0,075 + 0,3·frein) × min(f,1) × v
τ = 0,67 s frein relâché ;  τ = 0,13 s frein à fond
```

### Un quatrième signal que je n'avais pas vu

`getSteeringSignal()` lit la redstone **à gauche et à droite** du support
(`HORIZONTAL_FACING.getClockWise()` et `.getCounterClockWise()`) et renvoie leur
**différence signée**. Le support de roue a donc deux entrées distinctes : le frein par
au-dessus, la direction par les côtés. Mon modèle n'en connaît aucune.

---

## 4. Aérodynamisme — **les voiles sont des ailes**

C'était la vraie surprise. Sable expose `BlockSubLevelLiftProvider`, implémenté par :

- `SailBlockMixin`, dans le paquet `…mixin.compatibility.create.sails_providing_lift` — les
  voiles de Create ;
- `SymmetricSailBlock` — les voiles symétriques de Simulated.

Les ponders de Simulated le disent en toutes lettres : *« When moving on a Simulated
Contraption, Regular Sails provide Lift »*, *« Lift is generated relative to the speed of
the Sail, and is applied perpendicular to its surface »*, *« Unlike Regular Sails, Symmetric
Sails only produce Drag »*.

Les coefficients sont dans les méthodes par défaut de l'interface :

| | portance | traînée parallèle | traînée sans direction |
|---|---|---|---|
| voile Create | **0,475** | **0,75** | **0,068882026** |
| voile symétrique | **0** | **1,75** | 0,068882026 |

La loi, lue dans `sable$contributeLiftAndDrag` (offsets 182–531) :

```
n = normale de la voile (son FACING opposé), v = vitesse du bloc, P = pression à sa position

traînée ∥      D∥ = n × (n · v) × C∥ × P
traînée diffuse D₀ = v × C₀ × P
portance        L  = n × |v − D∥ − D₀| × CL × P

force  −= (D∥ + D₀ + L)         appliquée au centre de la voile
couple −= (pos − centre_de_masse) × (D∥ + D₀ + L)
```

Tout est proportionnel à la pression, donc à l'altitude. La portance est perpendiculaire à
la voile et proportionnelle à la vitesse **résiduelle** — pas au carré, et sans angle
d'attaque ni décrochage. C'est un modèle d'aile linéaire, pas une polaire.

**Il n'existe rien d'autre.** Aucune classe d'aile, d'aileron, de gouverne ou de portance
aérodynamique dans les cinq jars : la recherche sur `wing|airfoil|angleOfAttack|
liftCoefficient|stall|aileron|rudder|elevator` ne rend que des sous-chaînes fortuites
(« flowing », « install », « showing »). L'aérodynamisme de cet écosystème se résume à :
traînée linéaire des blocs étanches, amortissement universel, portance des voiles.

### Ce que ça pèse sur la flotte

| Vaisseau | voiles totales | dont **hors rotor** |
|---|---|---|
| `cargo_airship` | 124 | **44** |
| `cachalot_volant_v3` | 0 | 0 |
| `cachalot_volant_v4` | 174 | 0 |
| `c1_air_cruiser` | 513 | 16 |

Seules les voiles hors rotor comptent ici : celles d'un rotor tournent avec leur palier.

> **Corrigé à l'application.** La première version de ce rapport attribuait aux 44 voiles
> du cargo 21 unités de portance. C'est faux : **les 60 voiles de coque de la flotte sont
> toutes des voiles symétriques** (`simulated:white_symmetric_sail`), qui ne portent pas.
> Le test écrit pour vérifier leur portance l'a révélé en revenant vide.

Elles ne font donc que freiner, et selon leur axe : les 44 du cargo portent `axis=x`, soit
`1,75 × 44 = 77` de traînée parallèle sur x, plus `0,0689 × 44 = 3,0` de traînée diffuse sur
les trois axes. **Aucun vaisseau actuel ne génère de portance de voile** — le modèle est en
place et testé sur une voile Create synthétique, prêt pour le premier vaisseau qui en
porterait en coque.

---

## 5. Le levitite freine aussi, et je l'ignore

`data/aeronautics/floating_materials/levitite.json` déclare un profil complet :

```
prevent_self_lift, scale_friction_with_gravity, lift_strength 10, transition_speed 3
vertical   : lent 2,0   rapide 0,1
horizontal : lent 1,5   rapide 0,05
```

Les blocs sont groupés **par matériau en grappes** (`FloatingBlockCluster`), chaque grappe
recevant sa propre matrice de frottement. Un vaisseau à levitite porte donc deux grappes :
l'enveloppe étanche, et le levitite avec un frottement **anisotrope et dépendant de la
vitesse** — à basse vitesse, 2,0 par bloc à la verticale, soit **six fois** le 0,33 de
l'enveloppe. Mon modèle applique zéro traînée aux blocs de levitite.

`transition_speed = 3` veut dire que le régime lent domine sous 3 blocs/s environ et
s'efface au-delà (mélange gaussien, `Math.exp` à l'offset 369). `scale_friction_with_gravity`
multiplie en plus par la norme de la gravité.

---

## 6. Ce qui reste hors de portée du modèle actuel

**Le couple de traînée.** `applyFriction` produit force **et** couple, calculés sur la
distribution spatiale des blocs (`outerProduct`, tenseur d'inertie, produits vectoriels).
Mon simulateur est à trois degrés de liberté en translation ; c'est L6, et ce rapport ne le
change pas.

**`totalScale` est une somme.** J'écris `0,33 × N`. Le moteur somme les `floating_scale`
bloc par bloc. Identique aujourd'hui puisque tous les blocs étanches portent 0,33, mais si
Aeronautics ajoute un second matériau étanche d'échelle différente, mon modèle se trompera
en silence. À transformer en somme dès qu'on y touche.

**Le pas de temps interne.** `sable-server.toml` porte `sub_level_substeps_per_tick = 2` :
la physique est intégrée deux fois par tick, à dt = 1/40 s. Sans effet sur des taux par
seconde, mais à savoir avant de comparer une trajectoire tick à tick.

---

## 7. Ce qu'il faut modifier, concrètement

### ① Amortissement universel — à faire en premier

`data/tables/pressure.json` : `universal_drag` passe de constante inutilisée à constante
utilisée, avec la source corrigée (`DimensionPhysics.createDefault` + `Rapier3D.initialize`)
et une note disant que c'est un **taux par seconde**, pas un coefficient de force.

`sim/tick.py`, au calcul de l'amortissement :

```python
damping = self.drag.coefficient(st.pressure) + t.get("pressure.universal_drag") * self.mass.total
```

`model/drag.py` : `report()` distingue les deux termes, pour que la décomposition affiche
« enveloppe 822 + universel 167 ».

**Effets attendus, à vérifier après :** niveau 1 inchangé (le solveur cinétique n'y touche
pas). Niveau 2 toujours exact — `τ = m/(k + 0,09m)` reste une exponentielle, l'intégration
exponentielle reste exacte, l'écart doit rester à 0,000 %. Niveau 4 **doit** signaler une
rupture sur les cinq scénarios : c'est le comportement attendu, et la re-bénédiction des
traces de référence (`createsim scenario bless`) fait partie du lot.

### ② Traction des roues — le bug

`sim/forces.py`, `wheel_forces` : `brake = signal / 15.0`, sans emprunter à
`wheel_brake_base` ni `wheel_brake_per_signal`, qui redeviennent ce qu'elles sont — les
constantes du freinage dynamique. Un test fige les quatre points du tableau, dont
frein 15 ⇒ poussée nulle.

### ③ `fudgeFriction`

Nouvelle fonction dans `sim/forces.py`, et la table `forces.json` gagne
`wheel_friction_fudge_offset = 0.1` / `wheel_friction_fudge_scale = 0.9` sourcées sur
`WheelMountBlockEntity.fudgeFriction`. Partout où j'écris `min(friction, 1)`, lire
`min(fudgeFriction(friction), 1)` pour la traction et le freinage, et `fudgeFriction(friction)`
seul pour la dérive latérale.

### ④ Frottement dynamique des roues

Comme au plan précédent (`docs/plan-frottement-dynamique.md`), avec deux précisions que la
recherche apporte : les coefficients sont **par seconde** (plus d'incertitude d'un facteur
20), et `strengthMul = 20 × min(normalMass, stiffness)`. L'amortissement de `integrate()`
devient un vecteur par axe, puisque freinage et dérive sont linéaires en v et anisotropes.

### ⑤ Portance des voiles de coque

Nouvel organe `model/sails.py` : les voiles **hors rotor de palier**, leur normale, leur
position. Nouveau producteur dans `sim/forces.py` appliquant les trois termes ci-dessus avec
`CL = 0.475`, `C∥ = 0.75`, `C₀ = 0.068882026` pour les voiles Create, et `CL = 0`,
`C∥ = 1.75` pour les symétriques.

### ⑥ Traînée du levitite

`model/drag.py` gagne une seconde grappe. Les termes lents/rapides et le mélange gaussien de
`transition_speed = 3` sont la partie délicate ; une première version peut n'implémenter que
le régime rapide (0,1 vertical / 0,05 horizontal) en signalant la simplification comme une
limite du modèle, à la façon du F5.9.

---

## 8. Ce qui reste à mesurer en jeu

La recherche a levé les deux incertitudes que je m'apprêtais à te faire mesurer — l'unité
des coefficients (par seconde, tranché par le `dt` du bytecode) et la forme de
`universal_drag` (un taux global, tranché par `Rapier3D.initialize`). Il reste :

| Mesure | Ce qu'elle tranche |
|---|---|
| Vitesse de croisière en palier du cruiser, poussée fixe | l'amortissement universel, là où il pèse ×6,4 |
| Distance d'arrêt d'un engin à roues, frein relâché puis à fond | `normalMass`, le seul point resté déduit |
| Un `.nbt` d'engin à roues, frein câblé à un levier | la clé NBT du signal, et tout le lot ④ |

La première suffit à valider ① toute seule, et c'est celle qui compte : elle porte sur la
correction la plus lourde du lot.

---

---

## 9. Ce que l'application a appris

Trois choses que la lecture du bytecode seule n'avait pas montrées, et que les tests ont
fait sortir.

**Les voiles de coque de la flotte ne portent pas.** Voir la correction en section 4.

**Une voile symétrique n'a pas de `facing`.** `SymmetricSailBlock.sable$getNormal` renvoie
`Direction.get(POSITIVE, AXIS)` : sa normale vient de sa propriété `axis`. Lire le `facing`
comme pour une voile Create donnait `None`, et la traînée parallèle retombait par défaut sur
l'axe vertical. Sur le cargo, 77 unités de traînée partaient sur y au lieu de x.

**Le levitite pèse lourd sur le cruiser.** 1 592 blocs × 11 (gravité) × 2,1 donnent 36 775
d'amortissement vertical à l'arrêt, pour une masse de 16 644 : τ ≈ 0,45 s. Le vaisseau
descend désormais à 0,21 bloc/s au lieu de chuter — le comportement d'un matériau
anti-gravité qui « tient » le vaisseau, et c'est bien ce que dit le profil
`floating_materials/levitite.json`. C'est aussi le changement le moins confronté du lot :
aucune mesure ne l'a encore validé.

### Effet mesuré par la non-régression, avant re-bénédiction

| Scénario | vitesse max | montée | autre |
|---|---|---|---|
| cargo — montée à vide | −9,8 % | +9,2 % | altitude max −1,6 % |
| cargo — brûleurs coupés | −5,1 % | +18,8 % | altitude max −4,5 % |
| cargo — décollage du sol | −9,6 % | +9,6 % | |
| cachalot — moulin et hélices | −10,1 % | +8,3 % | |
| cachalot v4 — disjonction | −12,8 % | +6,7 % | distance −16,9 % |

L'altitude d'équilibre ne bouge pas : la traînée ne change pas l'équilibre statique, seulement
le transitoire — le vaisseau dépasse moins son altitude avant de s'y poser.
