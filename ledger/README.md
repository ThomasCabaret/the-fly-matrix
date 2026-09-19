# Ledger

Le registre décrit ce qui existe, ce qui reste inconnu, ce qui a été tenté et ce
qui a été validé.

## Axes indépendants

- `inventory_status`: `missing`, `partial`, `complete`.
- `routing_status`: `unknown`, `candidates_known`, `proposed`, `fixed`, `verified`.
- `implementation_status`: `not_started`, `stub`, `implemented`, `tested`.
- `parameter_status`: `unknown`, `assumed`, `borrowed`, `measured`, `fitted`, `frozen`.
- `validation_status`: `not_run`, `smoke`, `local_pass`, `integration_pass`, `held_out_pass`, `failed`.
- `confidence`: `low`, `medium`, `high`.

Les fichiers `_template.yaml` ne sont pas des éléments du registre. Une fiche réelle
doit utiliser un identifiant stable, déclarer son parent éventuel et référencer ses
preuves, paramètres, validations et prochaine action.

