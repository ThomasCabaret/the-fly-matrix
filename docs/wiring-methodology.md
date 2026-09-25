# Méthodologie du câblage

Ce document décrit la méthode de travail durable de The Fly Matrix. Le registre
`ledger/` reste la source de vérité machine-readable ; ce texte explique comment
l'interpréter et le faire évoluer.

## Objectif de la phase actuelle

La phase de câblage construit un réseau paramétrable continu entre :

1. les observables du monde et du corps simulés ;
2. les afférences sensorielles MaleCNS ;
3. le graphe central MaleCNS ;
4. les sorties motrices MaleCNS ;
5. les actionneurs du corps simulé.

Une différence de cardinalité est représentée par une boîte locale explicite et
paramétrable. Une correspondance inconnue devient un ensemble candidat contraint
ou une boîte noire locale dont les ports et degrés de liberté sont déclarés. La
connaissance point-à-point n'est pas requise pour finir le câblage ; la couverture
exécutable de chaque canal l'est.

Cette phase ne choisit ni activité basale, ni gain, ni signe fonctionnel, ni seuil,
ni constante de temps, ni dynamique musculaire. Les valeurs pseudo-aléatoires des
smoke tests prouvent uniquement que les interfaces s'exécutent.

## Objets suivis

- Une **boîte** transforme localement un type de signal. Son statut sépare
  inventaire, implémentation, paramètres et validation.
- Un **groupe** est une population anatomique ou fonctionnelle reproductible.
  Son découpage et son routage sont suivis indépendamment.
- Un **fil** relie deux ports de boîtes et décrit sa cardinalité, ses contraintes
  candidates et ses degrés de liberté.
- Une **famille de paramètres** décrit ce qui sera réglé plus tard et comment les
  valeurs devront être partagées.
- Une **validation** possède un protocole, des critères d'acceptation et le dernier
  résultat connu.

## Classifier les corps avant de construire le graphe neuronal

Une ligne de la table d'annotations MaleCNS n'implique pas que le corps soit un
neurone. Avant tout graphe, runtime ou statistique dite « neuronale », le pipeline
doit appliquer et versionner une règle de population. Pour MaleCNS v1.0, l'ADR
0007 impose de conserver les 211 577 lignes et de leur ajouter au minimum :

- `population_scope` et `scope_reason` ;
- `is_canonical_neuron` ;
- `included_in_neural_runtime` ;
- un `runtime_node_index` distinct de l'indice d'inventaire.

La glie et les corps non résolus ne sont ni supprimés ni renommés en neurones. Ils
restent interrogeables dans l'inventaire et leurs arêtes restent comptées, mais ils
n'entrent pas silencieusement dans la propagation neuronale. Chaque route terminale
doit en outre être vérifiée contre le drapeau canonique. Un artefact ancien sans
classification doit faire échouer le runtime et demander une régénération.

L'accessibilité depuis une entrée et la capacité à atteindre une sortie sont des
étiquettes topologiques relatives aux frontières actuellement modélisées. Elles ne
constituent jamais, à elles seules, une preuve d'inutilité biologique.

Les identifiants sont stables. Un changement de connaissance modifie une fiche ;
il ne doit pas créer un nouvel identifiant pour faire disparaître l'historique.

## Disposition obligatoire de chaque terminal

Chaque canal d'entrée ou de sortie doit appartenir exactement à une disposition :

- `exact` : branchement fixé et audité ;
- `parameterized` : boîte locale reliant des ensembles connus par un routage ou
  une fonction de transfert encore libre ;
- `basal` : générateur nominal pour une modalité volontairement neutralisée ;
- `proxy` : observable de substitution explicitement assumée ;
- `sink` : sortie sans effecteur représenté ;
- `blocked` : absence actuelle de contrat exécutable.

`blocked` est le seul véritable fil tombant dans le vide. Une incertitude
scientifique n'est donc pas nécessairement un blocage : elle peut être contenue
dans une boîte `parameterized`. Inversement, compter une inconnue ou lui fournir
directement une valeur depuis le smoke test ne suffit pas à la considérer câblée.

Le chemin global doit partir uniquement des observables monde/corps, des sorties
de boîtes basales déclarées et des paramètres explicites. Le banc d'essai peut
alimenter ces ports, mais ne doit jamais injecter un vecteur d'activité à la place
d'une boîte sensorielle, de transduction ou de routage absente.

## Cohérence d'un secteur fonctionnel

Un secteur emploie une politique d'interface homogène. Des relations exactes et
paramétrables peuvent coexister à l'intérieur de la même pile de boîtes, mais une
sous-zone mal documentée ne change pas arbitrairement de nature fonctionnelle.
Ainsi, tous les canaux visuels doivent traverser la pile visuelle ; les canaux
connus peuvent y avoir une affectation fixée et les autres une matrice libre, mais
ils ne sont pas remplacés ponctuellement par du basal. Une exception exige une
frontière biologique ou fonctionnelle justifiée et enregistrée.

