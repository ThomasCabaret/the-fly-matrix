# Runs

Chaque expérience crée un sous-répertoire immuable contenant sa configuration
résolue, les empreintes des données, les graines, métriques, journaux et verdicts.
Les contenus de `runs/` ne sont pas versionnés par défaut.

Un clone ne doit pas recréer tout l'historique pour devenir utilisable. Le
runbook [`docs/reproduction-pipeline.md`](../docs/reproduction-pipeline.md)
sépare le chemin structurel obligatoire, les campagnes actuellement pertinentes
et les replays historiques optionnels. Toute conclusion durable issue d'un run
doit aussi disposer d'un résumé compact versionné sous `calibration/` ou dans le
registre approprié.

