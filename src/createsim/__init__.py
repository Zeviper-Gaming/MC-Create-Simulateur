"""createsim — banc d'essai hors-jeu pour vehicules Create.

Quatre couches, avec une regle dure : le noyau ne depend jamais de l'interface.

    data/   tables de constantes + lecteur NBT. Aucune logique physique.
    model/  le vehicule apres analyse. Recalcule PAR ORGANE.
    sim/    l'etat qui evolue. Aucune dependance a l'affichage.
    cli     presentation en ligne de commande.

Distinction essentielle : le *modele* ne bouge que si on edite un bloc,
l'*etat* change a chaque tick. Remettre a zero, c'est jeter l'etat et garder
le modele.
"""

__version__ = "0.1.0"

TICK_SECONDS = 1.0 / 20.0
"""Pas de temps fixe : le tick Minecraft.

Ce n'est pas un choix d'implementation mais une contrainte de fidelite : les
constantes de remplissage des ballons et les amortissements sont exprimes en
ticks. Un pas different donnerait des transitoires faux.
"""
