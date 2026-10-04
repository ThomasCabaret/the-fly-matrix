# Instructions de travail — The Fly Matrix

## Finalité du projet

Construire une simulation incarnée dans laquelle MaleCNS reste le substrat de
calcul principal. Les interfaces entre monde, corps, connectome et actionneurs
doivent être locales, explicites, paramétrables et auditables. Un résultat visible
mais produit par un contrôleur comportemental externe n'est pas un succès du
projet.

La couverture terminale et la revalidation scientifique du **câblage structurel
v0 sont complètes**. La phase courante construit l'inventaire des familles de
paramètres, leur DAG de dépendances et les campagnes reproductibles de
calibration. Ne choisissez pas de valeurs physiologiques, gains, signes, seuils
ou comportements cibles hors d'une cible et d'une campagne versionnées.

Tout objet possédé par une validation `scientific_wiring_revalidation` ouverte
bloque la calibration de sa famille. Ni un smoke test vert, ni une cardinalité
correcte ne suffisent à lever ce blocage.

Le runtime incarné non calibré existe désormais sous trois modes :
`closed_loop_record.bat` calcule et enregistre, `physical_replay.bat` présente une
trajectoire physique indépendante de son producteur, et `closed_loop_live.bat`
exécute directement la même boucle dans le viewer. Ces chemins prouvent
l'intégration, jamais un comportement biologique. Leur contrat est défini par
l'ADR 0010 et `docs/embodied-runtime.md`.

## Sources de vérité à lire

Avant une modification structurelle ou de calibration, consulter au minimum :

1. `PROJECT_STATE.md` pour l'état courant et les fronts ouverts ;
2. `docs/wiring-methodology.md` pour la définition de « câblé » ;
3. `decisions/0002-exhaustive-terminal-coverage.md` pour les dispositions
   terminales et la cohérence sectorielle ;
4. les fiches pertinentes de `ledger/` et leurs validations ;
5. `docs/provenance-policy.md` lorsqu'une relation scientifique est ajoutée ou
   modifiée.
6. `docs/calibration-methodology.md`, l'ADR 0005 et `calibration/state.yaml` pour
   tout paramètre, cible, campagne ou protocole d'évaluation.
   Lire aussi l'ADR 0012 pour le DAG, le partage, le gel et la réouverture des
   familles de paramètres, l'ADR 0013 pour capacité/ensembles et l'ADR 0014 pour
   la fidélité de la dynamique neuronale et les hypothèses critiques.
7. `docs/rules-first-automation.md` lorsqu'un lot répète une décision sur de
   nombreux objets, construit un pipeline ou lance une campagne hors ligne.

Le registre reste canonique pour les statuts, propriétaires, claims, validations
et prochaines actions. Pour la topologie relationnelle générée, les sources
versionnées, règles et exceptions singulières sont canoniques ; les matrices et
manifestes générés sont des caches reproductibles. L'ADR 0011 fixe cette
stratification. Les skills indiquent comment travailler avec ces sources ; ils ne
remplacent pas leur contenu.

## Périmètre neuronal MaleCNS

La table d'annotations contient 211 577 corps, pas 211 577 neurones. Ne jamais
assimiler une ligne annotée à un neurone. Appliquer et contrôler les drapeaux de
l'ADR 0007 : les 166 700 neurones canoniques sont inclus dans le runtime, tandis
que glies et corps non résolus restent conservés, classifiés et auditables.

## Contrat de câblage

Chaque canal terminal d'entrée ou de sortie doit avoir exactement une disposition :
`exact`, `parameterized`, `basal`, `proxy`, `sink` ou `blocked`.

- Une boîte locale paramétrable peut valablement terminer un câblage même lorsque
  sa correspondance interne est inconnue.
- Une valeur injectée directement par un smoke test à la place d'une boîte reste
  `blocked`.
