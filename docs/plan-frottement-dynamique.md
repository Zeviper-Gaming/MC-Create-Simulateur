# Plan — Frottement dynamique des roues et traînée universelle

## 🔓 Autorisations demandées

Aucune écriture pour l'instant : **ce document est le livrable**. Rien n'est modifié tant que
ce plan n'est pas validé. Voici ce qu'il engagerait une fois lancé.

| Chemin | Type d'édition |
|---|---|
| `src/createsim/sim/forces.py` | Correction de `wheel_forces` + nouvelle `wheel_friction_forces` |
| `src/createsim/sim/integrator.py` | `damping` scalaire → vecteur par axe |
| `src/createsim/sim/tick.py` | Branchement de l'amortissement anisotrope |
| `src/createsim/model/redstone.py` | `offroad:wheel_mount` ajouté aux consommateurs |
| `src/createsim/model/wheels.py` | **Création** — nouvel organe (suspension, `strengthMul`) |
| `src/createsim/model/vehicle.py` | Enregistrement de l'organe dans l'ordre de recalcul |
| `data/tables/forces.json` | Entrées `wheel_spring_*`, `wheel_normal_mass_*` |
| `data/tables/pressure.json` | Champ `hypothese` sur `universal_drag` |
| `data/mesures/jeu.json` | **Création d'entrées** — les mesures qui trancheront |
| `tests/test_frottement.py` | **Création** |
| `tests/test_solveur.py`, `test_simulation.py` | Ajustement des appels à `integrate` |
| `README.md` | Section frottement |

**Ce qui n'aura PAS lieu :** aucune écriture dans un fichier `.nbt` source, aucune écriture
dans l'instance CurseForge ni dans le bundle du plugin `mc-create-engineer` (ce plan ne
touche **pas** au calculateur statique — le document de passation le concerne, lui, et reste
à appliquer séparément), aucun appel réseau, aucune réécriture d'historique. Le commit et le
push vers `origin/main` restent autorisés comme pour les lots précédents, mais uniquement
une fois les tests au vert.

---

## Ce que la vérification a trouvé

Source d'autorité : `references/physique-moteur.md` §6 (traînée) et §16 (roues Offroad),
extraites de `FloatingBlockController.applyFriction` et
`WheelMountBlockEntity.sable$physicsTick()`. Le document de passation est une source
secondaire : là où il s'écarte de la référence, c'est la référence qui tranche.

### ✅ Ce qui est déjà exact

**La traînée.** §6 donne `F = −(0,33 × N_étanches × pression) × v`, linéaire et non
quadratique parce que `transition_speed = 0` annule la composante « slow drag ». C'est
exactement ce que fait `DragOrgan.coefficient()`. Rien à corriger.

**La pression à l'altitude réelle.** La Modification 4 du document vise un défaut du
calculateur *statique*, qui appelait `drag_coefficient(s)` sans pression et calculait donc
toujours au niveau de la mer. Le simulateur recalcule `st.pressure` à chaque tick depuis
l'altitude courante et le passe à `drag_force` — c'était une exigence F2.5 du cahier, tenue
depuis L0. **Cette modification ne s'applique pas ici.**

**Le rayon de pneu ne change pas la poussée**, conformément à §16.

### ❌ Défaut 1 — la traction applique les mauvaises constantes (bug actif)

§16 donne deux formules distinctes qui partagent le mot « frein » :

```
poussée  = RPM × (1 − frein) × min(friction,1) × 1,75      avec frein = signal / 15
freinage = −v_long × (0,075 + frein × 0,3) × min(friction,1) × strengthMul
```

`wheel_forces` construit son `frein` avec les constantes de la **seconde** formule et
l'injecte dans la **première** :

```python
brake = min(1.0, brake_base + (signal / 15.0) * brake_step)   # 0,075 + s/15 × 0,3
magnitude = abs(rpm) * (1.0 - brake) * surface * coef
```