## Ordre normal d'un lot

1. Inventorier les sources et les destinations sans interprétation implicite.
2. Décomposer jusqu'à la granularité la plus fine justifiée par les données.
3. Attribuer exactement une disposition à chaque terminal, sans omission ni
   recouvrement.
4. Générer des manifestes dérivés reproductibles avec contrôles de cardinalité.
5. Rendre les boîtes et les fils exécutables avec paramètres injectés.
6. Tester les doublons, omissions, identités, terminaux et rejeux déterministes.
7. Mettre à jour le registre, les preuves, les limites et la prochaine action.
8. Régénérer le tableau de bord et créer un commit local isolé.

Un lot ne doit pas promouvoir une hypothèse en fait pour obtenir un meilleur
pourcentage. Une inconnue correctement localisée est un résultat utile.

## Définition de « 100 % câblé »

Le câblage atteint 100 % lorsque :

- toutes les populations terminales dans le périmètre sont inventoriées et
  décomposées ;
- chaque terminal possède une route vérifiée, un ensemble candidat explicite ou
  une politique `basal`, `proxy` ou `sink` explicite ;
- toutes les boîtes et tous les fils peuvent s'exécuter avec des paramètres
  injectés de l'extérieur ;
- aucun canal ne reste `blocked` et aucune valeur d'activité n'est injectée
  anonymement à la place d'une boîte manquante ;
- la politique de chaque secteur fonctionnel est cohérente, sauf frontière
  biologique explicitement justifiée ;
- le parcours monde/corps → CNS → sorties motrices → corps passe de façon
  déterministe ;
- aucune valeur de calibration n'est nécessaire pour construire la topologie ;
- les omissions, ambiguïtés et composants physiques absents sont comptés.

Cela ne signifie pas que la mouche se comporte correctement. À 100 %, elle peut
être exécutée structurellement avec des valeurs arbitraires ; la calibration peut
alors commencer comme phase distincte.

## Calcul de l'indicateur de câblage

Les scores exacts sont implémentés dans `src/the_fly_matrix/ledger.py`. Les
paramètres et les validations comportementales sont exclus du score de câblage.

| Objet | Formule |
|---|---|
| Boîte | 35 % inventaire + 65 % implémentation |
| Groupe | 55 % décomposition + 45 % routage |
| Fil | 10 % inventaire + 45 % routage + 45 % implémentation |

Les paliers de câblage sont :

- inventaire : `missing=0`, `partial=0,5`, `complete=1` ;
- implémentation : `not_started=0`, `stub=0,15`, `implemented=0,75`, `tested=1` ;
- décomposition : `unknown=0`, `proposed=0,25`, `fixed=0,75`, `verified=1` ;
- routage : `unknown=0`, `candidates_known=0,15`, `proposed=0,35`,
  `fixed=0,75`, `verified=1`.

Le score global est la moyenne de toutes les boîtes, groupes et fils. Un secteur
est la moyenne des objets qui lui appartiennent. Les objets ont donc le même poids,
pas la même quantité de travail : fermer un gros objet peut déplacer le score de
plusieurs points, tandis qu'un audit difficile peut ne changer aucun palier.

Le calcul actuel précède l'ADR 0002 : il ne vérifie pas encore automatiquement la
partition des canaux par disposition et ne bloque pas un secteur qui emploie une
injection directe de smoke test. Jusqu'à l'ajout de cet audit, le pourcentage est
un indicateur historique utile mais ne certifie pas à lui seul la couverture
exhaustive définie ci-dessus.

L'« indice structurel secondaire » inclut paramètres et validations ; il ne doit
pas être utilisé pour mesurer l'objectif courant.

## Règles de prudence

- Une annotation est une observation publiée, pas nécessairement une fonction.
- Une ROI dominante n'est pas une attribution fonctionnelle.
- Une arête candidate n'est ni une route choisie ni un paramètre calibré.
- Une valeur de smoke test n'est jamais persistée comme valeur scientifique.
- Une valeur de smoke test ne peut pas remplacer la sortie d'une boîte absente
  dans le parcours global.
- Une absence de capteur ou d'effecteur reste un terminal explicite.
- Les données dérivées doivent être régénérables ; les données brutes ne vont pas
  dans Git.

## Reprendre le travail

1. Lire `PROJECT_STATE.md`, puis `drosophila_virtual_fly_project_contract.md`.
2. Lancer `status.bat` et `dashboard.bat`.
3. Lire les `next_action` des secteurs les moins avancés.
4. Vérifier le dernier commit et l'état Git avant toute modification.
5. Après un lot, lancer les tests, `run_wiring_smoke.bat` si le runtime change,
   puis `dashboard.bat`.

La politique de justification des routes est détaillée dans
[`provenance-policy.md`](provenance-policy.md).