- Le smoke test peut fournir les entrées déclarées et des paramètres arbitraires,
  mais ne doit pas court-circuiter une transduction ou un routage absent.
- Une politique doit être cohérente à l'échelle d'une famille fonctionnelle. Des
  parties exactes et paramétrables peuvent coexister dans la même pile ; une autre
  nature de boîte exige une frontière biologique ou fonctionnelle justifiée.
- Une différence de cardinalité n'impose pas une correspondance point-à-point :
  utiliser une boîte de routage ou de transfert dont les degrés de liberté sont
  explicitement comptés.
- Séparer les paramètres de routage structurel (choix, permutation, matrice locale
  admissible) des paramètres de fonction de transfert (gain, seuil, dynamique),
  même si une même classe runtime les exécute.
- Un ensemble candidat n'est terminé scientifiquement que s'il est fini, local et
  borné par des contraintes anatomiques explicites. Une matrice capable de relier
  librement des secteurs sans rapport reste `blocked`, même si elle s'exécute.

## Traçabilité attendue

Toute décision substantielle doit permettre de retrouver :

- ce qui est couvert, simplifié, paramétrable, bloqué ou exclu ;
- le statut d'inventaire, routage/décomposition, implémentation et validation ;
- les cardinalités d'entrée, de sortie et les degrés de liberté ;
- la source utilisée, l'affirmation qu'elle soutient, la règle dérivée et les
  hypothèses restantes ;
- le test ou protocole associé, sa commande, ses critères et son dernier résultat ;
- ce qui reste à faire dans `next_action` et la raison de tout blocage ;
- les changements de progression dans `PROJECT_STATE.md` et le tableau de bord.

Une absence de source doit être déclarée. Ne jamais transformer une intuition en
fait pour améliorer un pourcentage.

## Hypothèses critiques et travail à risque

Une hypothèse qui choisit la classe du modèle, les unités natives, la sémantique
temporelle ou une abstraction dont l'échec invaliderait plusieurs lots est un
**gate**, pas un détail provisoire. Avant d'accumuler du travail dépendant,
enregistrer son rayon d'impact, les preuves favorables et contraires, le plus petit
test discriminant, un budget borné, les critères d'arrêt et ce qui restera
réutilisable en cas d'échec. Exécuter ce test tôt. Un smoke test, une forte vitesse,
une convergence numérique ou un rendu plausible ne valident pas l'hypothèse
scientifique.

Le modèle rate central v0 est désormais un comparateur d'ingénierie. Il ne simule
ni spikes, ni réfractarité, ni noyau synaptique événementiel, ni délais de
transmission. L'ADR 0014 bloque sa promotion et les calibrations dépendantes de ses
unités jusqu'à comparaison bornée avec un modèle événementiel LIF traçable. Cette
règle n'empêche pas les inventaires de preuves et travaux locaux indépendants du
choix de modèle.

## Automatisation proportionnée et sensible aux exceptions

Privilégier les petites procédures reproductibles lorsque la même règle doit être
appliquée plusieurs fois, qu'un invariant important doit être contrôlé ou que le
calcul peut être délégué hors quota. Une exécution doit comptabiliser chaque objet
du périmètre comme traité, explicitement exclu, bloqué ou exceptionnel. Elle doit
signaler les cas sans règle, les règles en conflit, les fallbacks, les dérives de
données et les écarts matériels avec l'exécution acceptée précédente.

Cette préférence n'est pas une obligation de construire un framework. Employer le
mécanisme le plus léger qui ferme la boucle, et arrêter d'automatiser lorsque les
cas restants sont rares, irréductiblement scientifiques ou moins coûteux à traiter
directement. Les décisions directes conservent la même traçabilité. Ne jamais
masquer une surprise par un défaut silencieux ; une exception acceptée garde une
raison et une prochaine action. La politique complète est définie par l'ADR 0009
et `docs/rules-first-automation.md`.

