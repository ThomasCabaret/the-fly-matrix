---
name: flymatrix-wiring-audit
description: Auditer en lecture seule la complétude, la traçabilité et l'honnêteté du câblage de The Fly Matrix. À utiliser pour répondre à « est-ce fini ? », expliquer les pourcentages, repérer les fils bloqués ou injections directes, et comparer registre, runtime, tests et sources ; ne pas modifier le projet sauf demande explicite.
---

# Auditer le câblage The Fly Matrix

Produire un diagnostic fondé sur les artefacts du dépôt, pas sur le souvenir de la
conversation. Rester en lecture seule sauf si l'utilisateur demande aussi une
correction.

## Établir la référence

Lire `PROJECT_STATE.md`, `docs/wiring-methodology.md`,
`decisions/0002-exhaustive-terminal-coverage.md` et les entrées `ledger/`
concernées. Consulter les manifestes dérivés et `runs/wiring-smoke/latest.json`
lorsqu'ils existent. S'ils sont absents ou périmés, signaler cette limite ; les
régénérer seulement si cela est utile et reste dans le périmètre demandé.

## Contrôler la couverture réelle

Pour chaque secteur ou population auditée :

- comparer les ensembles attendus, générés et exécutés ;
- vérifier qu'un terminal appartient exactement une fois à `exact`,
  `parameterized`, `basal`, `proxy`, `sink` ou `blocked` ;
- détecter omissions, doublons, groupes qui se recouvrent et cardinalités
  contradictoires ;
- rechercher les entrées `unresolved_values`, vecteurs pseudo-aléatoires ou autres
  valeurs injectées après la frontière d'une boîte manquante ;
- distinguer un paramètre de test fourni à une boîte d'une activité qui contourne
  cette boîte ;
- vérifier la cohérence de la politique dans le secteur et justifier toute
  exception par une frontière biologique ou fonctionnelle ;
- sur les sorties, vérifier que chaque canal atteint un effecteur candidat ou un
  `sink` explicite.

Une route exacte vers un `bodyId` MaleCNS ne prouve pas que son origine physique
est câblée. De même, l'exécution déterministe d'un placeholder ne le transforme
pas en boîte valide.

## Contrôler la traçabilité

Vérifier l'accord entre code, manifeste, registre, documentation et tableau de
bord. Pour chaque décision importante, chercher :

- statut courant, niveau de confiance et prochaine action ;
- source précise et version ;
- affirmation réellement soutenue par la source ;
- règle dérivée, choix d'ingénierie et incertitude restante ;
- validation associée, commande, critères, dernier résultat et date/run ID ;
- effectifs couverts, simplifiés, paramétrables, bloqués et exclus.

Ne pas exiger une publication lorsqu'une décision est explicitement un choix
d'ingénierie. Exiger en revanche que ce choix soit nommé et que sa portée soit
bornée.

## Présenter le résultat

Séparer au minimum :

1. **couverture exécutable** — absence de fils `blocked` et de contournements ;
2. **résolution scientifique** — précision et solidité des correspondances ;
3. **calibration** — paramètres effectivement choisis ou encore libres ;
4. **validation** — tests exécutés, réussis, absents ou périmés.

Commencer par la conclusion (« fini », « fini avec dispositions paramétrables » ou
« non fini »), puis donner les nombres et les blocages concrets. Expliquer tout
écart avec le pourcentage affiché. Ne pas corriger le score ou promouvoir un statut
pendant un audit en lecture seule ; proposer la correction séparément.

Dans un cas non prévu, raisonner à partir de l'invariant « aucun terminal anonyme »
et de la finalité scientifique. Demander une décision utilisateur seulement si
plusieurs interprétations changent matériellement la portée ou la nature du modèle.

