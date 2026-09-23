---
name: flymatrix-calibration-audit
description: Auditer en lecture seule l'état, la reproductibilité, la provenance, les fuites comportementales et l'honnêteté des claims de calibration de The Fly Matrix. À utiliser pour répondre à « qu'est-ce qui est calibré ? », vérifier une campagne ou distinguer stabilité entraînée et réponse tenue à l'écart ; ne pas modifier le projet sauf demande explicite.
---

# Audit de calibration de The Fly Matrix

## Sources à confronter

Lire `PROJECT_STATE.md`, `docs/calibration-methodology.md`, ADR 0005,
`calibration/state.yaml`, puis les cibles, scopes, campagnes, parameter sets,
évaluations, tests et provenance concernés. Les résumés et dashboards ne suffisent
pas : les comparer aux commandes, hashes, artifacts et résultats réels.

Rester en lecture seule. Ne pas lancer une campagne coûteuse, modifier un statut ou
promouvoir un parameter set pendant un audit sans demande explicite.

## Contrôles

Pour chaque claim ou parameter set :

1. reconstruire toute la lignée et l'origine de chaque famille de paramètres ;
2. vérifier scope, unités, bornes, valeurs gelées, seeds, commande, commit et
   versions d'entrée ;
3. chercher tout changement de topologie caché ou contrôleur externe ;
4. identifier les comportements exposés dans loss, validation, early stopping,
   sélection manuelle ou inspection itérative ;
5. vérifier que les scénarios `evaluation_only` ne sont pas accessibles au runner
   d'optimisation et ont été verrouillés avant le gel des paramètres ;
6. comparer les critères déclarés aux métriques réellement calculées et conserver
   les échecs ou essais abandonnés dans le dénominateur pertinent ;
7. distinguer validation locale, stabilité technique en boucle fermée et preuve
   held-out d'une réponse spécifique ;
8. vérifier sources, transformations, hypothèses et applicabilité des valeurs
   biologiques empruntées ;
9. confirmer que `next_action`, blocages et état du dashboard reflètent les
   registres canoniques.

## Verdicts

Ne pas produire un pourcentage unique sans dénominateur. Rapporter séparément :

- couverture des familles de paramètres ;
- provenance et reproductibilité ;
- validation technique ;
- validation locale des interfaces ;
- contamination comportementale ;
- résultats réellement held-out ;
- blockers et prochaine action.

Qualifier les affirmations : `supported`, `partially_supported`, `unsupported`,
`contaminated`, `not_run` ou `blocked`. Une stabilité optimisée est un succès
technique mais pas un comportement émergent. Une réaction visible sans sham,
spécificité et répétabilité n'établit pas une réponse causale.

Signaler les divergences avec fichiers et lignes, preuves observées, impact et
correction minimale. Une absence de source ou de trace est un résultat d'audit,
pas une invitation à inventer une justification.
