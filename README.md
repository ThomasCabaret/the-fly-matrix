# The Fly Matrix

`the-fly-matrix` construit une simulation incarnée de drosophile dans laquelle le
connectome MaleCNS reste le substrat de calcul principal. Les adaptateurs entre le
monde physique, le système nerveux et les actionneurs doivent rester locaux,
explicites, de faible capacité et auditables.

Le contrat scientifique de référence est
[`drosophila_virtual_fly_project_contract.md`](drosophila_virtual_fly_project_contract.md).

## Commandes Windows

- `download_data.bat` télécharge ou contrôle les trois fichiers MaleCNS minimaux.
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
  arbitraires reproductibles, ainsi que les routages aval proprioceptif et
  mécanorécepteur, le routage aval visuel, les afférences sensorielles non résolues
  et les sorties CNS explicitement motrices.
- `dashboard.bat` recalcule puis ouvre la carte globale et le tableau de bord.
- `build_preview.bat` recalcule le tableau de bord sans ouvrir le navigateur.

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
elles ne sont jamais enregistrées comme paramètres scientifiques.

Le manifeste proprioceptif sépare volontairement les deux côtés de l'adaptateur
type C. Côté physique, `flybody-proprioception-channels.csv` relie maintenant les
102 articulations biologiques aux adresses `qpos` et `qvel` du modèle compilé :
la boîte `sensor.proprioception` extrait ainsi 102 positions et 102 vitesses de
façon exécutable. Côté CNS, `proprioception-routes.parquet` fixe les 1 454 routes
terminales MaleCNS regroupées en 262 instances. La correspondance scientifique
entre ces 204 observables et ces 262 instances reste volontairement inconnue ;
les contraintes et vibrations sont elles aussi différées. Finir ces deux moitiés
fiables ne fabrique donc pas une jonction biologique implicite.

Le manifeste mécanorécepteur applique la même séparation : 4 291 afférences
tactiles ou mécanoréceptrices sont divisées en 323 instances type C selon le
groupe annoté, le nerf d'entrée, la sous-classe, les types MANC/MaleCNS et le côté.
Les routes terminales vers les `bodyId` sont exactes, tandis que la correspondance
avec les surfaces de contact, vibrations et autres observables physiques reste à
établir. Les modalités non annotées sont conservées comme inconnues et ne sont pas
reclassées par hypothèse.

Côté physique, `flybody-touch-channels.csv` fixe désormais les six capteurs de
contact au sol réellement compilés par FlyGym, un par patte. Chaque canal expose
16 scalaires : présence du contact, force, couple, position, normale et tangente,
soit 96 observables exécutables. L'inventaire conserve également les 57 segments
autorisés à entrer en collision et leurs 69 paires avec le sol. Les charges locales
hors pattes et la correspondance de ces six canaux avec les 323 instances
mécanoréceptrices restent explicitement différées.

Le manifeste visuel conserve une instance type C par neurone sensoriel du lobe
optique : 6 091 photorécepteurs et 7 cellules `HBeyelet`, soit 6 098 routes
terminales un-à-un vers MaleCNS. L'audit empêche explicitement d'utiliser
`assignedOlHex1` et `assignedOlHex2` comme coordonnées d'entrée : leurs 23 720
valeurs appartiennent exclusivement à des neurones internes `ol_intrinsic`. La
correspondance pixel/ommatidie vers photorécepteur reste donc inconnue jusqu'à
l'obtention d'une source rétinotopique indépendante.

Côté physique, `flybody-vision-channels.csv` décrit deux caméras composées de 721
ommatidies chacune. Pour chaque ommatidie, le manifeste conserve le canal actif
jaune ou pâle de la sortie FlyGym `(2, 721, 2)`, soit 1 442 échantillons
normalisés. Le smoke test effectue un véritable rendu MuJoCo local deux fois et
vérifie un résultat déterministe. La jonction de ces 1 442 échantillons vers les
6 098 afférences MaleCNS reste séparée et explicitement différée.

Le manifeste moteur couvre les 708 neurones `vnc_motor` et 107 neurones
`cb_motor`, avec une instance type E par `bodyId`. L'audit des nerfs de sortie
isole 191 autres neurones endocrines ou efférents au lieu de les transformer en
commandes musculaires. Les 815 activités sont maintenant étiquetées par 441
groupes reproductibles `(sous-classe, type, côté)` sans sommation ni perte ; les
10 neurones sans type restent des singletons `bodyId`. Cette granularité repose
sur les annotations MaleCNS publiées et fixe le fil routeur→transduction. La
jonction séparée des 441 groupes vers les 102 actionneurs FlyBody, ainsi que les
signes, gains et dynamiques musculaires, restent à construire.

À l'autre extrémité, `flybody-actuator-channels.csv` fixe désormais les 102
adresses `ctrl` du modèle compilé et leur articulation cible, sans choisir la
valeur des commandes. Cent actionneurs retrouvent un groupe de configuration
FlyBody ; les deux actionneurs d'haltères, bien que présents et limités en force
dans notre modèle, sont signalés comme dépourvus de configuration spécifique.
La jonction scientifique entre les 815 sorties neuronales et ces 102 commandes
reste explicitement différée.

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