| Signal | `frein` correct | Poussée correcte | Mon `frein` | Ma poussée | Écart |
|---|---|---|---|---|---|
| 0 | 0,000 | 1,750 | 0,075 | 1,619 | **−7 %** |
| 5 | 0,333 | 1,167 | 0,175 | 1,444 | +24 % |
| 10 | 0,667 | 0,583 | 0,275 | 1,269 | +118 % |
| 15 | 1,000 | **0,000** | 0,375 | 1,094 | **la roue pousse encore** |

Frein à fond, la roue devrait être immobilisée ; elle tracte à 62,5 % de sa valeur libre.
Frein relâché, elle perd 7,5 % pour rien. Le calculateur d'origine n'avait aucun terme de
frein — c'est mon portage L0 qui en a ajouté un, avec les mauvaises constantes.

### ❌ Défaut 2 — le frottement dynamique n'existe pas

Les deux forces de §16 qui dépendent de la **vitesse** sont absentes : le freinage
longitudinal et la résistance à la dérive latérale. `wheel_lateral_coef = 0,6` est dans la
table `forces.json`, sourcée, et n'est appelée nulle part. Aucun `strengthMul`, aucune
lecture de la raideur de suspension.

Conséquence : le simulateur ne peut répondre ni à « sur combien de blocs ce véhicule
s'arrête-t-il ? » ni à « tient-il ce virage ? ». C'est précisément l'objet de ce lot.

### ❌ Défaut 3 — aucun levier ne peut freiner

`model/redstone.py` définit `CONSUMERS = BURNERS + TRANSMISSIONS`. `offroad:wheel_mount`
n'en fait pas partie, donc `signals` ne le contient jamais et `wheel_forces` retombe
systématiquement sur la valeur figée du NBT. Un frein câblé à un levier resterait sans effet
dans la boucle — le contraire de ce que L2 promet.

### ⚠️ Défaut 4 — `universal_drag` inutilisé, et la correction proposée n'est pas sûre

`universal_drag = 0,09` est dans `pressure.json`, sourcée
(`Sable DimensionPhysics.createDefault()`), jamais utilisée. Conséquence réelle : un véhicule
sans bloc étanche a `k = 0`, donc `terminal_motion` renvoie `vitesse_max: None` et
l'intégrateur bascule sur sa branche sans amortissement — **le véhicule accélère
indéfiniment**. Le défaut est bien présent chez moi aussi.

Mais la correction du document (`k += 0,09 × N_total`) **ne peut pas être adoptée telle
quelle**, et le document l'admet lui-même dans sa réserve. La référence §6 dit que
`universal_drag` « s'ajoute **globalement** (amortissement du sous-niveau) » — *globalement*,
pas par bloc. Quatre lectures sont défendables, et elles ne donnent pas le même véhicule :

| Lecture | τ du cargo | τ du cruiser | Facteur sur la traînée du cruiser |
|---|---|---|---|
| actuelle (sourcée, sans le terme) | 2,26 s | 60,1 s | ×1 |
| `+ 0,09 × N_total` (document) | 1,46 s | 7,8 s | **×7,7** |
| `+ 0,09 × masse` | 1,88 s | 9,4 s | ×6,4 |
| `+ 0,09` global | 2,26 s | 60,1 s | ×1,00 |
| `v *= 0,91` par tick | 0,53 s | 0,53 s | indépendant de la masse |

Un facteur 7,7 sur la traînée d'un vaisseau, ce n'est pas un raffinement : c'est la
différence entre une barge et un engin nerveux. La dernière lecture est la plus probable pour
un « amortissement du sous-niveau » dans un moteur de la famille Minecraft, où
`velocity *= (1 − drag)` à chaque tick est l'idiome courant — et c'est aussi la seule qui
rende la constante de temps indépendante de la masse, ce qui se voit immédiatement en jeu.

**Ce point se mesure.** Il ne se tranche pas au raisonnement.

### 📄 Défaut 5 — la table de friction du sol n'est pas consultée

