---
name: flymatrix-wiring
description: Construire ou modifier le câblage structurel de The Fly Matrix — boîtes, groupes, fils, dispositions terminales, manifestes et runtime — sans effectuer la calibration. À utiliser pour tout lot reliant monde/corps, MaleCNS et actionneurs ; ne pas utiliser pour une simple revue en lecture seule.
---

# Réaliser un lot de câblage The Fly Matrix

Produire un lot local, exécutable, traçable et scientifiquement honnête. Adapter
l'ordre des opérations au cas rencontré : les exigences ci-dessous portent sur le
résultat, pas sur une séquence rigide.

## Charger le contexte utile

Lire `PROJECT_STATE.md`, `docs/wiring-methodology.md` et
`decisions/0002-exhaustive-terminal-coverage.md`. Lire ensuite uniquement les
fiches `ledger/`, validations, générateurs et sources qui concernent le secteur du
lot. Consulter `drosophila_virtual_fly_project_contract.md` quand le choix touche à
la capacité d'un adaptateur ou à la frontière connectome/hors-connectome.

Préserver les modifications existantes de l'utilisateur et vérifier l'état Git
avant d'éditer.

## Concevoir la couverture

- Énumérer les ensembles d'entrée et de sortie et contrôler leur cardinalité.
- Décomposer au niveau le plus fin justifié par les données, sans inventer une
  identité point-à-point.
- Attribuer chaque terminal exactement une fois à `exact`, `parameterized`,
  `basal`, `proxy`, `sink` ou `blocked`.
- Lorsqu'on connaît les deux ensembles mais pas la bijection ni la fonction,
  créer une boîte locale paramétrable avec degrés de liberté explicites.
- Préserver une pile fonctionnelle homogène dans le secteur. Des sous-relations
  fixes et libres peuvent coexister dans cette pile ; ne pas changer de modalité
  pour combler localement une lacune documentaire.
- Garder les adaptateurs locaux et de capacité minimale. Ils ne doivent connaître
  ni objectif comportemental global, ni phase de marche, ni état global de tâche.

Si le cas ne rentre pas proprement dans la taxonomie, proposer l'abstraction la
plus petite et réversible. Continuer lorsque le choix est local et conserve le
contrat scientifique ; demander une décision utilisateur lorsqu'il change la
portée, la nature fonctionnelle du secteur ou la capacité de contrôle du modèle.

## Implémenter sans calibrer

- Générer les manifestes dérivés plutôt que maintenir des listes manuelles.
- Séparer les routes fixes, les arêtes candidates, les paramètres continus, les
  choix discrets, les proxies et les sinks.
- Autoriser le smoke test à fournir des observables déclarées et des paramètres
  arbitraires reproductibles. Interdire qu'il injecte directement le résultat
  qu'une boîte manquante aurait dû produire.
- Ne jamais persister une valeur de smoke test comme paramètre scientifique.
- Conserver les données volumineuses et sorties générées hors Git.

## Rendre la décision auditée

Mettre à jour les fiches concernées pour conserver :

- statuts et confiance ;
- dispositions et effectifs couverts/bloqués ;
- cardinalités et degrés de liberté ;
- `evidence`, références, affirmation utilisée, règle dérivée et hypothèses ;
- identifiants de validation, commande, critères, résultat et `latest_run_id` ;
- `next_action`, limites connues et `blocked_by`.

Créer ou mettre à jour une validation chiffrée quand l'exhaustivité ou la
non-duplication est importante. Ajouter un ADR seulement pour une décision
transversale durable, pas pour chaque détail local.

## Vérifier et livrer

Exécuter les tests proportionnés au changement. Si le runtime ou le parcours
global change, exécuter le smoke test complet. Valider le registre et régénérer le
tableau de bord après tout changement de statut ou progression. Examiner le diff,
vérifier l'absence de secrets et de gros artefacts, puis mettre à jour
`PROJECT_STATE.md` avec le résultat réel et les fronts restants.

Dans le compte rendu, distinguer explicitement : couverture exécutable, résolution
scientifique, calibration et validation. Ne pas annoncer un secteur « fini » tant
qu'un canal `blocked` ou une injection anonyme subsiste.

