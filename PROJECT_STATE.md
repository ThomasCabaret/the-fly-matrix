# État de reprise du projet

Mise à jour : 2026-09-26, précâblage scientifique rétrogradé et placé sous
revalidation indépendante avant calibration.

Cette fiche doit être actualisée après tout commit qui modifie le score de câblage
ou les fronts structurels. En cas d'écart, le registre et le tableau de bord
recalculé font autorité.

## Objectif courant

La couverture terminale du **câblage structurel v0 est complète** : aucun fil
d'interface inventorié ne reste sans disposition. Cette couverture exécutable
n'est cependant plus considérée comme une acceptation scientifique des
regroupements, matrices candidates ou proxies. La découverte puis la correction
d'une confusion antérieure entre corps annotés et neurones impose de recontrôler
le raisonnement ayant produit ces relations, et pas seulement le périmètre du
graphe central.

Le front actif est donc la **revalidation scientifique indépendante du
précâblage**, avant toute calibration des familles concernées. Le registre marque
26 objets `revalidation_required` : 7 boîtes, 7 groupes, 10 fils et 2 familles de
paramètres couvrant vision, proprioception, mécanoréception et sortie motrice.
Leurs implémentations et `integration_pass` restent des preuves d'exécution et de
cardinalité, pas des preuves biologiques. Les groupes et routes auparavant trop
affirmatifs ont été rétrogradés à `proposed` et leur confiance à `low`, sans
supprimer les manifestes ni les données.

La méthode de revue est fixée par
[`ADR 0008`](decisions/0008-independent-scientific-wiring-reaudit.md) et
[`validation.scientific_wiring_reaudit`](ledger/validations/scientific-wiring-reaudit.yaml).
Chaque secteur doit être reconstruit depuis les données brutes versionnées et les
sources primaires sans prendre le manifeste courant comme recette, puis comparé
relation par relation. Aucun paramètre scientifique n'est accepté et aucune
calibration des objets possédés par cette validation ne doit commencer avant sa
clôture.

Le **prochain lot d'ingénierie** est un banc d'exécution du vrai graphe MaleCNS,
avant toute campagne de calibration. Il doit fournir une référence CPU
déterministe, un backend GPU creux, des mesures de mémoire et de débit, des runs
du graphe complet et de sous-graphes déclarés, ainsi qu'un export de traces pour
rejeu hors ligne dans MuJoCo. Le premier run visible devra réellement traverser
MaleCNS et les boîtes déclarées ; il pourra employer un profil dynamique arbitraire
mais versionné `BENCHMARK ONLY / UNCALIBRATED`, et son comportement ne constituera
aucun résultat scientifique.

Le contrat de ce banc est dans
[`docs/runtime-execution-benchmark.md`](docs/runtime-execution-benchmark.md). Sa
construction peut avancer pendant la revalidation du câblage, mais elle ne lève
aucun des 26 blocages scientifiques.

Un viewer physique temps réel est maintenant disponible via
`diagnostic_viewer.bat`. Il utilise un faux CNS récurrent de 64 états, déterministe
par seed, qui lit les 102 positions/vitesses articulaires et commande les 102
adresses FlyBody. Il contourne explicitement MaleCNS et la transduction motrice,
affiche en permanence `NOT MALECNS / NOT CALIBRATION` et ne modifie aucun statut
scientifique. Son profil interactif utilise un pas diagnostique de 0,5 ms, un
contrôleur à 100 Hz et un rendu à 30 FPS ; le pas physique natif de 0,1 ms reste
accessible par option. La séparation est actée dans
[`ADR 0006`](decisions/0006-isolated-physical-viewer-diagnostic.md).