`BlockProperties.ground_friction(name)` existe et n'est jamais appelée : seul le scalaire
`SimOptions.ground_friction` agit. C'est **conforme** à la réserve du document — un `.nbt` de
véhicule ne contient pas le sol sous ses roues — mais rien ne le dit à l'utilisateur. À
documenter, pas à implémenter.

---

## Deux résultats de la vérification qui changent la conception

**`strengthMul` se simplifie.** §16 donne
`normalMassScaling = min(masse_normale / raideur, 1) × 10` puis
`strengthMul = raideur × normalMassScaling × 2`. En développant :

```
strengthMul = 20 × min(masse_normale, raideur)
```

Ce n'est pas qu'une simplification d'écriture, c'est un comportement. Sous saturation, la
décélération vaut `F/M = 20 × v × coef` : **indépendante de la masse**, comme le frottement
réel. Au-dessus, `strengthMul` plafonne à `20 × raideur` et la décélération devient
inversement proportionnelle à la masse — **un véhicule surchargé sur suspension molle ne
freine plus**. C'est un vrai résultat de conception que le simulateur pourra montrer, et
c'est aussi ce qui me fait retenir l'interprétation « masse portée par cette roue » pour
`masse_normale` : c'est la seule lecture qui rende la physique cohérente.

**Le freinage et la dérive sont linéaires en v, comme la traînée.** Ils ne doivent donc pas
rejoindre la somme des forces externes mais l'**amortissement**, sinon l'intégration
exponentielle cesse d'être exacte et le niveau 2 de validation (0,000 % aujourd'hui) se
dégrade. Mais ils sont **anisotropes** : le freinage agit sur l'axe longitudinal, la dérive
sur le latéral, la traînée sur les trois. Le `damping` scalaire de `integrate()` doit devenir
un vecteur par axe. La boucle est déjà écrite par axe, le changement est contenu.

---

## Le lot, en cinq étapes

### 1. Corriger la traction (indépendant du reste)

`frein = signal / 15`, sans emprunter aux constantes du freinage dynamique. Une ligne, plus
un test qui fige les quatre points du tableau ci-dessus — en particulier **frein à 15 ⇒
poussée nulle**, qui est le cas que le code actuel rate le plus franchement.

### 2. `model/wheels.py` — un organe pour les roues

Sur le modèle des organes existants (`affected_by` en O(1), `recompute` complet) :

- lecture de la raideur (`ScrollValue`) et du pneu de chaque support ;
- répartition de la masse portée — première version : `masse_totale / nombre_de_roues`,
  explicitement marquée comme hypothèse ;
- `strength_mul = 20 × min(masse_portée, raideur)`, avec le drapeau de saturation ;
- `affected_by` : le bloc est un support de roue, ou son voisin (la molette et le signal
  arrivent par au-dessus).

Enregistré dans l'ordre de recalcul après `masse` (dont il dépend) et avant `cinetique`.

### 3. `wheel_friction_forces` — le frottement dynamique

```
freinage = −v_long × (0,075 + frein × 0,3) × min(friction, 1) × strengthMul
dérive   = −v_lat  × 0,6                   × friction        × strengthMul
```

L'asymétrie est dans la source et doit être tenue : la traction et le freinage saturent à
`min(friction, 1)`, la dérive latérale non. Sur sable des âmes, miel ou tapis roulant
(friction 1,65), un véhicule tient donc **mieux** en virage qu'il ne tracte.

L'axe longitudinal est celui du support de roue (`facing`) ; le latéral est perpendiculaire
dans le plan horizontal.

### 4. Amortissement par axe

`integrate(position, velocity, external_force, damping, mass)` où `damping` devient un
triplet. Les trois appelants (`tick.py`, `terminal_motion`, les tests) suivent. La branche
`rate < 1e-9` reste, par axe : un véhicule sans traînée ni roue sur un axe donné garde son
intégration en accélération pure.

