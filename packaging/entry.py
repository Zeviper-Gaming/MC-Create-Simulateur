"""Script d'entree que PyInstaller empaquette : il n'ajoute rien, il appelle
`createsim.gui.main`. Les arguments viennent tels quels de Windows — un `.nbt`
glisse sur l'icone arrive en premier argument."""
from createsim.gui import main

if __name__ == "__main__":
    raise SystemExit(main())
