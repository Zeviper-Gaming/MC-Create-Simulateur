# Simulateur de véhicules Create

Banc d'essai **hors-jeu** pour véhicules Create (Aeronautics / Simulated / Offroad / Sable).
Il charge un fichier de structure Minecraft `.nbt`, reconstruit le véhicule qu'il contient,
et le fait fonctionner selon les équations du moteur du jeu — sans lancer Minecraft, sans
monde, sans serveur.

Le but n'est pas de montrer *ce que* le véhicule fait, mais **quelle force en est
responsable**. En jeu, on voit le résultat et jamais la décomposition.

> **État : lots L0, L1 et L2 livrés — le périmètre demandé est atteint.**
> L0 est le noyau physique, sans interface, dont les deux niveaux de validation
> automatiques passent. L1 est la fenêtre 3D : blocs, centres, et décomposition des
> forces. L2 est le bandeau de contrôle et la boucle temps réel — on actionne les
> commandes du vaisseau et on le voit réagir. Restent le diagnostic outillé et les
> courbes (L3), les scénarios (L4), l'édition de blocs (L5) et le tangage complet (L6).

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

```bash
pip install PySide6
createsim voir mon_vaisseau.nbt
```

La fenêtre : le véhicule, **les forces qui s'exercent dessus**, et un bandeau latéral
qui expose ses commandes réelles. Chaque force est dessinée à son point d'application
avec une longueur proportionnelle à son intensité ; la résultante et le couple net
sont distincts ; les centres de masse et de portance sont matérialisés, avec le bras
de levier entre eux. La simulation tourne à 1/20 s et l'effet d'une commande est
visible immédiatement.

| Touche | Effet |
|---|---|
| souris | clic gauche orbite, molette zoome, clic droit translate |
| `1`–`9` | montre ou masque une famille de force |
| `F` | toutes les forces |
| `B` | volume de gaz des poches, teinté par remplissage |
| `K` | réseau cinétique en surbrillance, teinté par régime |
| `A` `C` `H` `P` `I` | avant, côté, dessus, arrière, isométrique |
| `R` | recadrer automatiquement |

`--bench 5` mesure la cadence pendant cinq secondes puis sort.

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

## Le risque 3D est levé

Le cahier désignait un risque principal : *« la 3D peut coûter cher. Un rendu naïf de
20 000 cubes s'écroule. »* Il prescrivait d'en faire d'abord un module autonome,
« testable avant que le reste de l'interface existe ». C'est fait, et le risque
n'existe plus.

| Mesure | `c1_air_cruiser` (20 659 blocs) |
|---|---|
| Faces totales d'un rendu naïf | 123 954 |
| Faces visibles après suppression des internes | **31 030** (−75 %) |
| Quadrilatères après fusion gloutonne | **10 376** (−67 %) |
| Triangles envoyés au GPU | **20 752** — 8 % d'un cube par bloc |
| Mémoire GPU | **2,1 Mo** |
| Construction du maillage | **0,76 s**, une fois au chargement |
| Cadence à 1280×720 | **2 453 images/s** — NF2 en demande 60 |

Trois choses rendent ce résultat possible, et aucune n'est un raffinement tardif.
Les **faces internes n'existent pas** : une face n'est émise que si le voisin dans sa
direction est vide. Les **faces coplanaires de même famille fusionnent** en rectangles
maximaux. Et tout part en **un seul tampon, dessiné en un seul appel**.

Trois choses rendent le résultat lisible, et chacune répare un défaut réel.

**L'enroulement des triangles suit la normale annoncée.** Après `np.take`, les deux
axes restants gardent leur ordre d'origine, soit `(x, z)` pour l'axe y — un repère
*gaucher* par rapport à `+y`. Toutes les faces horizontales sortaient donc enroulées à
l'envers, le *back-face culling* les éliminait, et on voyait à travers chaque pont et
chaque toit. Un test compare désormais la normale géométrique de chacun des 27 658
triangles à celle qu'il déclare.

**La grille des blocs est restituée dans le shader.** La fusion gloutonne efface les
arêtes : sans elles, une coque de trente blocs n'est plus qu'un aplat et l'échelle se
perd. Le trait est tracé par dérivées d'écran, donc antialiasé, et s'efface quand un
bloc couvre moins de deux pixels — sinon la grille moire au loin. Coût géométrique nul.

**Le cadrage s'ajuste sur les sommets, pas sur la boîte englobante**, et la caméra
choisit l'azimut qui remplit le mieux l'image. Une coque de 176 blocs de long posée en
diagonale n'occupait que le tiers de la largeur ; elle en occupe maintenant l'essentiel.

Le maillage vit dans `view/mesh.py`, qui ne connaît ni Qt ni OpenGL et se teste sans
fenêtre — c'est ce qui a permis de mesurer le poste coûteux avant d'écrire la moindre
ligne d'interface. PySide6 6.11.2 s'installe sans difficulté sur Python 3.14.

> **La sortie de secours du cahier — une coquille Qt hébergeant Three.js — n'a pas
> lieu d'être :** il y a 40× la marge demandée. Reste à confirmer la cadence sur les
> trois systèmes visés ; elle n'est mesurée que sous Windows.

## L2 : actionner les commandes et voir le vaisseau réagir

