# État de reprise du projet

Mise à jour : 2026-10-03. L'inventaire/DAG, le compilateur périphérique et le
runner autonome minimal sont validés. Le prior neurotransmetteur/signe est gelé
et un modèle central signé minimal est désormais exécutable et structurellement
validé. Sept régimes non ajustés ont été caractérisés de façon reproductible ;
une première campagne technique a produit 32 candidats admissibles. Une étude
aval préenregistrée montre qu'ils divergent fortement aux sorties motrices. Une
contrainte indépendante de raffinement temporel exclut maintenant un candidat et
conserve 31 survivants, mais aucun paramètre de référence n'est identifié ni gelé.
Le modèle à douze paramètres partagés est désormais enregistré comme une hypothèse
de capacité à haut risque, pas comme la dimensionalité admise de MaleCNS. Le front
se déplace vers la propagation de cet ensemble dans les calibrations locales et
hybrides plutôt que vers une élimination centrale prolongée.

Cette fiche doit être actualisée après tout commit qui modifie le score de câblage
ou les fronts structurels. En cas d'écart, le registre et le tableau de bord
recalculé font autorité.

## Objectif courant

La couverture terminale du **câblage structurel v0 est complète** : aucun fil
d'interface inventorié ne reste sans disposition. La revalidation indépendante
des regroupements, matrices candidates et proxies est également terminée. Il ne
reste donc aucun lot de câblage obligatoire avant calibration ; toute future
extension d'une enveloppe candidate ou modification de topologie ouvrira une
nouvelle version de câblage plutôt qu'une correction silencieuse.

La **revalidation scientifique indépendante du précâblage est
`independently_validated`**. Elle conserve la portée historique de 26 objets :
7 boîtes, 7 groupes, 10 fils et 2 familles de
paramètres couvrant vision, proprioception, mécanoréception et sortie motrice.
Leurs implémentations et `integration_pass` restent des preuves d'exécution et de
cardinalité ; l'acceptation scientifique supplémentaire porte sur les enveloppes
topologiques bornées, jamais sur les valeurs physiologiques ou de transfert.

L'objectif courant est de construire l'**infrastructure de calibration** avant de
chercher un comportement convaincant : inventaire versionné des familles de
paramètres, DAG de dépendances, règles de partage et d'identifiabilité, jeux de
données autorisés, représentation de l'incertitude, protocoles de gel/réouverture
et runner autonome minimal. La politique est définie par
[`ADR 0012`](decisions/0012-hierarchical-reconstructible-calibration.md) et
[`docs/calibration-methodology.md`](docs/calibration-methodology.md).

Le premier jalon de cette infrastructure est franchi. Le registre
[`calibration/parameter_families/`](calibration/parameter_families/) inventorie
19 familles : six sources basales, quatre routages, quatre transferts, trois
familles de dynamique centrale, la mécanique FlyBody conservée comme dépendance
externe gelée et l'enveloppe numérique motrice isolée comme nuisance technique.
Le [`DAG`](calibration/dependency-dag.yaml) contient huit dépendances et est validé
acyclique. Les dimensions maximales exécutables sont séparées des degrés de
liberté scientifiques encore à choisir. Le couplage historique entre routage et
gain en proprioception, mécanoréception et sortie motrice est désormais résolu à
la frontière runtime par `compiler.peripheral_routing_transfer.v0`. Il impose des
simplexes de routage explicites, des affectations de partage explicites et les
hashes des enveloppes acceptées ; il ne choisit ni route, ni gain, ni valeur.
Les 3 746 routes motrices logiques sont notamment distinguées de leurs 7 849
coefficients runtime développés.

Le runner autonome minimal est maintenant validé. Il refuse les entrées dont le
hash a dérivé, vérifie les frontières topologiques de chaque famille, interdit aux
modes fitting/validation d'accéder aux scénarios held-out et n'exécute que des
évaluateurs enregistrés dans le code. Chaque essai est conservé comme `accepted`,
`rejected`, `error` ou `skipped_budget_exhausted`; les répétitions sont comparées
par hash sémantique et aucun essai planifié ne peut disparaître du décompte.