Une famille déclarée `independently_validated` doit pouvoir être reconstruite
dans une destination vide depuis les sources, règles et exceptions, sans lire son
précâblage, puis reproduire un hash sémantique canonique. Tester également les
contraintes négatives, les symétries/topographies pertinentes et, lorsqu'il est
non circulaire, un gold standard masqué. Le rapport expose la distribution des
tailles d'ensembles candidats et les degrés de liberté, pas seulement leur nombre.

## Contrat de calibration

- Distinguer `evidence_transfer`, `technical`, `local_interface`,
  `behavior_targeted` et `evaluation_only`.
- Une stabilité entraînée est un résultat technique, pas un comportement émergent.
- Toute action reconnaissable utilisée dans une loss, la sélection de modèle,
  l'early stopping ou le réglage manuel contamine la lignée pour ce comportement.
- Toute calibration comportementale exige l'accord explicite de l'utilisateur et
  un marquage très visible dans les registres, rapports et descendants.
- Les protocoles `evaluation_only` sont verrouillés avant fitting et ne servent
  jamais à choisir des paramètres. Une inspection qui entraîne un changement
  contamine cette version du protocole.
- Les valeurs biologiques reprises conservent source, unités, transformation,
  incertitude et limites d'applicabilité.
- Les campagnes forment un DAG explicite. Calibrer localement et geler les
  dépendances acceptées avant les objectifs globaux ; une calibration conjointe
  reste possible si la non-identifiabilité séparée est documentée.
- Minimiser la liberté par une hiérarchie de partage justifiée. Ne créer des
  paramètres individuels ni augmenter la capacité du modèle pour absorber un
  échec sans décision versionnée et preuve qu'un modèle plus simple est insuffisant.
- Distinguer le meilleur essai de l'ensemble scientifiquement admissible et
  conserver une incertitude proportionnée : intervalle, ensemble de solutions ou
  distribution selon le problème.
- Le gel d'une famille est explicite. Sa réouverture crée une nouvelle campagne,
  enregistre le diagnostic qui la motive et invalide ou revalide ses descendants.
- La calibration ne doit ni modifier silencieusement la topologie, ni ajouter un
  contrôleur comportemental externe autour de MaleCNS.
- Le choix ou la pondération à l'intérieur d'une enveloppe candidate acceptée est
  un paramètre de routage ; élargir cette enveloppe est une modification de
  câblage. Geler et enregistrer les hashes de topologie et d'exceptions avant une
  campagne.
- ADR 0006 autorise une unique exception diagnostique isolée :
  `diagnostic_viewer.bat` peut contourner MaleCNS pour explorer MuJoCo, mais son
  overlay, son namespace et ses sorties doivent rester `NOT MALECNS / NOT
  CALIBRATION`. Rien de ce chemin ne peut entrer dans une calibration, une
  évaluation scientifique ou un claim comportemental.
- Les sorties lourdes vont sous `runs/calibration/`; Git conserve les configs,
  lignées, hashes, résumés, échecs, décisions et prochaines actions.

## Capacité du modèle central et propagation d'ensemble

Le modèle central v0 à neuf efficacités de neurotransmetteur et trois paramètres
globaux est une hypothèse minimale exécutable, pas une dimension biologique
acceptée. Sa stabilité technique ou sa convergence numérique ne valident pas son
niveau de partage. Conserver ce risque dans `calibration/model-risks.yaml` et
suivre l'ADR 0013.

Ne pas exiger une solution centrale unique avant les calibrations locales. Un
ensemble admissible peut être propagé vers les sources basales, les interfaces
sensorielles/motrices et les campagnes hybrides. Déclarer si les paramètres aval
sont communs, robustes sur l'ensemble, conditionnés par membre/cluster ou ajustés
conjointement. Comptabiliser tous les membres ; toute réduction de coût par
échantillonnage doit être préenregistrée puis confirmée sur l'ensemble pertinent.