C'est le périmètre demandé par le cahier — le minimum vendable. Un bandeau vertical à
droite, sections repliables, valeurs modifiables en continu, **aucun bouton
« appliquer »**.

**Le bandeau n'expose que ce qui existe dans le fichier.** Un vaisseau sans roues n'a
pas de section roues. Un brûleur commandé par un levier n'est pas réglable directement :
on actionne le levier, et le brûleur suit. C'est ce qui distingue un simulateur d'un
tableur — on pilote le véhicule tel qu'il est câblé, pas ses paramètres internes.

| Section | Contenu |
|---|---|
| Simulation | pause, ×1/×4/×16, avance d'un tick, remise à zéro, convergence directe |
| Commandes de bord | un curseur 0-15 par levier réel, sa position, ce qu'il commande |
| Groupes de brûleurs | un groupe par canal redstone : signal reçu, réglage molette, sortie, remplissage en direct |
| Transmissions | signal, mode, rapport effectif — **le découplage à 15 est écrit en toutes lettres** |
| Propulsion | par palier : régime, voiles, poussée, part dans la poussée totale |
| Situation | altitude, sol, friction, et les constantes du jeu derrière un mode expert |

| Réf. | Exigence | État |
|---|---|---|
| F2.4 | pause, ×1, ×4, ×16, avance d'un tick | ✅ |
| F2.7 | mode statique : convergence directe vers l'équilibre | ✅ |
| F4.1 | une commande d'interface par commande réelle, avec sa position | ✅ |
| F4.2 | propagation immédiate par les liaisons redstone | ✅ |
| F4.3 | sélectionner une commande la met en surbrillance avec ses destinataires | ✅ |
| F4.4 | paramètres de situation modifiables simulation en cours | ✅ |
| F4.5 | sauvegarde et rappel de jeux de réglages nommés | ✅ |
| F4.6 | valeur numérique systématique à côté de chaque curseur | ✅ |
| F4.7 | constantes modifiables, en signalant l'écart au réglage du jeu | ✅ |

Sur une manette `inverted`, le bandeau affiche **les deux** nombres — « angle en jeu 0 ·
signal émis 15 » — parce que la confusion entre les deux est exactement le piège à
lever, et qu'elle coûte une transmission découplée sans qu'on comprenne pourquoi.

### Le piège de performance

La boucle est tombée à **22 tours/s**, frôlant le seuil obligatoire, avant qu'un profil
ne désigne le coupable : la géométrie des poches de gaz était **remaillée à chaque
tick**, 33 ms par tour. Or elle ne change qu'à l'édition d'un bloc — seule sa teinte
suit le remplissage. En ne réécrivant que le tampon de couleur, la boucle passe à
**100 tours/s** sur `cargo_airship` et **84** sur `c1_air_cruiser`.

## L1 : la décomposition des forces

La fenêtre montre le véhicule **et les forces qui s'exercent dessus**. La seconde
partie est la raison d'être du logiciel : en jeu on voit le résultat, jamais la
décomposition.

| Réf. | Exigence | État |
|---|---|---|
| F3.1 | blocs en volumes colorés par famille | ✅ |
| F3.2 | caméra libre, vues normalisées | ✅ |
| F3.6 | un vecteur par force, à son point d'application, longueur ∝ intensité | ✅ |
| F3.7 | code couleur par famille, légende chiffrée | ✅ |
| F3.8 | résultante et couple net, distincts des forces élémentaires | ✅ |
| F3.9 | centres de masse et de portance, bras de levier entre eux | ✅ |
| F3.10 | filtre d'affichage par famille de force | ✅ |
| F3.11 | volume des poches en transparence, teinté par remplissage | ✅ |
| F3.12 | surbrillance du réseau cinétique, teinté par régime | ✅ |
| F3.4 | attitude réelle appliquée au rendu | déséquilibre **statique** seul, comme décidé |
| F3.3 F3.5 | coupe par plan mobile, textures du jeu | L6 |

Trois choix méritent d'être dits.

**Les forces se dessinent en deux passes.** Une passe fantôme sans test de profondeur
montre ce que la coque cache, puis une passe pleine par-dessus. Sans la première, un
centre de masse situé à l'intérieur du vaisseau serait purement invisible ; sans la
seconde, on perdrait toute notion de profondeur.

**Un couple n'est pas une force**, donc il n'est pas dessiné comme une flèche : c'est
un arc fléché autour de son axe, qui se lit comme une rotation sans avoir à consulter
la légende.

**L'échelle est rapportée à la taille du véhicule.** La plus grande force occupe une
fraction fixe de la plus grande dimension, et toutes les autres suivent
proportionnellement. Un vaisseau de 20 blocs et un de 200 se lisent donc pareil, et
la légende donne la conversion — « 1 bloc = 2 737 ». Une force sous un demi-pour-cent
de la plus grande n'est pas dessinée, mais reste comptée dans la légende.

### Un défaut de fond corrigé au passage

Le calculateur statique supposait que **l'axe longitudinal était x**. Or `cargo_airship`
mesure 34 × 38 × 67 et `c1_air_cruiser` 31 × 37 × 176 : leur longueur est en **z**. Le
rapport confondait donc tangage et roulis, et annonçait un bras de levier de −0,04 là
où le vrai vaut 2,09. L'axe se déduit désormais des dimensions, et le rapport nomme
celui qu'il a retenu.

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
