# The Fly Matrix

`the-fly-matrix` construit une simulation incarnée de drosophile dans laquelle le
connectome MaleCNS reste le substrat de calcul principal. Les adaptateurs entre le
monde physique, le système nerveux et les actionneurs doivent rester locaux,
explicites, de faible capacité et auditables.

Le contrat scientifique de référence est
[`drosophila_virtual_fly_project_contract.md`](drosophila_virtual_fly_project_contract.md).

Pour reprendre le projet sans le contexte des conversations :

1. lire [`PROJECT_STATE.md`](PROJECT_STATE.md) pour l'état courant et les fronts restants ;
2. lire [`docs/wiring-methodology.md`](docs/wiring-methodology.md) pour la définition
   du câblage, les statuts et le calcul des pourcentages ;
3. appliquer [`docs/provenance-policy.md`](docs/provenance-policy.md) à toute nouvelle
   décision de branchement ;
4. consulter `ledger/` pour la source de vérité détaillée et les prochaines actions.

## Commandes Windows

- `download_data.bat` télécharge ou contrôle les trois tables MaleCNS principales
  et le supplément de 109 Ko sur les colonnes optiques R7/R8.
- `setup.bat` crée `.venv` avec Python 3.12 et installe le profil demandé.
- `setup_gpu.bat` installe PyTorch CUDA et vérifie un calcul réel sur le GPU.
- `status.bat` affiche l'état de l'environnement, des données et du registre.
- `verify_install.bat` relance le contrôle complet données/GPU/FlyBody/MuJoCo/Graphviz.
- `run_analysis.bat` régénère l'inventaire local MaleCNS/FlyBody, construit les
  manifestes de câblage locaux puis, si le jeton est configuré, compare les
  populations avec neuPrint et mesure les signatures anatomiques ROI de sept
  groupes d'interface prioritaires.
- `run_wiring_smoke.bat` régénère le manifeste des clamps puis exécute toutes les
  routes olfactives, gustatives et thermo-hygrosensorielles avec des valeurs
  arbitraires reproductibles, ainsi que les transductions candidates proprioceptive
  et mécanoréceptrice, leurs routages aval, la transduction visuelle R7/R8 par
  colonnes publiées, le routage aval visuel, les afférences sensorielles non
  résolues et les sorties CNS explicitement motrices.
  Les valeurs de secours encore injectées pour les canaux bloqués prouvent la
  continuité du code, mais ne valent pas fermeture de leur câblage.
- `dashboard.bat` recalcule puis ouvre la carte globale et le tableau de bord.
- `build_preview.bat` recalcule le tableau de bord sans ouvrir le navigateur.

The next dashboard generation will add an exhaustive interactive wiring map. Its
data contract, semantic-zoom rules, traceability requirements, and initial local
web architecture are recorded in
[`ADR 0003`](decisions/0003-interactive-wiring-map.md).

Chaque script affiche ses étapes, conserve un code de sortie exploitable et attend
une touche avant de fermer sa console.

Profils de setup disponibles :

```text
setup.bat                    environnement de développement minimal
setup.bat -Profile audit     outils d'audit des tables MaleCNS
setup.bat -Profile body      FlyGym / MuJoCo
setup.bat -Profile full      audit + corps + backend GPU MuJoCo Warp
```

PyTorch/CUDA est volontairement séparé du setup général : `setup_gpu.bat` utilise
`requirements-gpu-cu126.txt`, puis refuse de conclure au succès tant qu'un calcul
réel n'a pas été exécuté sur la carte NVIDIA.

`requirements-lock.txt` enregistre le snapshot exact de l'environnement ayant passé
`verify_install.bat`. `pyproject.toml` reste la spécification maintenable par profils.

## Accès neuPrint

Les tables MaleCNS locales suffisent pour commencer l'inventaire et le câblage.
Les requêtes distantes et certaines morphologies demanderont ensuite un jeton
personnel neuPrint :

1. Se connecter à `https://neuprint.janelia.org`.
2. Ouvrir le menu du compte, puis **Account**, et copier le jeton complet.
3. Copier `.env.example` vers `.env` et renseigner
   `NEUPRINT_APPLICATION_CREDENTIALS`.

Le fichier `.env` est ignoré par Git. Le jeton ne doit jamais être partagé ni
versionné.

L'audit distant n'enregistre que des métadonnées publiques, les effectifs des
requêtes, les signatures ROI et leurs écarts avec les fichiers locaux. Le jeton
n'est jamais copié dans `data/derived/` ni dans les rapports.