Une analyse structurelle de la récurrence du vrai MaleCNS est disponible via
`cycle_topology.bat`. L'analyse corrigée conserve les 211 577 corps annotés dans
un registre par corps, mais calcule le graphe neuronal sur les 166 700 corps
canoniques seulement. Elle marque séparément l'accessibilité depuis les 17 884
entrées et la capacité à atteindre les 815 sorties motrices. Les quatre classes
obtenues sont 165 494 neurones du cœur causal entrée→sortie, 1 126 accessibles
sans conséquence sur les sorties motrices modélisées, 9 capables d'atteindre une
sortie sans être accessibles depuis les entrées déclarées et 71 dans aucun des
deux ensembles. Ces étiquettes décrivent le périmètre actuel ; elles ne déclarent
pas les neurones biologiquement inutiles.

Les composantes fortement connexes sont exactes. En revanche, la profondeur BFS
multi-source est comprimée et ne mesure ni une profondeur biologique ni la taille
réelle des cycles ; l'ancienne lecture « retours surtout locaux » est retirée.
La méthode et les limites sont décrites dans
[`docs/connectome-cycle-topology.md`](docs/connectome-cycle-topology.md).

La prochaine analyse topologique ne cherchera pas à assimiler les SCC à des
modules. Elle testera une hypothèse de **modularité hiérarchique quasi
feed-forward** : chaque module doit admettre un ordre interne majoritairement
feed-forward avec des skips et retours surtout locaux, tandis que le graphe dirigé
des modules conserve ses arêtes et peut former des cycles macroscopiques longs.
Cette hypothèse doit pouvoir être rejetée si aucune partition stable ne l'explique.

La définition normative est désormais celle de
[`ADR 0002`](decisions/0002-exhaustive-terminal-coverage.md) : chaque canal doit
avoir une disposition `exact`, `parameterized`, `basal`, `proxy`, `sink` ou
`blocked`. Une boîte noire locale paramétrable termine valablement un câblage même
si sa correspondance interne est inconnue. En revanche, une activité fournie
directement par le smoke test à la place d'une boîte reste `blocked`.
Le score historique du registre mesure aussi la maturité des décompositions et des
routes. Il ne doit donc pas être confondu avec la couverture terminale : celle-ci
est désormais exhaustive dans la carte, sans canal d'entrée ni groupe moteur
`blocked`, alors que l'indicateur global reste inférieur à 100 %.

La première carte interactive exhaustive est désormais implémentée. Elle exporte
depuis les manifestes locaux 31 041 nœuds et 55 198 relations : 1 552 observables
physiques, 8 895 boîtes d'entrée, 17 884 entrées CNS, 815 sorties CNS, 441 groupes
moteurs et 102 actionneurs. Les terminaux bloqués restent visibles au lieu d'être
filtrés. Après le présent lot, elle compte 2 212 entrées `basal`, 6 585
`parameterized`, 98 `proxy` et aucune entrée `blocked`. Côté sortie, 431 groupes
sont `parameterized` et les 10 groupes sans effecteur représenté sont explicitement
`sink`, pas `blocked`. La carte offre zoom/panoramique, focus sectoriel sans retrait de topologie,
recherche et panneau de traçabilité. Elle ne contient aucune valeur de calibration.
L'architecture, les invariants visuels et le contrat de traçabilité sont actés en anglais dans
[`ADR 0003`](decisions/0003-interactive-wiring-map.md).

## État synthétique

- Maturité historique du câblage : **81 %**.
- Graphe central MaleCNS : **100 % structurel**.
- Sortie motrice : **79 %**, précâblage exécutable à revalider.
- Proprioception : **81 %**, précâblage exécutable à revalider.
- Entrées sensorielles non résolues : **96 %**.
- Clamps basaux : **87 %**.
- Vision : **79 %**, précâblage exécutable à revalider.
- Mécanosensation : **74 %**, précâblage exécutable à revalider.
- Corps physique : **100 %**.
- Monde physique : **100 %**.
- Évaluation/fermeture de boucle : **20 %**.
- Couverture terminale de la carte : **100 % sans disposition `blocked`**.
- Revalidation scientifique : **26 objets `revalidation_required`**.
- Calibration des familles concernées : **bloquée avant revalidation**.