Le run `20261002T113512989298Z--runner-validation-peripheral-parameter-compiler-v0`
a exécuté deux fois chacun des trois contrats périphériques : **6/6 essais
acceptés, zéro rejet, zéro erreur et zéro cas non déterministe**. Son hash
sémantique est `1efcfd166625598d7f259e24dad4d948ee546dcff4dce3d709defa88f6e8d34a`.
Ce run utilise des simplexes uniformes et gains unitaires éphémères ; il valide
l'infrastructure seulement et n'accepte aucune valeur de mouche. Il a été produit
depuis le commit `f90f052` avec un worktree propre. Le contrat est
documenté dans [`docs/calibration-runner.md`](docs/calibration-runner.md).

Le premier nœud de preuve du DAG est également franchi. La recette
[`evidence.transmitter_sign_prior.v0`](calibration/evidence/transmitter-sign-prior-v0.yaml)
reconstruit une ligne pour chacun des 166 700 neurones canoniques à partir des
trois sources MaleCNS v1.0 hashées. Elle trouve 166 522 enregistrements de
neurotransmetteur et conserve 178 absences explicites. Le parameter set
[`parameters.central_transmitter_sign_prior.v0`](calibration/parameter_sets/central-transmitter-sign-prior-v0.yaml)
est gelé comme dépendance de preuve, pas comme dynamique calibrée.

Le prior attribue une classe excitatrice aux 103 720 neurones cholinergiques et
une classe inhibitrice aux 22 069 neurones GABAergiques. Glutamate, histamine,
monoamines, consensus `unclear` et absences restent contextuels ou inconnus. À
l'échelle du graphe, 14 745 137 arêtes ont un prior excitateur, 4 925 557 un
prior inhibiteur et **5 912 244 restent inconnues ou dépendantes du contexte**.
Le code numérique zéro encode cette absence d'affirmation ; il ne supprime jamais
une synapse. Deux exécutions propres ont reproduit le hash sémantique
`fb3777b99eb913b41a86962cae33b8bf41a96bc0c26c25ca68ce34229a7a44da`.

Le candidat [`model.malecns_typed_signed_rate.v0`](calibration/models/malecns-typed-signed-rate-v0.yaml)
rend maintenant ce prior exécutable sans créer 25,6 millions de poids libres. Il
expose neuf efficacités partagées par classe de neurotransmetteur et trois
paramètres globaux de dynamique. Les signes acétylcholine/GABA sont contraints par
le prior gelé ; les sept classes contextuelles, `unclear` ou `missing` conservent
chacune un paramètre signé explicite. Aucun résidu par arête n'est autorisé en v0.

Le run propre
`20261003T082053529120Z--runner-validation-signed-dynamics-contract-v0` a parcouru
deux fois les **25 582 938 arêtes** : 25 582 938/25 582 938 sont assignées, les
5 912 244 arêtes inconnues/contextuelles sont exercées avec un probe non nul,
zéro arête est supprimée et le hash sémantique répété est
`c45acd00346e5ee4bdd1f93686dbcb286be385187dac1ce056e809bf852a6789`.
Cette preuve accepte la représentation sparse et la comptabilité seulement. Les
valeurs du probe, l'équation comme modèle biologique, la stabilité et tout
comportement restent explicitement non acceptés.

Le run diagnostique propre
`20261003T090226460183Z--campaign-diagnostic-central-unfitted-characterization-v0`
a ensuite exécuté sept régimes non ajustés pendant 200 ms chacun sur le graphe
complet. Une seconde exécution propre reproduit le hash sémantique
`351e883439080618af35a1e685efcd54058e8bd1f88cf206f6210d5863f41ace`.
Le régime faible sans entrée s'éteint, les régimes intermédiaires récupèrent
après la petite perturbation, tandis que le régime fort conserve un gain de
perturbation de 3,988 et atteint 96,5 % de neurones numériquement actifs. Ces
observations montrent que le banc distingue plusieurs modes, pas que l'un d'eux
est acceptable. Aucun probe, seuil ou paramètre n'est promu.

