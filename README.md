# Simulateur de véhicules Create

Banc d'essai **hors-jeu** pour véhicules Create (Aeronautics / Simulated / Offroad / Sable).
Il charge un fichier de structure Minecraft `.nbt`, reconstruit le véhicule qu'il contient,
et le fait fonctionner selon les équations du moteur du jeu — sans lancer Minecraft, sans
monde, sans serveur.

Le but n'est pas de montrer *ce que* le véhicule fait, mais **quelle force en est
responsable**. En jeu, on voit le résultat et jamais la décomposition.

> **État : lots L0 à L4 livrés.**
> L0 est le noyau physique, sans interface, dont les deux niveaux de validation
> automatiques passent. L1 est la fenêtre 3D : blocs, centres, et décomposition des
> forces. L2 est le bandeau de contrôle et la boucle temps réel — le périmètre
> demandé. L3 ajoute le diagnostic cliquable, les courbes glissantes et la
> télémétrie. L4 apporte les scénarios, la comparaison et la non-régression.
> Restent l'édition de blocs (L5) et le tangage complet (L6). L'outil se lance
> maintenant **sans Python**, par un exécutable, et charge les `.nbt` directement.

---

## Lancer l'outil

Une fenêtre, trois façons de l'ouvrir.

| Comment | Ce qui s'ouvre |
|---|---|
| double-clic sur `createsim.exe` | l'**accueil** : vos fichiers récents, les `.nbt` de vos dossiers `schematics`, les exemples fournis |
| glisser un `.nbt` sur l'icône `createsim.exe` | ce vaisseau, directement |
| `createsim.exe vaisseau.nbt` | idem, en ligne de commande (`createsim vaisseau.nbt` depuis les sources) |

L'exécutable est autonome : ni Python, ni PySide6, ni Minecraft. Il embarque les tables de
constantes, la bibliothèque de scénarios et deux vaisseaux d'exemple.

### Charger un `.nbt`

Cinq chemins mènent à un vaisseau. Tous **remplacent le vaisseau courant**, à la même place
et à la même taille — un seul à la fois, comme le cahier le décide.

- **Glisser-déposer** un `.nbt` n'importe où dans la fenêtre : l'accueil, la vue 3D, le bandeau.
  Si plusieurs fichiers sont lâchés, le premier s'ouvre et la barre d'état dit combien sont ignorés.
- **Ctrl+O**, ou *Fichier → Ouvrir un .nbt…* : la boîte de dialogue s'ouvre dans le dernier
  dossier utilisé, sinon dans le dossier `schematics` d'une de vos instances.
- ***Fichier → Ouvrir un récent***.
- **L'accueil** : un double-clic sur un fichier de la liste.
- **La ligne de commande**, ou l'icône sur laquelle on glisse le fichier.

L'outil sait où Create range ses fichiers : les dossiers `schematics` des instances **CurseForge**,
**Prism / MultiMC** et du lanceur officiel. Pour un autre emplacement, la variable
`CREATESIM_SCHEMATICS` (plusieurs dossiers séparés par `;` sous Windows).

**Un `.nbt` qui n'est pas une structure** — le cache d'une forteresse, un `level.dat`, un fichier
tronqué — est un cas normal, pas une erreur de programmation. L'outil le dit en une phrase
(« il manque *size*, *DataVersion*, *palette*, *blocks* »), la fenêtre courante reste ouverte, et
le fichier n'entre pas dans les récents. Avant, l'utilisateur lisait `KeyError: 99`.

**Réglages et journal** vivent dans `%LOCALAPPDATA%\createsim` (Windows),
`~/Library/Application Support/createsim` (macOS) ou `~/.config/createsim` (Linux) :
du JSON lisible à la main, aucune clé de registre. `CREATESIM_HOME` déplace le tout — c'est
aussi ce qui permet une installation portable. Le journal est le seul endroit où lire une erreur
quand il n'y a pas de console : *Aide → À propos* dit où il est.

