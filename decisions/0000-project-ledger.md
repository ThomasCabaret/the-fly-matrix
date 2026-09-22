# ADR 0000 — Le registre est la source de vérité

## Statut

Accepté.

## Décision

Les boîtes, fils, familles de paramètres et validations sont décrits par des fiches
machine-readable dans `ledger/`. Les checklists et graphes d'avancement seront
générés depuis ces fiches plutôt que maintenus séparément.

Un statut scientifique, un statut d'implémentation et un niveau de confiance ne
doivent jamais être fusionnés en un pourcentage unique.

L'indicateur principal de la phase courante est le câblage exécutable défini dans
`docs/wiring-methodology.md`. L'indice structurel historique reste secondaire et
ne remplace jamais les axes détaillés du registre.