La première véritable campagne de fitting technique est maintenant exécutée et
reproductible. `campaign.technical_neural_dynamics_pilot.v0` reconstruit 32
candidats Sobol sur les douze paramètres partagés, puis soumet chacun à trois
scénarios train et deux scénarios de validation locale distincts des probes
diagnostiques. Les deux runs propres
`20261003T132548498439Z--campaign-technical-neural-dynamics-pilot-v0` et
`20261003T132656622969Z--campaign-technical-neural-dynamics-pilot-v0` reproduisent
le hash sémantique
`68b0166693c21734d0cf2c7dc195e2377e156a21c2ee96aa30ec89512289a8ff`.

Les **32/32 candidats passent** : zéro saturation numérique, gain de perturbation
maximal entre 0,633 et 0,937, résidu final maximal entre 5,85e-7 et 0,170 et
demi-récupération stable en 2 à 11 pas. Ce résultat valide une large admissibilité
technique sur les cinq scénarios mais révèle surtout une non-identifiabilité : les
critères ne distinguent aucun vecteur de référence. L'ensemble reconstructible est
conservé, sans sélection post hoc, sans gel et sans claim physiologique.

L'étude diagnostique préenregistrée
`diagnostic.central_ensemble_motor_sensitivity.v0` a ensuite comparé les 32
membres sur trois motifs synthétiques, chaque stimulus étant soustrait à un sham
partant du même état initial. Elle observe exhaustivement 96 réponses aux 815
terminaux moteurs MaleCNS bruts, sans traverser le transfert moteur, les
actionneurs, le corps ou le monde. Les runs propres
`20261003T143327383160Z--campaign-diagnostic-central-ensemble-motor-sensitivity-v0`
et
`20261003T143423135154Z--campaign-diagnostic-central-ensemble-motor-sensitivity-v0`
reproduisent le hash sémantique
`c7dc9aa65e1bc3d030b32e4e97474d3ca9f7fb523290fc2962b12308c386917e`.

Le résultat est **hautement sensible**, pas identifiant : la distance cosinus P90
entre motifs candidats atteint 1,124 et le rapport d'amplitudes P90/P10 atteint
17,596 ; aucune des 96 réponses n'est numériquement nulle. Un candidat arbitraire
changerait donc matériellement la suite. L'étude ne classe aucun membre et ne
fournit aucune vérité biologique ; elle impose d'ajouter une contrainte centrale
non comportementale indépendante ou de propager l'ensemble complet.

La première contrainte indépendante est désormais exécutée. Le protocole
`constraint.central_timestep_convergence.v1` compare, pendant la même durée de
400 ms, les réponses stimulus-moins-sham du CNS complet intégrées à 5,0, 2,5 et
1,25 ms. Il contrôle séparément les 166 700 neurones canoniques et les 815 sorties
motrices brutes, sans transfert moteur, corps, monde, rendu ni comportement. Les
deux runs propres
`20261003T185726564390Z--campaign-central-timestep-convergence-v1` et
`20261003T190037078175Z--campaign-central-timestep-convergence-v1` reproduisent le
hash sémantique
`12667c186699cdb3cbdbbd4f275a2522f4c0ebd8fe3675e872dc214057db6062`.

Les **31/32 candidats passent**. Le candidat 30 est rejeté car son erreur relative
L2 sur l'état central complet atteint 0,286 à 5 ms (limite 0,15) et 0,116 à
2,5 ms (limite 0,075). Aucun survivant n'est classé ou choisi. La v0, conservée
comme résultat méthodologique supersédé, avait aussi révélé neuf inversions
d'ordre sous 1e-4 dues aux réductions sparse CUDA ; la v1 a préenregistré ce
plancher numérique sans modifier les seuils matériels. Le nouvel ensemble est
donc plus portable numériquement, pas plus physiologique ni comportemental.

L'[`ADR 0013`](decisions/0013-ensemble-propagation-and-model-adequacy.md)
formalise la correction de trajectoire. Les neuf efficacités par classe de
neurotransmetteur et les trois paramètres globaux constituent le plus petit modèle
signé actuellement exécutable ; ils ne sont pas une hypothèse biologique validée.
Il n'est pas nécessaire d'obtenir un candidat central unique avant de calibrer les
sources basales et les interfaces. Les 31 membres seront propagés comme ensemble
d'incertitude, avec des paramètres aval déclarés communs, robustes, conditionnés
ou conjointement identifiés. Les résidus locaux et par classe/région serviront de
test de capacité avant toute nouvelle version centrale plus expressive.