Le présent lot supprime la dernière injection directe d'entrée. Les 1 883
afférences sensorielles résiduelles conservent leurs routes `bodyId` exactes et sont
désormais possédées par trois sources nominales type A disjointes : 57 canaux
`chemosensory`, 11 `mechanosensory_tbc` et 1 815 canaux de modalité inconnue. Chaque
canal a un paramètre explicite non calibré. Cette disposition `basal` est un joker
structurel réversible, sans attribution de capteur physique ni valeur
physiologique. Le smoke test traverse ces trois boîtes avant le routeur et atteste
qu'aucun vecteur terminal n'est injecté directement. La politique est actée dans
[`ADR 0004`](decisions/0004-residual-sensory-nominal-sources.md).

La carte corrige en parallèle la disposition des 10 groupes moteurs sans effecteur
FlyBody : les 11 neurones concernés sont des terminaux `sink` explicites, conformément
au runtime qui consomme leur activité sans produire de commande. Il ne reste donc
aucun terminal `blocked` dans les interfaces cartographiées. Cela ne signifie pas
que les paramètres ou les comportements sont calibrés.

Le dernier lot supprime l'injection directe des 91 groupes proprioceptifs qui
attendaient une mesure de contrainte ou de vibration. Les 171 groupes déjà reliés
au corps conservent leurs 1 439 arêtes candidates `parameterized`. Les 91 autres,
couvrant 468 neurones, traversent désormais 553 arêtes `proxy` limitées aux
cinématiques du même appendice et du même côté lorsque l'annotation le permet.
L'unique groupe sans nerf ni côté connus ne voit que cinq articulations centrales
thorax–tête/abdomen. Les 262/262 groupes sont exécutables sans vecteur terminal de
secours et aucun coefficient n'est fixé.

Le score global historique était resté à 86 %. Le score proprioceptif passe de 86 à
85 % parce que le nouveau fil proxy est honnêtement enregistré au palier
`candidates_known`, ce qui augmente le dénominateur de cet ancien indicateur. Il
ne s'agit pas d'une régression du réseau : les canaux `blocked` proprioceptifs
passent de 91 à zéro. Les 1 883 afférences résiduelles sont maintenant terminées
par les sources nominales décrites ci-dessus, sans modifier ce lot proprioceptif.

Le dernier lot élimine toute injection directe dans les 6 098 terminaux visuels.
Les 2 628 R7/R8 présents dans le supplément officiel conservent leur colonne
biologique exacte et un enregistrement colonne→ommatidie externe. Les 3 463 autres
photorécepteurs possèdent chacun un choix discret parmi les 721 ommatidies du même
œil et un gain libre. Les 7 HBeyelet, absents du capteur FlyBody, utilisent un proxy
explicitement déclaré : la moyenne lumineuse de l'œil indiqué par leur instance,
avec un gain libre. Le smoke test calcule désormais les 6 098 activités depuis le
rendu MuJoCo et les paramètres de boîte; il n'accepte plus de vecteur terminal de
secours. Aucun choix rétinotopique ni gain scientifique n'a été persisté.

Le score visuel passe de 86 à 89 % et le score global de 85 à 86 %. La différence
restante dans ce secteur mesure surtout la résolution et la validation à affiner,
pas un fil pendant : la disposition terminale visuelle est exhaustive.

Le dernier lot ferme l'exécution physique après la sortie motrice. Le runtime
construit un FlyBody articulé dans MuJoCo, vérifie l'ordre des 102 actionneurs,
applique réellement les commandes pendant 20 pas, puis relit les 102 positions et
vitesses par l'interface proprioceptive. Le rejeu depuis le même état est identique
bit à bit et diffère du témoin passif. Une enveloppe numérique propre au smoke test
protège MuJoCo des paramètres arbitraires; elle n'est pas une calibration. Le
secteur corps physique était alors passé de 94 à 100 %. Le score global restait arrondi à 85 %,
mais son composant de routage des fils passe de 69 à 70 %.