Après les contrôles centraux peu coûteux de pathologie et de portabilité
numérique, suspendre l'élimination CNS isolée sauf nouvelle preuve indépendante.
Utiliser les résidus locaux, par classe et par région pour décider si un modèle
central plus capacitaire est nécessaire. Toute augmentation de capacité crée une
nouvelle version et compare explicitement le modèle plus simple.

Les entrées basales et toute tonicité motrice sont des familles explicites. Une
stabilité corporelle neutre peut être entraînée comme cible `technical`, mais la
lignée ne peut ensuite présenter la station immobile comme spontanément émergente.
Ne jamais cacher une tonicité dans un gain ni prescrire pose, allure ou action sous
une étiquette de simple stabilité.

## Catalogue prospectif d'évaluations comportementales

`calibration/evaluation_candidates/emergent-behavior-catalog-v0.yaml` et
`docs/prospective-emergent-behavior-evaluations.md` recensent des observations
possibles après calibration. Ce catalogue n'est ni un protocole verrouillé, ni une
campagne, ni une autorisation de s'en servir pour choisir les paramètres.

Toute modification de paramètres, routage, capacité ou sélection manuelle visant
un comportement nommé contamine ce comportement pour la lignée concernée. Après
gel d'une lignée exécutable, transformer au plus un candidat à la fois en protocole
`evaluation_only` distinct, sourcé et immuable : scène, stimulus/sham, seeds,
métriques, seuils, analyse et hashes. Comparer idéalement MaleCNS à plusieurs
rewires avec paramètres gelés et à des rewires recalibrés par exactement la même
recette non comportementale ; aucun contrôle ne voit le comportement pendant sa
calibration.

## Initiative et cas non prévus

Ces règles définissent des invariants, pas une recette rigide. Adapter la méthode à
la forme réelle des données et préférer l'abstraction locale la plus simple qui
préserve l'intention scientifique. Un nouveau type de boîte ou une nouvelle
disposition peut être proposé s'il résout un cas réellement différent sans cacher
de capacité comportementale.

Prendre les décisions locales, réversibles et faiblement risquées qui permettent
d'avancer. Demander l'avis de l'utilisateur lorsqu'un choix modifierait la portée
scientifique, mélangerait des politiques incompatibles dans un secteur, ajouterait
une capacité de contrôle importante ou changerait irréversiblement l'interprétation
du projet. Documenter ensuite la décision sous forme d'ADR si elle est transversale.

## Validation et livraison

- Régénérer les manifestes lorsqu'une règle de câblage change.
- Ajouter des tests portant sur les invariants et les cardinalités, pas seulement
  sur des formulations textuelles.
- Lancer les tests pertinents ; lancer `run_wiring_smoke.bat` si le runtime ou le
  parcours global change ; régénérer `dashboard.bat` après un changement de statut.
- Les scripts destinés à être lancés par double-clic doivent afficher un avancement
  riche, un résumé final et attendre une touche avant fermeture.
- Ne pas versionner les données brutes, secrets, environnements, sorties `runs/`
  ou rapports générés.
- Préférer un commit local cohérent et validé par lot de travail. Ne jamais pousser
  sans demande explicite. Pour une simple analyse ou revue, ne pas modifier ni
  commiter sauf demande.

## Skills du dépôt

- Utiliser `flymatrix-wiring` pour construire ou modifier une boîte, un groupe, un
  fil, un manifeste ou un chemin runtime de câblage.
- Utiliser `flymatrix-wiring-audit` pour déterminer ce qui est réellement terminé,
  trouver les contournements et vérifier l'honnêteté des statuts et indicateurs.
- Utiliser `flymatrix-calibration` pour créer ou exécuter une cible, une campagne,
  un jeu de paramètres, un runner ou une dynamique temporelle de calibration.
- Utiliser `flymatrix-calibration-audit` pour auditer en lecture seule la
  reproductibilité, la provenance, les fuites comportementales et les claims.