L'outil **ne s'associe pas de lui-même** aux fichiers `.nbt` : d'autres logiciels les utilisent.
Pour double-cliquer un `.nbt` : clic droit → *Ouvrir avec* → *Choisir une autre application* →
`createsim.exe`.

### Construire l'exécutable

```bash
pip install ".[build]"
python packaging/build_exe.py            # dist/createsim/createsim.exe
python packaging/build_exe.py --zip      # + dist/createsim-windows.zip
python packaging/build_exe.py --onefile  # un seul fichier, démarrage plus lent
```

Le script ne se contente pas de construire : il **lance l'exécutable construit** et vérifie
trois choses. Un paquet PyInstaller qui se construit sans erreur peut démarrer sur une fenêtre
vide — il suffit qu'un plugin Qt ou un fichier de données manque.

| Essai | Résultat mesuré |
|---|---|
| ouvre un vaisseau et dessine sa fenêtre, vue 3D comprise | image identique, à l'octet près, à celle des sources |
| tient les 20 ticks/s obligatoires, rendu compris | **93 tours/s** |
| ouvre l'accueil et y trouve ses exemples embarqués | ✅ |

La construction prend une trentaine de secondes ; le dossier pèse 164 Mo, l'archive 66 Mo.
L'exécutable a aussi été déplacé hors du dépôt et lancé depuis un autre répertoire, avec un
profil vide : il ne dépend de rien d'autre que de son dossier.

Le rendu est le même que depuis les sources, **pixel pour pixel** : la même image, 921 600 pixels,
zéro différent.

