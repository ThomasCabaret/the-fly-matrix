# Raw data

Les données brutes sont immuables et ne sont jamais versionnées dans Git. Le
pipeline canonique, les volumes, les jetons et la distinction entre données
obligatoires et données de campagne optionnelles sont documentés dans
[`docs/reproduction-pipeline.md`](../../docs/reproduction-pipeline.md).

MaleCNS v1.0 doit être placé dans :

```text
data/raw/malecns/v1.0/
```

Utiliser `download_data.bat` pour télécharger, reprendre ou contrôler les quatre
fichiers minimaux : trois tables MaleCNS et le supplément de colonnes optiques.
Les sources locales FeCO et moteur utilisent `prepare_local_source_data.bat` et
restent optionnelles tant que leur campagne n'est pas rejouée. Les fichiers
dérivés doivent aller dans `data/derived/`, jamais à côté des sources.