La méthode de revue est fixée par
[`ADR 0008`](decisions/0008-independent-scientific-wiring-reaudit.md) et
[`validation.scientific_wiring_reaudit`](ledger/validations/scientific-wiring-reaudit.yaml).
Chaque secteur doit être reconstruit depuis les données brutes versionnées et les
sources primaires sans prendre le manifeste courant comme recette, puis comparé
relation par relation. Aucun paramètre scientifique n'est accepté par cette
clôture. Les futures campagnes peuvent désormais prendre les hashes acceptés comme
frontière topologique gelée, selon le contrat de calibration séparé.

Le ruleset `wiring-revalidation.rules.v1` et son runner constituent le premier
palier reproductible de cette revue. Le run
`wiring-revalidation-20260927T183911Z` a reconstruit depuis les sources brutes
12 658 terminaux uniques et 7 124 groupes, puis comparé leurs appartenances et
dispositions au précâblage : aucune différence et aucune exception inattendue ne
subsistent. Le supplément officiel a aussi reproduit exactement les 2 628
relations R7/R8 `bodyId`→colonne optique. Cette passe ne régénère pas encore les
familles de matrices candidates fines. La sortie motrice, la mécanoréception, la
proprioception et la vision disposent maintenant de clean builders acceptés ;
aucune famille fine ne reste bloquée. La portée et les commandes sont documentées dans
[`docs/wiring-revalidation.md`](docs/wiring-revalidation.md).

Le run global `wiring-revalidation-20260928T205213Z` a reconstruit les 815
terminaux moteurs et 441 groupes dans une destination vide, puis produit 3 746
relations groupe→actionneur, soit 7 849 relations terminal→actionneur. Le hash
sémantique `0cd753e02283e42f3bf963e3fe223b7728b1a343da5b2db78e6414d4de8c5ca3`
a été reproduit par un second clean build. Après seulement, la matrice exécutable
a été ouverte : ses 7 849 relations sont toutes confirmées, sans ajout, retrait
ni doublon. Les contraintes négatives de côté et d'appendice, la capacité miroir
et la couverture des 102 actionneurs passent ; les 10 groupes non représentés
restent des `sink`. Cette validation accepte l'enveloppe topologique candidate,
pas une correspondance muscle biologique exacte et aucun des 7 849 gains.

Le run global `wiring-revalidation-20260929T140029Z` a ensuite reconstruit les
4 291 terminaux mécanorécepteurs et leurs 323 groupes sans ouvrir la matrice
exécutable. Les règles utilisent seulement les annotations MaleCNS, les drapeaux
canoniques et les inventaires physiques FlyBody : sept observables de charge par
patte, positions/vitesses des appendices du même côté et trois composantes de
force grossière pour la tête ou le thorax. Elles produisent 2 108 relations
groupe→observable, soit 28 514 relations terminal→observable. Le hash sémantique
`70e71d9a5c36edcc8ce5f01e367c7a5349f8d1942ea3b1a72e0e0a9868cc9fd2`
a été reproduit par un second clean build. Après seulement, le précâblage a été
ouvert : toutes les relations sont confirmées, sans ajout, retrait ni doublon.
Les contraintes de côté, position de patte, appendice et segment, ainsi que les
capacités de 131 clés miroir, passent sans exception. Cette validation accepte
l'enveloppe candidate locale, pas la physiologie récepteur→signal et aucun des
28 514 coefficients de transfert.

Le run global `wiring-revalidation-20260929T144947Z` a ensuite reconstruit les
1 454 terminaux proprioceptifs et leurs 262 groupes depuis les annotations, les
drapeaux canoniques et le seul inventaire articulaire FlyBody. Les règles
produisent 1 439 arêtes candidates directes pour 171 groupes et 553 arêtes proxy
pour 91 groupes, soit 1 992 relations groupe→observable et 10 518 relations
terminal→observable. Le hash sémantique
`782b98d147b5ecd15861dca0241d7fabf2995b1b9b6ef5b9c50d8e94ea5dd665`
a été reproduit dans une deuxième destination vide avant ouverture du
précâblage. Les 10 518 relations existantes sont toutes confirmées sans ajout,
retrait, doublon ni exception ; les contraintes de côté, appendice, spécialisation
FeCO, partition direct/proxy et capacité miroir passent. Cette acceptation porte
sur l'enveloppe structurelle locale. Les proxies de déformation/vibration et les
10 518 paramètres continus restent non calibrés.