La forme *fichier unique* (`--onefile`, 64 Mo) passe les mêmes vérifications, mais se
dépaquette dans le dossier temporaire à chaque lancement : **environ 2 s de plus** (4,1 s
jusqu'à la première image, contre 2,1 s pour la forme dossier). Le dossier est le bon choix pour
un usage quotidien ; le fichier unique, pour envoyer l'outil à quelqu'un.

Deux limites, dites plutôt que tues. **Windows seulement** a été construit et vérifié ;
PyInstaller ne compile pas pour un autre système, et l'archive `.app` de macOS n'est pas
faite. Et l'exécutable n'est **pas signé** : téléchargé d'Internet plutôt que construit
localement, Windows SmartScreen le signalera.

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
createsim voir mon_vaisseau.nbt     # ou simplement : createsim mon_vaisseau.nbt
createsim                            # sans fichier : l'accueil
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

### Niveau 3 — confrontation au jeu

Les niveaux 1 et 2 vérifient que le noyau est d'accord avec lui-même. Aucun des deux ne
dit si les **équations** sont les bonnes. C'est le rôle du niveau 3, et le cahier en fait
la condition de livrabilité de L2 : *« le lot L2 n'est livrable que si au moins une
grandeur du niveau 3 a été confrontée au jeu et concorde. »*

Relevé au Stressometer sur `cachalot_volant_v4`, vaisseau posé, moulin assemblé —
`data/mesures/jeu.json`, rejoué par `tests/test_mesures_jeu.py` :

| Lecture | Attendu | Mesuré | |
|---|---|---|---|
| capacité du réseau du moulin | 8 192 su | **8 192 su** | ✅ |
| consommation, manettes moteur à l'arrêt | 0 su | **0 su** | ✅ |
| hélice centrale à fond (16 voiles, 256 tr/min) | 512 su | **8 192 su** | ❌ |
| escalier de la transmission, 16 crans | 0 → 0 tr/min | **0 → 256 tr/min** | ❌ |

Les deux premières lignes valident d'un coup toute la chaîne de génération : comptage des
voiles, plafond de 16 tr/min du moulin, 512 su par tour du palier, et l'agrégation de
`KineticNetwork`. Les deux dernières ont corrigé le modèle.

**Un palier d'hélice coûte 2,0 su/tr par voile, pas 2,0 su/tr.** Facteur 16 sur le
cachalot. La conséquence était invisible jusqu'à la mesure : son moulin ne peut pousser
qu'**une seule** hélice à fond — les trois ensemble demandent 20 480 su pour 8 192
disponibles, le réseau disjoncte et tout s'arrête. Le plafond utilisable est le cran 9,
à 94 % de charge.

**Le cran affiché par une manette est le signal émis**, `inverted` compris. Ce qui
renverse l'échelle n'est pas le levier mais son destinataire : le côté réducteur d'une
transmission analogique découple à 15 et passe en prise directe à 0. Deux manettes
voisines sur la même console ne se lisent donc pas dans le même sens, et le bandeau
l'écrit maintenant pour chacune.

### La loi de l'impact, départagée

Un point de mesure ne fait pas une loi : un impact constant de 32 su/tr expliquait tout
aussi bien les 8 192 su de l'hélice de 16 voiles. Cinq lectures l'ont tranché.

| Voiles | Régime | Lu en jeu | su/tr | su/tr/voile |
|---|---|---|---|---|
| 16 | 256 tr/min | 8 192 su | 32 | **2,0000** |
| 12 | 256 tr/min | 6 144 su | 24 | **2,0000** |
| 12 | 125 tr/min | 3 000 su | 24 | **2,0000** |
| 8 | 256 tr/min | 4 096 su | 16 | **2,0000** |
| 8 | 125 tr/min | 2 000 su | 16 | **2,0000** |

Trois rotors différents excluent l'impact constant ; 125 tr/min n'est pas sur l'escalier
des 16 crans, c'est donc un point hors grille qui établit la linéarité en régime et non
une redondance. Un test vérifie que la bibliothèque contient toujours un point qui
*exclut* l'hypothèse concurrente — une loi seulement compatible avec ses mesures n'est
pas une loi établie.

Reste une réserve, tenue explicite : le sens absolu de la poussée sur cette coque.

### Niveau 4 — non-régression

Cinq scénarios de référence, leurs traces figées dans le dépôt, rejoués à chaque
modification des tables ou du solveur. Les trois premiers niveaux disent si le modèle est
**juste** ; celui-ci dit s'il a **changé**, ce qui n'est pas la même question — une mise à
jour de mod peut très bien laisser le modèle juste et rendre le vaisseau soudain incapable
de décoller. Détail dans la section L4 plus bas.

```bash
createsim nonregression
```

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

## L5 : éprouver une variante sans la construire, et la rapporter en jeu

« Et si ? » — la question que l'analyse seule ne tranche pas. Le cahier prend l'exemple
d'une hélice soudée à la coque : sans édition, le gain de vitesse reste une extrapolation ;
avec elle, on retire les blocs de contact et on relance.

Sur le cachalot v4, c'est le moulin qui mord sur la coque par une trappe en sapin, et son
comptage de voiles est signalé non fiable. Un clic sur la trappe, `Suppr`, et le bandeau
répond : **« palier 42, 25, 12 : 134 voiles, comptage fiable »** — en 132 ms.

### Les gestes (F6.1 à F6.3)

**Clic** sur un bloc dans la vue 3D : il est sélectionné et l'onglet Édition s'ouvre, avec
son nom, sa position, la face touchée et ses propriétés éditables. Un clic sans glissement
sélectionne ; un glissement reste une orbite. Le rayon est parcouru case par case
(Amanatides et Woo) : le bloc choisi est celui qu'on **voit**, jamais celui de derrière.

| Geste | Où | Garde-fou |
|---|---|---|
| supprimer | `Suppr`, bouton | — |
| déplacer | flèches, `PgPréc` / `PgSuiv`, boutons | un bloc par case, grille entière |
| poser | palette, contre la face cliquée | types **déjà présents** dans le fichier |
| propriété | liste déroulante | valeurs vues dans le fichier pour ce type |
| annuler, refaire, original | `Ctrl+Z`, `Ctrl+Y`, menu Édition | sans limite |

Un bloc posé est un **clone** d'un bloc existant de ce type, NBT compris, en copie
profonde : régler la molette du clone ne règle pas l'original. La palette est figée au
chargement — supprimer le dernier bloc d'un type ne le retire pas de ce qu'on peut reposer.

### Les trois garde-fous du cahier

**Non destructif.** Le fichier source n'est jamais écrit. Un test fait **tout** — supprimer,
poser, déplacer, annuler, refaire, revenir à l'original, exporter — puis compare l'empreinte
SHA-256 du fichier avant et après.

**Export `.nbt`**, dans un fichier nouveau, nommé et horodaté à côté du source :
`cachalot_volant_v4--variante--20260922-143012.nbt`. Il refuse le fichier source et tout
fichier existant. Et il est **sans perte** : 5 039 et 20 659 blocs relus identiques,
**types compris**. Ce point n'allait pas de soi — le NBT des blocs était aplati au
chargement, et un bloc de structure en jeu lit une valeur au mauvais type comme zéro, sans
erreur. Le tag d'origine est désormais conservé et sert de gabarit au retypage. Tout ce que
le simulateur ne modélise pas repart tel qu'il a été lu : la **colle** (`honey_glue`,
`super_glue`) sans laquelle rien ne s'assemble en jeu, les entités de contraption, et même
le `sub_level` de Sable que porte le cargo.

