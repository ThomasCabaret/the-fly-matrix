# Ledger

Le registre décrit ce qui existe, ce qui reste inconnu, ce qui a été tenté et ce
qui a été validé.

Les `groups` représentent les populations anatomiques ou fonctionnelles qui sont
découpées puis routées. Ils sont distincts des `boxes` (calculs/adaptateurs) et des
`wires` (liaisons entre boîtes), afin qu'un découpage puisse être terminé alors que
son affectation reste inconnue.

## Axes indépendants

- `inventory_status`: `missing`, `partial`, `complete`.
- `routing_status`: `unknown`, `candidates_known`, `proposed`, `fixed`, `verified`.
- `decomposition_status`: `unknown`, `proposed`, `fixed`, `verified`.
- `implementation_status`: `not_started`, `stub`, `implemented`, `tested`.
- `parameter_status`: `unknown`, `assumed`, `borrowed`, `measured`, `fitted`, `frozen`.
- `validation_status`: `not_run`, `smoke`, `local_pass`, `integration_pass`, `held_out_pass`, `failed`.
- `confidence`: `low`, `medium`, `high`.

Les fichiers `_template.yaml` ne sont pas des éléments du registre. Une fiche réelle
doit utiliser un identifiant stable, déclarer son parent éventuel et référencer ses
preuves, paramètres, validations et prochaine action.

La définition de « câblage terminé », le calcul exact de l'indicateur et la
procédure de reprise sont documentés dans
[`docs/wiring-methodology.md`](../docs/wiring-methodology.md). La politique de
justification des routes et les catégories de preuves sont dans
[`docs/provenance-policy.md`](../docs/provenance-policy.md).

Pour toute fiche nouvelle ou substantiellement modifiée, remplir le bloc
`provenance` du modèle correspondant. Les fiches historiques sont migrées lorsqu'on
les touche : une source absente doit rester absente plutôt que d'être reconstruite
rétrospectivement sans preuve.
