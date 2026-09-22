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
ou un terminal non résolu ; elle ne doit jamais être masquée par une connexion
globale arbitraire.

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

Les identifiants sont stables. Un changement de connaissance modifie une fiche ;
il ne doit pas créer un nouvel identifiant pour faire disparaître l'historique.

## Ordre normal d'un lot

1. Inventorier les sources et les destinations sans interprétation implicite.
2. Décomposer jusqu'à la granularité la plus fine justifiée par les données.
3. Séparer les routes exactes, les candidats contraints et les inconnues.
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
  une politique terminale justifiée par l'absence d'un capteur/effecteur ;
- toutes les boîtes et tous les fils peuvent s'exécuter avec des paramètres
  injectés de l'extérieur ;
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

L'« indice structurel secondaire » inclut paramètres et validations ; il ne doit
pas être utilisé pour mesurer l'objectif courant.

## Règles de prudence

- Une annotation est une observation publiée, pas nécessairement une fonction.
- Une ROI dominante n'est pas une attribution fonctionnelle.
- Une arête candidate n'est ni une route choisie ni un paramètre calibré.
- Une valeur de smoke test n'est jamais persistée comme valeur scientifique.
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