**Diff chiffré**, dans un encart **permanent** sous les onglets : masse, portance, centre de
masse, marge de Stress Units, vitesse de pointe, altitude d'équilibre, chacun avec son écart
signé, en vert quand c'est un gain. La référence est une copie intacte du vaisseau évaluée
**sous les mêmes commandes et à la même altitude** que la session — sinon pousser une manette
ou simplement monter ferait apparaître des écarts que personne n'a créés. La vitesse de
pointe tient compte de l'amortissement réel axe par axe, levitite compris, par point fixe.

### Une variante dans un scénario (F6.8)

Une édition se consigne comme on la dirait, pas comme deux états de bloc :

```json
"editions": [
 { "op": "supprimer", "pos": "45,25,12" },
 { "op": "deplacer", "de": "62,4,2", "vers": "62,7,2" }
]
```

Un scénario les rejoue sur le fichier source avant le premier tick ; deux variantes du même
vaisseau se comparent courbe contre courbe avec la machinerie de L4. Figer une session
emporte sa variante.

### Sans interruption perceptible (F6.4)

Remailler tout le cruiser coûtait 219 ms ; un tick en dure 50. Le maillage est donc découpé
en **tronçons de 16³**, et une édition ne remaille que ceux dont une case a changé, plus
leurs voisins. Un test vérifie que le résultat est **exactement** celui d'une reconstruction
complète — une face oubliée à une frontière laisserait un trou.

| Coût d'une édition (médiane) | cargo, 5 039 blocs | cruiser, 20 659 blocs |
|---|---|---|
| remaillage | 7 ms | 22 ms |
| travail complet du geste | 22 ms | 52 ms |

Pour y arriver, trois organes ont appris à faire moins : les **paliers** ne retracent que
les rotors réellement touchés, avec une règle resserrée (un bloc ne peut rejoindre un rotor
que s'il lui est contigu — le demi-espace faisait retracer les dix paliers du cruiser pour
72 % des éditions) ; les organes **dépendants** ne sont refaits que si ce qu'ils lisent a
changé (le réseau cinétique ne lit que le nombre de voiles des moulins) ; et le **retour à
l'original** se fait en une passe — 230 ms au lieu de 1,6 s pour trente éditions. Un test
tire quarante éditions au hasard et vérifie que **chaque organe** égale celui d'un modèle
reconstruit de zéro.