## Principe de suivi

Le répertoire `ledger/` est la source de vérité. Il contient une fiche par boîte,
par groupe anatomique, par fil, par famille de paramètres et par validation. Les rapports présents dans
`reports/generated/` seront produits depuis ce registre et ne devront pas être
maintenus manuellement.

Le pourcentage affiché est un indicateur structurel, pas une mesure de réussite
scientifique. Il agrège séparément l'inventaire, le routage, l'implémentation, les
paramètres et la validation. Une inconnue reste donc visible au lieu d'être masquée
par une boîte déclarée globalement « en cours ».

Le tableau de bord place désormais en tête un indicateur plus strict de **câblage
exécutable**. Il exclut entièrement le réglage des paramètres et la calibration.
Il atteint 100 % seulement lorsque les groupes terminaux et leurs routes sont
vérifiés et que toutes les boîtes et liaisons peuvent s'exécuter avec des paramètres
injectés, même arbitraires. L'ancien indice structurel reste affiché à titre
secondaire.

« Exécutable » ne signifie pas que chaque relation biologique est connue. Chaque
canal doit toutefois finir dans une boîte ou une politique explicite : branchement
exact, boîte paramétrable, clamp basal, proxy physique ou terminal sans effecteur.
Un canal encore alimenté directement par le smoke test reste bloquant. La règle
détaillée et l'exigence de cohérence par secteur sont fixées dans
[`ADR 0002`](decisions/0002-exhaustive-terminal-coverage.md).

`run_analysis.bat` produit également, sous `data/derived/inventory/`, une table des
groupes d'interface et un Parquet de leurs membres. Ces résultats sont reproductibles
à partir des données brutes locales et volontairement exclus de Git.
`interface-first-tier.csv` propose le premier niveau selon l'axe le plus fiable de
chaque population (`entryNerve` pour de nombreuses entrées, `exitNerve` pour les
sorties, type ou sous-classe ailleurs). `interface-subgroups.csv` pousse ensuite le
découpage sur les axes locaux pertinents, et `interface-decomposition-audit.csv`
mesure leur couverture. Une proposition n'est promue en fiche `ledger/groups/`
avec un `parent_id` qu'après audit anatomique ; elle ne devient donc jamais une vérité
scientifique par simple effet du script.

Quand le jeton neuPrint est présent, `roi-audit.json` synthétise les ROI primaires
dominantes, `roi-signatures.csv` conserve les agrégats complets et
`roi-neuron-signatures.jsonl` le détail par neurone. Pour cette convention,
les synapses post-synaptiques décrivent l'entrée anatomique et les synapses
pré-synaptiques la sortie. Ces fichiers sont des observations de morphologie
grossière : une ROI dominante ne vaut pas attribution fonctionnelle.

Pour les modalités volontairement neutralisées, le câblage reste explicite.
`data/derived/wiring/basal-clamp-channels.csv` décrit les canaux terminaux par
nerf, type, côté et sous-classe pertinente, tandis que
`basal-clamp-routes.parquet` relie chaque canal aux `bodyId` MaleCNS exacts. Les
valeurs d'activité basale n'apparaissent pas dans ces manifestes : elles seront
traitées uniquement pendant la phase de calibration.

Le runtime minimal dans `src/the_fly_matrix/runtime.py` sait instancier les boîtes
type A générées, diffuser une valeur injectée par canal vers chaque `bodyId` et
fusionner les activités dans un tampon d'entrée CNS type D. Le smoke test utilise
des valeurs pseudo-aléatoires uniquement pour vérifier le passage des données ;
elles ne sont jamais enregistrées comme paramètres scientifiques. À terme, ces
valeurs ne peuvent entrer que par les ports ou paramètres de boîtes déclarées :
les injections directes actuellement utilisées pour certains canaux visuels,
proprioceptifs et sensoriels résiduels sont une dette de câblage suivie, pas une
solution finale.

Le cœur CNS utilise directement la table creuse publiée, sans en créer une copie
géante dans le dépôt. `central-node-index.parquet` attribue un indice stable aux
211 577 `bodyId` annotés et conserve leurs degrés et poids synaptiques entrants
et sortants. Sur les 151 856 684 lignes brutes, 26 028 386 relient deux neurones
annotés ; les 125 828 298 lignes touchant un fragment de segmentation non annoté
sont comptées puis exclues explicitement. Le runtime parcourt les lots Arrow et
calcule un entraînement synaptique à un saut avec les poids entiers publiés. Cette
opération ferme le chemin structurel entrée→CNS→sortie motrice, sans choisir de
seuil, signe, constante de temps, non-linéarité ni activité physiologique.