Le run global `wiring-revalidation-20260929T182220Z` clôt la vision et la revue
globale. Il reconstruit 6 098 terminaux visuels et 4 802 unités d'enregistrement :
1 332 colonnes publiées contenant 2 628 R7/R8, 3 463 photorécepteurs sans colonne
et 7 HBeyelet proxy. Une représentation normalisée de six ensembles de sources
compte exhaustivement 3 091 576 relations candidates, soit 3 665 347 relations
terminal→observable développées. Le hash
`130b45c285aa86f97886648a607de29617422e9c8c94aed51be711ae5a836152`
a été reproduit avant ouverture du précâblage ; les 6 098 décisions terminales et
4 802 enveloppes existantes correspondent exactement. Les contraintes de côté,
palette, injectivité des colonnes et séparation HBeyelet passent sans exception.
Les 4 795 enregistrements discrets, 6 098 gains et dynamiques visuelles restent
non calibrés.

Le projet adopte désormais une politique d'**automatisation proportionnée par
règles avec rapports d'exception**. Les travaux répétitifs doivent, lorsque c'est
rentable, être exprimés comme des règles versionnées appliquées hors quota ; chaque
exécution comptabilise ce qui a été traité, exclu, bloqué ou surpris, puis produit
les cas ambigus pour une décision compacte. Cette préférence ne justifie pas une
infrastructure plus coûteuse que le traitement direct des rares cas restants. Le
contrat est dans [`docs/rules-first-automation.md`](docs/rules-first-automation.md)
et l'[`ADR 0009`](decisions/0009-proportional-rules-first-automation.md).

L'[`ADR 0011`](decisions/0011-reconstructible-peripheral-topology.md) fixe le
jalon de sortie de cette revalidation : sources immuables, règles versionnées et
petite table d'exceptions doivent reconstruire chaque famille dans une destination
vide avec le même hash sémantique. Les matrices générées sont des caches. Les
espaces candidats doivent rester locaux et leur capacité être quantifiée ; les
paramètres discrets de routage sont séparés des paramètres continus de fonction de
transfert. Les tests doivent inclure contraintes négatives, symétries/topographies
pertinentes et gold standards masqués non circulaires lorsqu'ils existent.

Le **banc d'exécution du vrai graphe MaleCNS est maintenant implémenté et mesuré**.
Il transforme les 25 582 938 arêtes canoniques en CSR float32, compare chaque run
GPU à une référence CPU déterministe et compile les boîtes déclarées en un vecteur
de 17 884 entrées et un décodeur de 815 sorties motrices vers 102 commandes. Le
profil temporel `benchmark.malecns.leaky_tanh.v0` est explicitement
`BENCHMARK ONLY / UNCALIBRATED` : sa normalisation, sa fuite et ses paramètres
aléatoires déterministes sont des choix d'ingénierie et aucunement une dynamique
biologique acceptée.

Le run `benchmark-20260927T081439Z`, produit depuis le commit moteur `ba7e9f4`, a
simulé 5,0 secondes du graphe complet en 2,077 secondes de noyau sur la RTX 4060
Laptop : **481,4 pas/s**, soit **2,407 fois le temps réel** au pas arbitraire de
5 ms. Le CSR occupe 195,8 Mio, le pic alloué
sur le GPU 210,2 Mio et l'accord CPU/GPU présente une erreur absolue maximale de
1,49e-08 après trois pas. La trace compacte des 102 commandes, six métriques et
256 sondes neuronales occupe 1,22 Mio. Ces mesures démontrent la faisabilité
d'exécution, pas la validité du comportement produit.

Le contrat de ce banc est dans
[`docs/runtime-execution-benchmark.md`](docs/runtime-execution-benchmark.md). Le
benchmark ne remplace aucune preuve de câblage scientifique et ne constitue pas
une calibration.