Reste une exception assumée : toucher un **mur de ballon** relance son remplissage, ce que
le cahier classe lui-même « coût élevé » — jusqu'à 0,9 s sur le cargo. Le curseur d'attente
le dit. Le raccourcir aurait demandé d'approximer le remplissage d'Aeronautics, qui ne monte
jamais : un ballon ouvert par le bas garde son gaz. Pas question de sacrifier la géométrie
sur laquelle la portance est calculée.

### Trois défauts de fond trouvés en route

**Annuler une brèche laissait le ballon percé.** Après une brèche, la poche rétrécit et son
contour ne passe plus par le trou ; remettre le mur n'était vu par personne. La zone où les
tentatives de remplissage ont fui est maintenant retenue, et y poser un bloc étanche relance
le remplissage — la règle du cahier, qui veut un flood-fill dès qu'un bloc étanche est touché.

**Une poche en plus disparaissait de la simulation.** Le gaz est apparié aux poches par
position ; une édition qui coupe une poche en deux en ajoutait une sans gaz, et `zip` la
laissait tomber sans un mot. Le gaz est désormais réattribué au prorata des cases d'air
reprises ; ce qui a fui par la brèche est perdu, et la barre d'état le chiffre.

**Supprimer une voile ne l'invalidait pas.** L'organe ne regardait que le nom du bloc
touché — devenu de l'air.

Et deux défauts de L4 et du bandeau : une grandeur **indéfinie des deux côtés** (pas de
vitesse de pointe sans poussée, ni avant ni après) comptait comme un changement ; et après un
remplissage refait, la **molette d'un brûleur** réglait un dictionnaire que la simulation ne
lisait plus. Le bandeau est reconstruit dès que l'organe des leviers ou celui du ballon a
tourné.

### Ce que l'édition ne garantit pas

Une variante qui va bien à l'écran ne tient pas forcément en jeu. Le simulateur ne vérifie
ni la colle, ni les châssis, ni les règles d'attache de Create, ni qu'un palier accepte
d'entraîner le rotor qu'on lui greffe — l'éditeur le rappelle sous le bouton d'export. Le
simulateur dit où chercher et de combien ; l'essai en jeu tranche.

---

## Frottement : relevé au bytecode, pas à la documentation

Les modèles de frottement ont été relus directement dans les jars de l'instance, désassemblés
à `javap` — rapport complet dans [`docs/rapport-frottement-create.md`](docs/rapport-frottement-create.md),
chaque constante avec sa classe et son offset. La découverte qui a tout recadré : **le moteur
physique est Rapier** (Rust, lié en natif par `sable_rapier`). Sable prépare des forces,
Rapier intègre.

| Mécanisme | Avant | Après |
|---|---|---|
| Traînée d'enveloppe | 0,33 × N × pression | inchangée — confirmée exacte |
| Amortissement universel | ignoré | 0,09 s⁻¹ × masse |
| Traction des roues | frein faux | `frein = signal / 15` |
| Adhérence au sol | `min(f, 1)` | `fudgeFriction` : glace → 0,10 |
| Freinage et dérive des roues | absents | par seconde, anisotropes |
| Voiles de coque | ignorées | portance 0,475 et deux traînées |
| Levitite | aucune traînée | profil lent/rapide × gravité |

**L'amortissement universel est le gros morceau.** `universal_drag = 0,09` est remis à
`Rapier3D.initialize(gx, gy, gz, drag)` à côté de la gravité : c'est le taux
d'amortissement du corps rigide, en s⁻¹, pas une traînée par bloc. Sur le c1_air_cruiser —
20 659 blocs pour 839 étanches — il divise la constante de temps par **6,4**, de 60 s à 9,4 s.

**La traction des roues avait un bug.** Deux formules du moteur partagent le mot « frein » ;
le code prenait les constantes du freinage dynamique (0,075 et 0,3) pour fabriquer celui de
la traction. Une roue freinée à fond tractait encore à 62 %.

