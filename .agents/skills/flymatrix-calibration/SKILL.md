---
name: flymatrix-calibration
description: Construire ou modifier la calibration de The Fly Matrix — cibles, scopes, paramètres, campagnes, évaluations, runner et dynamique temporelle — sans changer silencieusement le câblage ni confondre comportement entraîné et émergent. À utiliser pour implémenter ou exécuter une calibration ; ne pas utiliser pour un audit seulement en lecture.
---

# Calibration de The Fly Matrix

## Avant toute action

Lire intégralement :

1. `PROJECT_STATE.md` ;
2. `docs/calibration-methodology.md` ;
3. `decisions/0005-calibration-evidence-and-claims.md` ;
4. `calibration/state.yaml` et les cibles actives ;
5. les fiches de câblage, validations et sources des boîtes concernées.

Le câblage reste canonique pour la topologie. La calibration modifie des paramètres
déclarés. Si le travail exige une nouvelle boîte, une cardinalité ou un chemin,
revenir au workflow `flymatrix-wiring` et rendre ce changement explicite.

## Classer avant de calibrer

Classer chaque cible comme `evidence_transfer`, `technical`, `local_interface`,
`behavior_targeted` ou `evaluation_only`. Déclarer séparément son exposition :
`allowed`, `diagnostic_only` ou `evaluation_only`.

- Les données biologiques reprises exigent source, unités, transformation,
  incertitude et limites d'applicabilité.
- La stabilité numérique, l'activité bornée/récupérable et la stabilité corporelle
  neutre sont des cibles techniques, pas des comportements émergents.
- Une fonction locale ne doit pas devenir un contrôleur d'action caché.
- Une cible comportementale reconnaissable exige l'autorisation explicite de
  l'utilisateur et un marquage très visible dans toute la lignée.
- Une évaluation tenue à l'écart ne participe jamais à la loss, à l'early stopping,
  au choix de modèle ou au tuning manuel.

Si le cas ne rentre honnêtement dans aucune classe, proposer une extension ou un
ADR. Demander à l'utilisateur si le choix changerait la portée scientifique, la
signification d'un résultat ou l'exposition d'un comportement.

## Construire un lot

1. Définir une cible versionnée, son scope exact, ses métriques, dépendances,
   critères, hypothèses, sources et `next_action`.
2. Inventorier les paramètres autorisés, gelés et inconnus. Compter les degrés de
   liberté et conserver les unités.
3. Créer une campagne reproductible : parents, bornes, méthode, seeds, budget,
   commande, commit, hashes et séparation train/validation/diagnostic/held-out.
4. Enregistrer chaque sortie dans un nouveau parameter set immuable. Ne pas
   écraser la référence active.
5. Conserver sous `runs/calibration/` les sorties lourdes et versionner seulement
   résumés, configurations, identifiants de contenu et résultats compacts.
6. Enregistrer les échecs, régressions et résultats négatifs ; ne pas sélectionner
   silencieusement un essai visuellement plaisant.
7. Vérifier les invariants structurels, les métriques locales, la boucle fermée si
   concernée et les non-régressions avant promotion.
8. Mettre à jour `calibration/state.yaml`, `PROJECT_STATE.md` et le tableau de bord
   quand le statut change.

## Discipline comportementale

Toute observation d'un résultat comportemental utilisée ensuite pour changer des
paramètres constitue une exposition. Propager cette contamination dans les
descendants. Un résultat ainsi entraîné peut être montré comme démonstration
d'ingénierie, jamais comme comportement non entraîné.

Ne jamais brancher un contrôleur comportemental externe autour de MaleCNS. Le
smoke test ou le runner fournit environnement, stimulus et paramètres déclarés ;
il ne choisit pas l'action de la mouche.

Pour une réponse tenue à l'écart, figer auparavant paramètres, protocole, scènes,
seeds et métriques. Après inspection conduisant à un changement, déclarer la
version contaminée et créer un nouveau protocole held-out.

## Validation et livraison

Tester les schémas, unités, cardinalités, seeds, déterminisme et restrictions de
scope. Ajouter des tests sur l'absence d'accès aux scénarios held-out depuis le
runner d'optimisation. Lancer les tests pertinents et le smoke test si le runtime
global change. Régénérer le dashboard après une évolution de statut.

Les scripts double-cliquables affichent une progression détaillée, un résumé final
et attendent une touche. Faire un commit local cohérent et validé ; ne jamais
pousser sans demande.