La **boucle incarnée réelle est maintenant exécutable et enregistrable**. À
chaque pas de 5 ms, elle lit la vision FlyBody, les contacts et la proprioception,
traverse toutes les boîtes d'entrée, avance le vrai graphe MaleCNS sur CUDA,
décode ses 815 sorties motrices, applique 102 commandes protégées par une enveloppe
numérique explicitement non physiologique, puis exécute 50 sous-pas MuJoCo natifs.
Il n'existe aucun contrôleur comportemental externe dans ce chemin.

Le run `closed-loop-20260927T124854Z`, produit depuis le commit moteur `add05df`,
a calculé **une seconde fermée complète** : 200 pas neuronaux, 10 000 pas MuJoCo
et une nouvelle acquisition visuelle à chaque pas neuronal. Il a pris 16,854 s,
soit 0,0593 fois le temps réel. Les capteurs et interfaces ont pris 8,079 s,
MaleCNS 2,799 s et la physique 2,072 s. La trajectoire autonome de 200 trames
occupe 971 225 octets et son rejeu contre une instance FlyBody neuve a passé le
contrat de modèle.

Le format `the_fly_matrix.physical_trajectory` conserve `qpos`, `qvel`, commandes,
forces, observations articulaires, contacts, rétine, résumés neuronaux et
provenance. Le player ne dépend pas du contrôleur producteur. Les modes headless,
live et replay partagent la même construction FlyBody et le même shell de viewer.
L'architecture est actée dans l'[`ADR 0010`](decisions/0010-controller-independent-physical-trajectories.md)
et documentée dans [`docs/embodied-runtime.md`](docs/embodied-runtime.md).

Cette validation est uniquement une preuve d'intégration. La règle neuronale,
les paramètres d'interface et le garde-fou moteur restent non calibrés. Le front
d'ingénierie suivant consiste à inventorier les familles et leurs dépendances,
puis à préparer l'injection de jeux de paramètres versionnés dans cette unique
boucle. L'inspection du replay et le profilage de la vision restent des outils du
baseline et du futur runner, pas un substitut à cet inventaire.

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
- Sortie motrice : **79 %** historique ; topologie candidate indépendamment validée, gains inconnus.
- Proprioception : **81 %** historique ; topologie candidate indépendamment validée, paramètres inconnus.
- Entrées sensorielles non résolues : **96 %**.
- Clamps basaux : **87 %**.
- Vision : **79 %** historique ; topologie candidate indépendamment validée, enregistrements et gains inconnus.
- Mécanosensation : **74 %** historique ; topologie candidate indépendamment validée, coefficients inconnus.
- Corps physique : **100 %**.
- Monde physique : **100 %**.
- Évaluation/fermeture de boucle : **20 %**.
- Couverture terminale de la carte : **100 % sans disposition `blocked`**.
- Revalidation scientifique : **`independently_validated` ; 4/4 familles fines, zéro exception et zéro famille bloquée**.
- Calibration : **inventaire/DAG, compilateur périphérique et runner validés ; 1 famille de preuve gelée, 31/32 candidats centraux passent le filtre de raffinement temporel mais restent non identifiés, sensibilité aval élevée et reproductible, aucun jeu complet promu**.

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
conservées et classifiées. Les **110 tests** actuels passent, y compris les
garde-fous du runner, les tests de compilation, le runtime et les validations
structurelles.

## Statut structurel

Le câblage structurel v0 est terminé : couverture terminale 100 %, quatre familles
fines sur quatre indépendamment validées, aucune exception inattendue et aucune
famille bloquée. Aucun travail structurel n'est requis pour ouvrir la calibration.
Les raffinements futurs restent possibles, mais deviennent de nouvelles versions
topologiques et invalident explicitement les campagnes qui dépendaient des hashes
précédents.

## Front de calibration

**Ouvert.** Les campagnes sont reconstructibles, le modèle central signé minimal
est exécutable et sa première campagne technique est terminée. Le filtre de
raffinement temporel retire un candidat matériellement dépendant du pas de temps,
mais laisse 31 survivants non identifiés. Leur sensibilité aux sorties motrices
centrales reste élevée et la suffisance des douze paramètres partagés est un
risque ouvert. Le prochain front est une campagne locale ou hybride consciente de
l'ensemble, pas une semaine de filtres CNS internes ni le choix d'un membre dont
la sortie paraît préférable.