**L'amortissement est devenu un vecteur par axe.** Freinage, dérive, traînée des voiles et
levitite sont linéaires en v, donc ils entrent dans l'intégration exacte plutôt que dans la
somme explicite — mais ils sont anisotropes. Le niveau 2 reste à 0,000 %.

**Les voiles sont des ailes**, par un mixin au nom sans ambiguïté :
`compatibility.create.sails_providing_lift`. Aucun vaisseau actuel n'en profite : les 60 voiles
de coque de la flotte sont des voiles symétriques, qui ne font que freiner.

Deux simplifications restent, signalées comme limites du modèle et non tues : la masse portée
par chaque roue (F5.10, le moteur la tire de la matrice de masse inverse) et le mélange
lent/rapide du levitite (F5.11, sans la correction d'étalement de la grappe).

---

## L4 : comparer deux configurations, survivre à une mise à jour de mod

Un scénario associe quatre choses, et il faut les quatre pour qu'une exécution soit
reproductible : **le fichier**, **les réglages**, **la situation** et une séquence de
commandes **horodatée**. C'est le quatrième point qui distingue un scénario d'un simple
jeu de réglages — « brûleurs à fond » et « brûleurs à fond puis coupés à la seconde 30 »
ne décrivent pas la même manœuvre.

```bash
createsim scenario list
createsim scenario run "montee a vide" --csv trace.csv
createsim scenario compare "montee a vide" "brûleurs coupes"
createsim nonregression
```

Le format est du JSON lisible à la main, comme l'exige le cahier : un scénario se relit et
se corrige dans un éditeur de texte, sans l'outil.

```json
"commandes": [
 { "tick": 0,   "levier": "15,13,20", "valeur": 15 },
 { "tick": 600, "levier": "15,13,20", "valeur": 0 }
]
```

Dans la fenêtre, le bouton **scénario** fait trois choses : figer la session courante
(les mouvements de manette sont enregistrés au fil de l'eau, seuls les **changements**
étant consignés), rejouer un scénario sur le vaisseau courant, ou en superposer un second
pour comparer. Le cahier tranche le multi-vaisseaux : un seul à la fois, la comparaison
passe par la superposition de deux exécutions.

### Ce qui a bougé, et à partir de quand

La comparaison rend deux choses, parce qu'elles ne répondent pas à la même question.

**L'ampleur** — douze indicateurs suivis d'une exécution à l'autre : altitude finale et
max, temps de montée, vitesses, gaz, SU demandés, ticks en surcharge, ticks au sol.

**L'instant** — le premier tick où les deux traces cessent de coïncider. C'est le plus
utile des deux et le plus facile à oublier : un écart de 3 % sur l'altitude finale ne dit
pas s'il naît au départ ou s'il dérive sur toute la montée ; le tick où les courbes se
séparent, si.

### La non-régression

Cinq scénarios de référence, leurs traces figées en CSV dans le dépôt, rejoués par
`createsim nonregression`. Simulons une version d'Aeronautics où la poussée d'air chaud
gagne **3 %** :

```
ECHEC cargo — montee a vide          rupture — separation au tick 5 (0.25 s) sur « y »
         altitude finale       156.257 ->  163.610  m     +4.71 %
         altitude max          158.948 ->  167.107  m     +5.13 %
         montee                 21.750 ->   21.250  s     -2.30 %
OK    cachalot — moulin et helices en charge      identique
```

Trois pour cent sur une constante déplacent l'altitude d'équilibre de près de cinq —
et le cachalot, lui, n'en dépend pas du tout. C'est exactement ce qu'on veut savoir avant
de reconstruire un vaisseau.

Un scénario dont le vaisseau n'est pas dans le dépôt, ou qui n'a pas encore de trace de
référence, est **ignoré et non compté en échec** : confondre les deux ferait crier au loup
à chaque ajout. Et le test qui compte vraiment n'est pas celui qui vérifie que la
non-régression passe — c'est celui qui vérifie qu'elle **détecte** un changement. Une
non-régression qui passe toujours ne protège de rien, et c'est le mode de défaillance
naturel de ce genre d'outil.

### Un défaut trouvé en route

Le sol était figé à la construction de la `Simulation`. Charger un scénario avec un plan
de sol sur une session qui n'en avait pas donnait une chute sans fin — le bandeau
reconstruisait le sol de son côté, la voie scénario l'ignorait. Un seul endroit le
construit désormais, et `reset()` l'y rappelle.

---

## L3 : chercher une panne et mesurer une amélioration

Trois outils, et une exigence de fond dans chacun.

**Les courbes.** Deux ou trois grandeurs au choix, sur une fenêtre glissante réglable.
C'est là qu'on voit un vaisseau osciller autour de son altitude d'équilibre au lieu de
s'y poser — un tableau de nombres ne le montre jamais, parce que l'oscillation est dans
la *dérivée* et pas dans la valeur. Chaque série porte **sa propre échelle** : l'altitude
se compte en centaines et la vitesse en unités, les forcer sur un axe commun écraserait
l'une des deux. Une trace de référence chargée depuis un CSV se superpose en pointillé,
sur la même échelle, ce qui permet de *mesurer* une amélioration au lieu de la deviner.

**Le diagnostic.** La liste des anomalies, classée par gravité, **chacune cliquable pour
situer ses blocs dans la vue 3D** — « rotor soudé à la coque » ne sert à rien si on doit
ensuite chercher où. L'organe porte son nom donné quand il en a un. Et la distinction du
cahier est tenue visuellement : une **limite du modèle** a sa propre couleur et n'est
jamais présentée comme un défaut du vaisseau.

**La télémétrie.** Un enregistrement par tick, exporté en CSV à en-tête, lisible à la
main. Le cahier demande les **forces par source** et non par famille : une colonne par
force et par axe, nommée de la clef stable de sa source — `f_helice@11.10.10_y`. Agréger
par famille suffirait à tracer une courbe, mais pas à savoir laquelle des six hélices a
molli, ni à rejouer la trace.

**Le rejeu** relit une trace tick par tick et redessine les vecteurs enregistrés. Les
*points* d'application viennent du modèle, qui est le même : une trace se relit donc
**avec son vaisseau**, pas seule. L'aller-retour CSV est exact au flottant près.

Deux détails qui ne vont pas de soi. Une hélice à l'arrêt produit une force **nulle**,
pas une force **absente** — sans cela la liste change d'un tick à l'autre et la trace
cesse d'être rejouable. Et la liste d'anomalies n'est reconstruite que si elle a changé :
elle est recalculée à chaque tick mais ne bouge presque jamais, et rebâtir des dizaines
de widgets vingt fois par seconde ferait retomber la boucle sous son seuil.

## L2 : actionner les commandes et voir le vaisseau réagir

C'est le périmètre demandé par le cahier — le minimum vendable. Un bandeau vertical à
droite, sections repliables, valeurs modifiables en continu, **aucun bouton
« appliquer »**.

**Le bandeau n'expose que ce qui existe dans le fichier.** Un vaisseau sans roues n'a
pas de section roues. Un brûleur commandé par un levier n'est pas réglable directement :
on actionne le levier, et le brûleur suit. C'est ce qui distingue un simulateur d'un
tableur — on pilote le véhicule tel qu'il est câblé, pas ses paramètres internes.

**Tout se renomme d'un clic gauche.** Leviers, canaux de brûleurs, poches, hélices,
transmissions : le nom donné s'affiche en gras à la place du libellé technique, et
celui-ci n'est jamais perdu — la barre d'état dit « gaz principal (levier [15, 13, 20]) »
pour qu'on retrouve le bloc en jeu. Les noms vivent dans un `.noms.json` à côté du
vaisseau ; le `.nbt` d'origine n'est jamais écrit. Entrée valide, Échap annule, un nom
vide restaure le défaut.

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