`terminal_motion` gagne une variante par axe et cesse de renvoyer `vitesse_max: None` dès
qu'une roue freine, même sans bloc étanche.

### 5. Le levier de frein

`offroad:wheel_mount` rejoint `CONSUMERS` dans `redstone.py`, avec `SignalStrength` comme
clé NBT de repli. Le bandeau montrera alors le sens de l'échelle du levier de frein comme il
le fait déjà pour les brûleurs et les transmissions.

**Réserve reprise du document :** la clé NBT exacte n'a jamais été vérifiée sur une structure
freinée. Elle ne peut pas l'être aujourd'hui — voir plus bas.

### Hors de ce lot

La **suspension verticale** (`springStrength`, `dampingStrength`, `force_ressort`) est
sourcée en §16 et les constantes seront mises en table, mais elle agit sur l'axe vertical au
contact du sol : elle appartient à L6 avec le tangage, pas ici. Le document de passation ne
la demande pas non plus.

Le **calculateur statique** `mc-create-engineer` n'est pas touché : les cinq modifications du
document de passation le concernent et doivent lui être appliquées dans sa propre session.

---

## Vérification

**Niveau 1–2 inchangés.** Le passage à un amortissement par axe ne doit rien déplacer sur un
vaisseau sans roue : l'écart analytique doit rester à 0,000 % et la concordance à 124/131. Le
lot 4 est là pour le prouver — `createsim nonregression` doit rendre « identique » sur les
cinq scénarios de référence.

**Nouveaux tests** (`tests/test_frottement.py`) :

- les quatre points de la table de traction, dont frein 15 ⇒ poussée nulle ;
- décélération indépendante de la masse sous saturation, dépendante au-dessus ;
- dérive latérale à friction 1,65 supérieure à la traction à la même friction ;
- un levier de frein change réellement la force (défaut 3) ;
- l'amortissement par axe redonne exactement le scalaire quand les trois axes sont égaux.

**Deux scénarios de plus** dans la bibliothèque, dès qu'un véhicule à roues sera disponible :
une distance d'arrêt et un virage tenu.

---

## Ce que je ne peux pas faire sans toi

**Aucun véhicule à roues n'existe dans le corpus.** J'ai cherché : les onze `.nbt` de
l'instance et les deux fixtures du dépôt ne contiennent pas un seul `offroad:wheel_mount`.
Le `dirt_bike.nbt` cité par le document de passation n'est plus là. Tout ce lot serait donc
écrit sans jamais tourner sur une donnée réelle, et les tests reposeraient sur des structures
fabriquées à la main. C'est faisable, mais c'est exactement la situation qui a produit le
défaut 1 : une formule plausible, jamais confrontée.

**Il me faudrait un `.nbt` d'un engin à roues**, si possible avec un frein câblé à un levier —
cela lèverait du même coup la réserve sur la clé NBT du signal.

**Et trois mesures**, du même genre que celles qui ont réglé la loi d'impact des hélices :

| Mesure | Ce qu'elle tranche |
|---|---|
| Distance d'arrêt depuis une vitesse connue, frein relâché puis à fond | `strengthMul`, et l'unité des coefficients (par tick ou par seconde — facteur 20) |
| Vitesse de croisière en palier du cargo, hélices à un réglage fixe | la forme de `universal_drag` : 2,26 s, 1,46 s ou 0,53 s de constante de temps |
| Même engin, suspension molle puis dure, même masse | la saturation de `strengthMul` |

Sans la première, je code une formule dont je ne sais pas si elle s'applique par tick ou par
seconde. C'est la faute qui avait donné 23,8 % d'erreur au niveau 2 avant L0 ; je préfère la
nommer avant plutôt que la découvrir après.

**Ma recommandation :** faire l'étape 1 tout de suite — elle est sourcée, isolée, et corrige
un bug qui tourne aujourd'hui dans `main` — puis garder les étapes 2 à 5 pour quand un engin
à roues existera.
