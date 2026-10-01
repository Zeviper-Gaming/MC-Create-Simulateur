"""Extraire les masses de blocs telles que Sable les resout en jeu (etape 1).

Le simulateur devinait la classe de masse d'un bloc par mots-cles (« stone »,
« oak », suffixes…). Le jeu, lui, la tire de ses datapacks : des definitions
`data/*/physics_block_properties/*.json`, chacune rattachee a un bloc ou a un
tag, appliquees dans un ordre precis. La devinette ratait les blocs de metal —
102 blocs de fer comptes 1 au lieu de 4 sur le cargo, 13 % de masse en moins.

Ce script lit les jars de l'instance EN LECTURE SEULE et reproduit la
resolution du jeu, pas a pas :

    1. les tags de blocs de Minecraft, de NeoForge et de chaque mod, fusionnes
       et resolus recursivement ;
    2. les definitions de proprietes physiques, avec leur priorite ;
    3. leur ORDRE d'application, qui decide des egalites de priorite. Lu au
       bytecode :
         - `SimpleJsonResourceReloadListener.prepare` range les fichiers dans
           une `HashMap`, remplie dans l'ordre d'une `TreeMap`
           (`MultiPackResourceManager.listResources`) ;
         - `ResourceLocation.compareTo` compare le chemin, puis l'espace de noms ;
         - `ResourceLocation.hashCode` vaut `31 * espace.hashCode() + chemin.hashCode()` ;
         - `PhysicsBlockPropertiesDefinitionLoader.apply` parcourt la HashMap puis
           trie par priorite (`Comparator.comparingInt`, tri stable).
       A priorite egale, c'est donc l'ordre d'iteration d'une HashMap Java qui
       tranche. Il est reproduit ici exactement.

Resultat : `data/tables/masses_resolues.json`, ou chaque definition porte le
jar et le chemin d'ou elle vient. Le simulateur n'a plus besoin de l'instance a
l'execution.

    python tools/extraire_masses.py
    python tools/extraire_masses.py --instance "C:/.../Instances/Autre pack"
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from datetime import date
from pathlib import Path

INSTANCE = Path(r"C:/Users/Florian/curseforge/minecraft/Instances/La Bonne Compagnie")
INSTALL = Path(r"C:/Users/Florian/curseforge/minecraft/Install")
MINECRAFT = "1.21.1"
DEPOT = Path(__file__).resolve().parents[1]
SORTIE = DEPOT / "data" / "tables" / "masses_resolues.json"

#: la masse par defaut, `PhysicsBlockPropertyTypes` (static init, dconst_1)
MASSE_DEFAUT = 1.0
#: la priorite par defaut d'une definition, `PhysicsBlockPropertiesDefinition`
#: (codec, sipush 1000)
PRIORITE_DEFAUT = 1000
DOSSIER = "physics_block_properties"


# --- le hachage de Java, a l'identique --------------------------------------
def _int32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v >= 0x80000000 else v


def java_string_hash(s: str) -> int:
    """`String.hashCode()` : sur les unites UTF-16, en arithmetique 32 bits."""
    h = 0
    unites = s.encode("utf-16-be")
    for i in range(0, len(unites), 2):
        h = (31 * h + ((unites[i] << 8) | unites[i + 1])) & 0xFFFFFFFF
    return _int32(h)


def resource_location_hash(espace: str, chemin: str) -> int:
    """`ResourceLocation.hashCode()`, lu au bytecode : 31 * espace + chemin."""
    return _int32(31 * java_string_hash(espace) + java_string_hash(chemin))


def ordre_hashmap(cles: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """L'ordre d'iteration d'une `java.util.HashMap` remplie dans cet ordre.

    Table de 16 cases au premier ajout, doublee des que la taille depasse les
    3/4 ; case = `(n - 1) & (h ^ (h >>> 16))`. Un redimensionnement partage
    chaque case en deux listes sans en changer l'ordre relatif : a la fin, on
    parcourt les cases dans l'ordre, et dans une case, l'ordre d'insertion.
    """
    n, taille = 16, 0
    for _ in cles:
        taille += 1
        if taille > n * 0.75:
            n *= 2
    rangees = []
    for rang, (espace, chemin) in enumerate(cles):
        h = resource_location_hash(espace, chemin) & 0xFFFFFFFF
        case = (h ^ (h >> 16)) & (n - 1)
        rangees.append((case, rang, (espace, chemin)))
    return [cle for _case, _rang, cle in sorted(rangees)]


# --- lecture des jars ---------------------------------------------------------
class Lecture:
    """Tout ce que les jars declarent, lu une fois."""

    def __init__(self):
        self.tags: dict[str, list[str]] = {}
        self.remplacements: list[str] = []
        self.definitions: dict[tuple[str, str], dict] = {}
        self.doublons: list[str] = []
        self.ignores: list[str] = []
        self.espaces: set[str] = set()
        self.jars: list[dict] = []

    def jar(self, chemin: Path) -> None:
        with zipfile.ZipFile(chemin) as z:
            self.jars.append({"jar": chemin.name, "octets": chemin.stat().st_size})
            self._archive(z, chemin.name)

    def _archive(self, z: zipfile.ZipFile, origine: str) -> None:
        for nom in z.namelist():
            if nom.startswith("META-INF/jarjar/") and nom.endswith(".jar"):
                with zipfile.ZipFile(io.BytesIO(z.read(nom))) as interne:
                    self._archive(interne, origine + "!/" + nom.rsplit("/", 1)[-1])
                continue
            morceaux = nom.split("/")
            if len(morceaux) >= 3 and morceaux[0] in ("data", "assets") and morceaux[1]:
                self.espaces.add(morceaux[1])
            if not nom.endswith(".json") or morceaux[0] != "data" or len(morceaux) < 4:
                continue
            espace = morceaux[1]
            if morceaux[2] == "tags" and len(morceaux) >= 5 and morceaux[3] in ("block", "blocks"):
                self._tag(z, nom, espace, "/".join(morceaux[4:])[:-5], origine)
            elif morceaux[2] == DOSSIER:
                self._definition(z, nom, espace, "/".join(morceaux[3:])[:-5], origine)

    def _json(self, z, nom, origine):
        brut = z.read(nom).decode("utf-8-sig").strip()
        if not brut:
            self.ignores.append("%s!/%s : fichier vide" % (origine, nom))
            return None
        try:
            return json.loads(brut)
        except json.JSONDecodeError as exc:
            self.ignores.append("%s!/%s : JSON illisible (%s)" % (origine, nom, exc))
            return None

    def _tag(self, z, nom, espace, chemin, origine) -> None:
        doc = self._json(z, nom, origine)
        if doc is None:
            return
        cle = "%s:%s" % (espace, chemin)
        if doc.get("replace"):
            self.remplacements.append("%s (%s)" % (cle, origine))
            self.tags[cle] = []
        valeurs = self.tags.setdefault(cle, [])
        for v in doc.get("values", []):
            ident = v if isinstance(v, str) else (v or {}).get("id")
            if ident:
                valeurs.append(ident)

    def _definition(self, z, nom, espace, chemin, origine) -> None:
        if not chemin:
            self.ignores.append("%s!/%s : nom de fichier vide" % (origine, nom))
            return
        doc = self._json(z, nom, origine)
        if doc is None:
            return
        cle = (espace, chemin)
        if cle in self.definitions:
            # meme identifiant dans deux packs : le pack du dessus l'emporte, et
            # l'ordre des mods n'est pas connu hors du jeu — on le dit
            self.doublons.append("%s:%s (%s et %s)" % (espace, chemin,
                                                       self.definitions[cle]["source"], origine))
        doc["source"] = "%s!/%s" % (origine, nom)
        self.definitions[cle] = doc


def resoudre(lecture: Lecture):
    cache: dict[str, frozenset] = {}

    def membres(tag: str, pile: tuple = ()) -> frozenset:
        if tag in cache:
            return cache[tag]
        out = set()
        for v in lecture.tags.get(tag, ()):
            if v.startswith("#"):
                if v[1:] not in pile:
                    out |= membres(v[1:], pile + (tag,))
            else:
                out.add(v)
        cache[tag] = frozenset(out)
        return cache[tag]

    # L'ordre du jeu : TreeMap (chemin puis espace, sur l'emplacement du fichier),
    # puis HashMap, puis tri stable par priorite.
    triees = sorted(lecture.definitions, key=lambda c: (DOSSIER + "/" + c[1] + ".json", c[0]))
    iteration = ordre_hashmap(triees)
    finale = sorted(iteration, key=lambda c: int(lecture.definitions[c].get("priority", PRIORITE_DEFAUT)))

    definitions = []
    for rang, cle in enumerate(finale):
        doc = lecture.definitions[cle]
        proprietes = doc.get("properties") or {}
        surcharges = {cond: float(v["sable:mass"])
                      for cond, v in (doc.get("overrides") or {}).items()
                      if "sable:mass" in (v or {})}
        if "sable:mass" not in proprietes and not surcharges:
            continue                       # ne touche pas a la masse
        selecteur = doc.get("selector", "")
        if selecteur.startswith("#"):
            blocs = sorted(membres(selecteur[1:]))
        elif ":" in selecteur:
            blocs = [selecteur]
        else:
            lecture.ignores.append("%s : selecteur non reconnu %r" % (doc["source"], selecteur))
            continue
        definitions.append({
            "id": "%s:%s" % cle,
            "rang": rang,
            "priorite": int(doc.get("priority", PRIORITE_DEFAUT)),
            "source": doc["source"],
            "selecteur": selecteur,
            "masse": float(proprietes["sable:mass"]) if "sable:mass" in proprietes else None,
            "surcharges": surcharges,
            "blocs": blocs,
        })

    # Les egalites que l'ordre de la HashMap tranche, dites en clair
    egalites = []
    for i, a in enumerate(definitions):
        for b in definitions[i + 1:]:
            if a["priorite"] != b["priorite"] or a["masse"] is None or b["masse"] is None:
                continue
            if a["masse"] == b["masse"]:
                continue
            communs = sorted(set(a["blocs"]) & set(b["blocs"]))
            if communs:
                egalites.append({
                    "definitions": [a["id"], b["id"]],
                    "priorite": a["priorite"],
                    "gagnante": b["id"],
                    "masse_retenue": b["masse"],
                    "blocs_concernes": len(communs),
                    "exemples": communs[:6],
                })
    return definitions, egalites


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--instance", type=Path, default=INSTANCE)
    parser.add_argument("--install", type=Path, default=INSTALL)
    parser.add_argument("--sortie", type=Path, default=SORTIE)
    args = parser.parse_args(argv)

    instance_json = json.loads((args.instance / "minecraftinstance.json").read_text(encoding="utf-8"))
    chargeur = instance_json.get("baseModLoader", {}).get("name", "")        # neoforge-21.1.248
    version_nf = chargeur.split("-", 1)[1] if "-" in chargeur else ""
    jars = [args.install / "versions" / MINECRAFT / (MINECRAFT + ".jar"),
            args.install / "libraries" / "net" / "neoforged" / "neoforge" / version_nf
            / ("neoforge-%s-universal.jar" % version_nf)]
    jars += sorted((args.instance / "mods").glob("*.jar"))

    lecture = Lecture()
    for jar in jars:
        if not jar.is_file():
            print("introuvable :", jar, file=sys.stderr)
            return 2
        lecture.jar(jar)

    definitions, egalites = resoudre(lecture)
    doc = {
        "schema": 1,
        "genere_par": "tools/extraire_masses.py",
        "genere_le": date.today().isoformat(),
        "instance": args.instance.name,
        "chargeur": chargeur,
        "minecraft": MINECRAFT,
        "regle": ("Masse d'un etat de bloc : 0 s'il n'a pas de forme de collision "
                  "(PhysicsBlockPropertyHelper.getMass -> VoxelNeighborhoodState.isSolid), "
                  "sinon la derniere definition qui le couvre, dans l'ordre 'rang' "
                  "(HashMap puis tri stable par priorite), sa surcharge d'etat "
                  "l'emportant sur sa valeur de base ; a defaut, %.1f." % MASSE_DEFAUT),
        "masse_defaut": {"valeur": MASSE_DEFAUT,
                         "source": "PhysicsBlockPropertyTypes.MASS, static init (dconst_1)"},
        "definitions": definitions,
        "egalites_tranchees": egalites,
        "espaces_de_noms": sorted(lecture.espaces),
        "tags_remplaces": lecture.remplacements,
        "definitions_en_double": lecture.doublons,
        "ignores": lecture.ignores,
        "sources": lecture.jars,
        "hors_champ": ("Les datapacks propres a un monde (dossier saves/*/datapacks) ne "
                       "sont pas lus : ils peuvent ajouter des tags ou des definitions."),
    }
    args.sortie.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    blocs = sum(len(d["blocs"]) for d in definitions)
    print("%d jars lus, %d tags, %d definitions de masse (%d affectations de bloc), %d egalite(s) tranchee(s)"
          % (len(lecture.jars), len(lecture.tags), len(definitions), blocs, len(egalites)))
    for e in egalites:
        print("  egalite a priorite %d : %s -> %s gagne (%d blocs, ex. %s)"
              % (e["priorite"], " / ".join(e["definitions"]), e["gagnante"],
                 e["blocs_concernes"], ", ".join(e["exemples"][:3])))
    if lecture.doublons:
        print("  ATTENTION doublons :", lecture.doublons)
    print("ecrit :", args.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
