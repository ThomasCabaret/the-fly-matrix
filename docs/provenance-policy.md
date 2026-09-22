# Politique de provenance

Chaque branchement doit pouvoir répondre à quatre questions : **quelle donnée ou
publication ? quelle affirmation en est tirée ? quelle règle le code applique ?
qu'est-ce qui reste incertain ?**

## Nature d'une affirmation

Une règle de câblage appartient à une ou plusieurs catégories :

- `dataset_observation` : valeur directement lue dans un dataset versionné ;
- `literature_supported` : relation soutenue par une publication ou un atlas ;
- `derived_rule` : transformation déterministe de faits précédents ;
- `engineering_choice` : choix local nécessaire mais non mesuré biologiquement ;
- `smoke_only` : valeur ou comportement utilisé uniquement pour tester l'exécution ;
- `unresolved` : information absente ou contradictoire, conservée comme telle.

Les catégories ne sont pas des niveaux de qualité. Elles empêchent surtout de
présenter une déduction ou un choix d'ingénierie comme une mesure biologique.

## Ce qu'une fiche doit conserver

Pour toute boîte, tout groupe ou tout fil nouveau ou substantiellement modifié :

- `evidence` : artefacts, tables, code ou résultats locaux qui permettent l'audit ;
- `provenance.claim_kinds` : catégories ci-dessus ;
- `provenance.source_references` : identifiant de dataset, URL stable ou DOI ;
- `provenance.used_claims` : phrase courte indiquant exactement ce que la source
  justifie ;
- `provenance.assumptions` : choix non directement imposés par les sources ;
- `confidence` et `known_limitations` lorsque la fiche les accepte ;
- une validation avec critères chiffrés pour les cardinalités importantes.

Les anciennes fiches ne possèdent pas toutes encore ce bloc. Elles doivent être
mises à niveau lorsqu'elles sont touchées, sans inventer rétrospectivement une
source plus précise que celle réellement utilisée.

## Où vit la preuve

- `ledger/datasets.yaml` fixe l'identité et la version des données.
- `ledger/boxes/`, `groups/` et `wires/` décrivent la décision courante.
- `ledger/validations/` décrit comment la décision est contrôlée.
- `decisions/` conserve les décisions transversales et leurs alternatives.
- Les générateurs sous `src/the_fly_matrix/` matérialisent les règles.
- `data/derived/` et `runs/` contiennent les résultats reproductibles, mais sont
  ignorés par Git ; leur absence dans un clone ne doit pas effacer la justification
  suivie dans le registre.
- Git conserve le lot dans lequel la décision a été introduite ou révisée.

Une URL générale dans le contrat scientifique ne suffit pas toujours. Pour une
règle locale importante, la fiche ou sa validation doit citer la source précise et
nommer l'affirmation utilisée.

## Exemples d'interprétation

- `entryNerve=MetaLN` et `rootSide=L` lus dans MaleCNS sont des
  `dataset_observation`.
- Restreindre ces afférences à la patte postérieure gauche est une `derived_rule`
  qui doit citer la convention anatomique employée.
- Autoriser plusieurs articulations locales faute d'identité point-à-point est un
  `engineering_choice` et doit rester une matrice candidate.
- Injecter des nombres pseudo-aléatoires reproductibles pour traverser cette
  matrice est `smoke_only`.
- L'absence de mesure de contrainte dans FlyBody est `unresolved`, pas une raison
  pour utiliser silencieusement l'angle articulaire comme substitut.

## Checklist avant commit

- La source et sa version sont-elles identifiables ?
- L'affirmation réellement utilisée est-elle écrite ?
- Les règles dérivées et choix d'ingénierie sont-ils distingués ?
- Les candidats, routes fixes et inconnues sont-ils séparés ?
- Les exclusions et terminaux sans représentation sont-ils comptés ?
- Les valeurs de test sont-elles absentes des paramètres scientifiques ?
- Le registre, les tests et la prochaine action concordent-ils ?

Une traçabilité incomplète doit être déclarée comme dette documentaire dans la
prochaine action ; elle ne doit pas être masquée par un niveau de confiance élevé.