Le manifeste proprioceptif sépare volontairement les deux côtés de l'adaptateur
type C. Côté physique, `flybody-proprioception-channels.csv` relie maintenant les
102 articulations biologiques aux adresses `qpos` et `qvel` du modèle compilé :
la boîte `sensor.proprioception` extrait ainsi 102 positions et 102 vitesses de
façon exécutable. Côté CNS, `proprioception-routes.parquet` fixe les 1 454 routes
terminales MaleCNS regroupées en 262 instances. Entre les deux,
`proprioception-input-candidates.parquet` contient 1 439 arêtes locales candidates
contraintes par nerf d'entrée, côté, appendice et sous-classe réceptrice. Elles
relient 171 instances, couvrant 986 neurones, à des positions ou vitesses
articulaires plausibles sans leur attribuer de valeur. Les 91 instances restantes
(468 neurones) restent explicites : 82 attendent une mesure de contrainte, 5 une
mesure de vibration et 4 une contrainte du notum. Le runtime exige des valeurs
externes de smoke test pour ces terminaux au lieu de les mettre silencieusement à
zéro. Aucune de ces valeurs ni aucun des 1 439 coefficients n'est une calibration.

Le manifeste mécanorécepteur applique la même séparation : 4 291 afférences
tactiles ou mécanoréceptrices sont divisées en 323 instances type C selon le
groupe annoté, le nerf d'entrée, la sous-classe, les types MANC/MaleCNS et le côté.
Les routes terminales vers les `bodyId` sont exactes. En amont,
`mechanosensation-input-candidates.parquet` relie les sept observables de charge de
chaque patte — présence du contact, trois forces et trois couples — aux canaux dont
le nerf et le côté désignent la même patte. Il utilise également les positions et
vitesses de 19 articulations FlyBody pour les antennes, ailes, haltères et pièces
buccales du même côté. Les 16 canaux PDMN du notum reçoivent en plus les trois
composantes de force nette du thorax central, et les 4 canaux ON péri-optiques
celles de la tête. Les 2 108 arêtes candidates couvrent ainsi les 323 instances et
les 4 291 neurones, sans fixer aucun coefficient. Cette dernière association reste
volontairement grossière : le modèle expose ici une tête et un thorax centraux, et
le câblage n'invente donc aucune localisation gauche/droite.
`mechanosensation-transduction-channel-audit.csv` atteste la couverture de chacun
des 323 canaux terminaux. Les 1 306 arêtes issues des contacts et les 802 arêtes
issues du mouvement articulaire sont suivies par deux fils distincts dans le
registre. Les modalités non annotées ne sont pas reclassées par hypothèse.

Côté physique, `flybody-touch-channels.csv` fixe désormais les six capteurs de
contact au sol réellement compilés par FlyGym, un par patte. Chaque canal expose
16 scalaires : présence du contact, force, couple, position, normale et tangente,
soit 96 observables exécutables. L'inventaire conserve également les 57 segments
autorisés à entrer en collision et leurs 69 paires avec le sol. Les sept observables
de charge utiles par patte alimentent désormais la matrice candidate décrite
ci-dessus. `flybody-local-touch-channels.csv` ajoute deux appels explicites à
`Simulation.get_bodysegment_contact_forces` pour la tête et le thorax, soit six
composantes de force exécutables. Les autres charges locales restent absentes tant
qu'aucun terminal représenté ne les exige.

Le manifeste visuel conserve une instance type C par neurone sensoriel du lobe
optique : 6 091 photorécepteurs et 7 cellules `HBeyelet`, soit 6 098 routes
terminales un-à-un vers MaleCNS. L'audit empêche explicitement d'utiliser
`assignedOlHex1` et `assignedOlHex2` comme coordonnées d'entrée : leurs 23 720
valeurs appartiennent exclusivement à des neurones internes `ol_intrinsic` et ne
sont toujours pas détournées. Une source indépendante est maintenant intégrée :
le supplément officiel `optic-column-type-assignments-v1.0.xlsx` fixe
l'appartenance de 2 628 photorécepteurs R7/R8 à 1 332 colonnes optiques nommées,
avec leur côté et leur classe pale/jaune. Les 3 377 R1–R6, 85
`R7R8_unclear`, un `R7_unclear` absent du supplément et les 7 `HBeyelet` restent
explicites, soit 3 470 canaux sans colonne publiée dans cette source.