Le lot d'interface n'avait pas modifié ce score. `wiring_map.bat` compile l'application
React/Cytoscape, régénère `reports/generated/wiring-map/wiring-map.json`, démarre
un serveur HTTP strictement local et ouvre la vue. La disposition fixe les colonnes
monde/corps → modèles source → adaptateurs → entrées CNS → MaleCNS → sorties CNS
→ groupes moteurs → actionneurs afin que deux générations restent comparables.

Le smoke test traverse toujours 17 884 entrées CNS et 815 sorties motrices, toutes
canoniques, mais le runtime central est maintenant limité aux 25 582 938 arêtes
entre les 166 700 neurones canoniques. Les 211 577 lignes d'annotation restent
conservées et classifiées. Les **51 tests**, leurs 5 sous-tests et le smoke test
bout en bout passent après cette correction.

## Fronts structurels restants

1. Refaire indépendamment la décomposition et les relations visuelles, puis
   comparer chaque choix exact, candidat ou proxy au précâblage actuel.
2. Refaire le même audit pour la proprioception, notamment les 91 proxies de
   contrainte/vibration et leurs frontières appendice/côté.
3. Refaire le même audit pour la mécanoréception et les proxies de mouvement ou de
   contact local.
4. Refaire le même audit pour les 441 groupes moteurs et les ensembles
   d'actionneurs permis, en conservant séparément les 815 routes `bodyId` brutes.
5. Corriger les sources vagues ou cassées et enregistrer, pour chaque règle, la
   source, l'affirmation soutenue, l'hypothèse restante et le test associé.

## Front de calibration

**En pause pour les 26 objets possédés par la revalidation scientifique.** Les
éléments ci-dessous restent la suite prévue, mais ne sont pas la prochaine action.

1. Construire le banc CPU/GPU du vrai MaleCNS, mesurer le coût réel, puis produire
   un court run non calibré et son rejeu hors ligne sans choisir de gains
   physiologiques ni de comportement cible.
2. Construire un runner qui sépare les scénarios train, validation, diagnostic et
   `evaluation_only`, puis enregistrer le baseline non calibré.
3. Inventorier les familles de paramètres des interfaces sensorielles, motrices,
   basales et des éventuels feedbacks externes, avec unités, origines et scopes.
4. Calibrer d'abord l'activité bornée et récupérable, puis les interfaces locales
   et la stabilité corporelle neutre sur sol plat.
5. Geler les paramètres avant d'ouvrir le protocole stimulus/sham tenu à l'écart.

À ce jour : aucune campagne n'a été exécutée, aucun parameter set n'a été promu et
aucune cible comportementale n'est autorisée. Les fichiers de `calibration/`
déterminent désormais le prochain lot ; cette section en est le résumé humain.

Les `next_action` du registre et le tableau de bord déterminent l'ordre concret du
prochain lot ; cette liste ne remplace pas ces sources de vérité.

## Reproduction locale

```text
setup.bat                 # si l'environnement n'existe pas
download_data.bat         # si les tables MaleCNS ou le supplément optique sont absents
status.bat
run_analysis.bat          # inventaires et manifestes ; neuPrint si jeton présent
run_wiring_smoke.bat      # reconstruction et parcours structurel complet
dashboard.bat             # état HTML/DOT recalculé
wiring_map.bat            # carte exhaustive interactive locale
diagnostic_viewer.bat     # viewer MuJoCo + faux CNS isolé, non scientifique
cycle_topology.bat        # topologie cyclique structurelle du vrai MaleCNS
```

Les données brutes, les artefacts `data/derived/`, les exécutions `runs/` et les
rapports générés sont ignorés par Git. Un clone contient la méthode et le registre,
mais doit régénérer ces artefacts. Le rapport principal est alors
`reports/generated/project-status.html`.

La méthode complète est dans [`docs/wiring-methodology.md`](docs/wiring-methodology.md)
et la politique de sources dans
[`docs/provenance-policy.md`](docs/provenance-policy.md).
La méthode de calibration et son registre sont dans
[`docs/calibration-methodology.md`](docs/calibration-methodology.md) et
[`calibration/`](calibration/README.md).