1. Inventorier les familles de paramètres : rôle, type, dimension, unités,
   partage, origine, données autorisées, identifiabilité et incertitude.
2. Construire leur DAG de dépendances et geler pour chaque campagne les hashes de
   topologie, règles et exceptions issus du câblage accepté.
3. Compiler les transferts de preuves, statistiques basales et priors de
   neurotransmetteurs/signes avec confiance et masques inconnus.
4. Séparer les paramètres logiques de routage/transfert des vecteurs runtime et
   verrouiller leurs enveloppes candidates sans choisir de valeur.
5. Construire le runner autonome minimal avec comptabilité exhaustive des essais,
   splits locaux et comportementaux, critères préenregistrés et artefacts immuables.
6. Calibrer et geler les familles locales avant les contraintes globales, sauf
   non-identifiabilité documentée justifiant une campagne conjointe.
7. Conserver séparément le meilleur essai et l'ensemble scientifiquement
   admissible ; un échec ne doit pas augmenter silencieusement la capacité.
8. N'ouvrir le protocole stimulus/sham `evaluation_only` qu'après gel des
   paramètres et du protocole.

À ce jour : une campagne déterministe de transfert de preuve a été acceptée ; elle
n'a ajusté aucune valeur. Le compilateur factorisé vérifie maintenant les 1 992
coefficients proprioceptifs, 2 108 mécanorécepteurs et 7 849 moteurs à partir de
routes et transferts séparés. Son test uniforme/unitaire est synthétique, en
mémoire et explicitement non calibré. Le runner autonome reproduit ce contrôle en
six essais exhaustivement comptabilisés et protège déjà frontières, lignée,
budgets et scénarios tenus à l'écart. Le contrat central signé ajoute neuf
efficacités de classe et trois paramètres globaux, tous non ajustés, et couvre
exhaustivement le graphe avec un probe structurel non promouvable. Aucun parameter
set complet n'a été promu et aucune cible comportementale n'est autorisée. L'étude
aval préenregistrée est terminée : elle classe l'ensemble comme hautement sensible
en motif et en amplitude, sans sélectionner de candidat. La première contrainte
de portabilité numérique retire le candidat 30 et conserve 31 survivants sans les
classer. Le prochain lot doit définir une campagne locale, basale ou hybride qui
propage l'ensemble et mesure les résidus révélateurs de capacité ; les scopes
locaux périphériques deviennent le front principal. Les fichiers de
`calibration/` déterminent l'ordre effectif ; cette section en est le résumé humain.

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
connectome_benchmark.bat  # vrai MaleCNS CPU/GPU + trace compacte non calibrée
closed_loop_record.bat    # vrai MaleCNS en boucle fermée + trajectoire physique
physical_replay.bat       # viewer autonome de la dernière trajectoire physique
closed_loop_live.bat      # même boucle directement dans le viewer, même si lente
diagnostic_viewer.bat     # viewer MuJoCo + faux CNS isolé, non scientifique
cycle_topology.bat        # topologie cyclique structurelle du vrai MaleCNS
wiring_revalidation.bat   # règles indépendantes, comparaisons et exceptions input/output
calibration_status.bat     # inventaire des familles + cohérence/acyclicité du DAG
compile_calibration_evidence.bat # prior neurotransmetteur/signe reproductible
parameter_compiler_check.bat # factorisation routage/transfert, test structurel seulement
calibration_runner_check.bat # runner autonome, six essais d'infrastructure non calibrants
signed_dynamics_contract_check.bat # couverture signée exhaustive, probes non calibrants
characterize_signed_dynamics.bat # 7 régimes centraux non ajustés, diagnostic seulement
fit_signed_dynamics_pilot.bat # 32 candidats centraux, fitting technique sans comportement
central_ensemble_sensitivity.bat # sensibilité des 32 candidats sur 815 sorties brutes
constrain_central_timestep_v1.bat # filtre 5/2,5/1,25 ms, aucun comportement
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