Côté physique, `flybody-vision-channels.csv` décrit deux caméras composées de 721
ommatidies chacune. Pour chaque ommatidie, le manifeste conserve le canal actif
jaune ou pâle de la sortie FlyGym `(2, 721, 2)`, soit 1 442 échantillons
normalisés. Le smoke test effectue un véritable rendu MuJoCo local deux fois et
vérifie un résultat déterministe. La nouvelle boîte de transduction exécute les
2 628 R7/R8 documentés jusqu'au routeur MaleCNS. Elle exige une correspondance
injective externe des 1 332 colonnes vers les ommatidies du même œil, avec
compatibilité pale/jaune. Le smoke test injecte une correspondance arbitraire mais
valide uniquement pour tester le flux : aucun alignement spatial ni coefficient de
phototransduction scientifique n'est persisté.

Selon le contrat de couverture exhaustive, le secteur visuel n'est donc pas encore
terminé. Les 2 628 R7/R8 publiés sont une sous-relation mieux contrainte dans la
même pile visuelle ; les 3 470 autres canaux doivent recevoir une sous-matrice
paramétrable dans cette pile, et non un clamp basal localisé ni une injection
directe du smoke test.

Le manifeste moteur couvre les 708 neurones `vnc_motor` et 107 neurones
`cb_motor`, avec une instance type E par `bodyId`. L'audit des nerfs de sortie
isole 191 autres neurones endocrines ou efférents au lieu de les transformer en
commandes musculaires. Les 815 activités sont maintenant étiquetées par 441
groupes reproductibles `(sous-classe, type, côté)` sans sommation ni perte ; les
10 neurones sans type restent des singletons `bodyId`. Cette granularité repose
sur les annotations MaleCNS publiées et fixe le fil routeur→transduction. La
jonction séparée des 441 groupes vers les 102 actionneurs FlyBody est désormais
structurellement exhaustive. La matrice creuse contraint 804 neurones de 431
groupes vers les actionneurs compatibles avec leur grande catégorie anatomique,
leur nerf de sortie et leur côté. Elle expose 7 849 gains libres sans leur
attribuer de valeur. Les 13 neurones `am`, les 67 `pm` et la paire `PS349` de
`rm` couvrent les antennes et le proboscis. Les cinq `rm` du nerf optique et les
six `xm` de nerfs accessoires restent des terminaux explicites sans commande,
car FlyBody ne représente pas leurs effecteurs. Les signes, gains et dynamiques
musculaires relèvent donc maintenant de la calibration, pas du câblage.

À l'autre extrémité, `flybody-actuator-channels.csv` fixe désormais les 102
adresses `ctrl` du modèle compilé et leur articulation cible, sans choisir la
valeur des commandes. Cent actionneurs retrouvent un groupe de configuration
FlyBody ; les deux actionneurs d'haltères, bien que présents et limités en force
dans notre modèle, sont signalés comme dépourvus de configuration spécifique.
La topologie candidate entre les 815 sorties neuronales et ces 102 commandes est
fixée ; ses signes, gains et dynamiques restent explicitement à calibrer.

Le smoke test ne s'arrête plus au vecteur `ctrl`. Il construit également un
FlyBody articulé dans un monde MuJoCo, applique les 102 commandes pendant vingt
pas physiques, puis relit les 102 positions et vitesses articulaires par
l'interface proprioceptive exacte. Deux exécutions repartant du même état sont
identiques bit à bit et l'état commandé diffère du témoin passif. Pour protéger ce
test structurel de valeurs volontairement arbitraires, les commandes y sont
bornées par une enveloppe `tanh × 10⁻³`; cette enveloppe n'appartient ni au modèle
scientifique ni aux paramètres persistés. La boucle physique exécutable est donc
fermée, sans prétendre produire un mouvement biologiquement plausible.

Le manifeste sensoriel résiduel ferme la couverture des entrées inventoriées sans
inventer leur fonction. Il route individuellement 1 883 neurones encore hors des
modalités établies : 1 712 `unknown_sensory`, 57 `chemosensory`, 11
`mechanosensory_tbc` et 103 sans classe. Avec les modalités déjà câblées, les
17 884 `bodyId` de l'union sensorielle suivie disposent ainsi d'une route CNS
exacte. Leur origine physique et leur transduction restent inconnues.

## Rattachement Git distant

Une fois le dépôt distant créé :

```text
git remote add origin <URL_DU_DEPOT>
git push -u origin main
```
