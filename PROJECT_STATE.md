# État de reprise du projet

Mise à jour : 2026-09-22, contrat de couverture terminale exhaustive.

Cette fiche doit être actualisée après tout commit qui modifie le score de câblage
ou les fronts structurels. En cas d'écart, le registre et le tableau de bord
recalculé font autorité.

## Objectif courant

Terminer le **câblage structurel** avant toute calibration. À 100 %, les signaux
doivent pouvoir parcourir l'ensemble monde/corps → MaleCNS → actionneurs avec des
paramètres injectés arbitrairement. Aucun comportement plausible n'est encore
attendu.

La définition normative est désormais celle de
[`ADR 0002`](decisions/0002-exhaustive-terminal-coverage.md) : chaque canal doit
avoir une disposition `exact`, `parameterized`, `basal`, `proxy`, `sink` ou
`blocked`. Une boîte noire locale paramétrable termine valablement un câblage même
si sa correspondance interne est inconnue. En revanche, une activité fournie
directement par le smoke test à la place d'une boîte reste `blocked`.
Le calcul actuel des 85 % n'applique pas encore automatiquement cette nouvelle
condition ; le prochain audit machine-readable pourra donc reclasser le score
sans que le réseau sous-jacent ait régressé.

Avant le prochain grand lot de câblage, la priorité est désormais de construire
une première carte interactive exhaustive du routage. Elle doit représenter les
terminaux connectés comme non connectés, préserver la granularité réelle des
boîtes et adapter seulement le détail graphique au niveau de zoom. L'architecture,
les invariants visuels et le contrat de traçabilité sont actés en anglais dans
[`ADR 0003`](decisions/0003-interactive-wiring-map.md).

## État synthétique

- Câblage global : **85 %**.
- Graphe central MaleCNS : **100 % structurel**.
- Sortie motrice : **100 % structurel**.
- Proprioception : **86 %**.
- Entrées sensorielles non résolues : **88 %**.
- Clamps basaux : **87 %**.
- Vision : **86 %**.
- Mécanosensation : **82 %**.
- Corps physique : **100 %**.
- Monde physique : **100 %**.
- Évaluation/fermeture de boucle : **20 %**.

Le dernier lot ferme l'exécution physique après la sortie motrice. Le runtime
construit un FlyBody articulé dans MuJoCo, vérifie l'ordre des 102 actionneurs,
applique réellement les commandes pendant 20 pas, puis relit les 102 positions et
vitesses par l'interface proprioceptive. Le rejeu depuis le même état est identique
bit à bit et diffère du témoin passif. Une enveloppe numérique propre au smoke test
protège MuJoCo des paramètres arbitraires; elle n'est pas une calibration. Le
secteur corps physique passe de 94 à 100 %. Le score global reste arrondi à 85 %,
mais son composant de routage des fils passe de 69 à 70 %.

Le smoke test traverse toujours 17 884 entrées CNS, 26 028 386 arêtes centrales,
815 sorties motrices et 102 actionneurs avant le pas physique. Les 33 tests
unitaires/intégration locaux passent.

## Fronts structurels restants

1. Auditer toutes les injections `unresolved_values` du parcours global et leur
   attribuer une disposition terminale machine-readable.
2. Faire traverser aux 6 098 canaux la même pile visuelle : affectations R7/R8
   fixes lorsqu'elles sont publiées, sous-routage paramétrable pour les autres,
   sans clamp basal localisé dans l'œil.
3. Encapsuler contrainte et vibration proprioceptives manquantes dans une boîte
   `parameterized` ou `proxy` explicite plutôt que dans des valeurs de test.
4. Donner aux 1 883 afférences sensorielles résiduelles une boîte source générique
   locale, quitte à conserver une fonction de transfert très large à calibrer.
5. Définir plus tard l'interface d'évaluation tenue à l'écart; la boucle physique
   commande→MuJoCo→état articulaire est désormais fermée et déterministe.
6. N'affiner les candidats tête/thorax que si une observable corporelle plus
   localisée devient disponible, sans inventer de latéralité.

Les `next_action` du registre et le tableau de bord déterminent l'ordre concret du
prochain lot ; cette liste ne remplace pas ces sources de vérité.

## Reproduction locale

```text
setup.bat                 # si l'environnement n'existe pas
download_data.bat         # si les tables MaleCNS ou le supplément optique sont absents
status.bat
run_analysis.bat          # inventaires et manifestes ; neuPrint si jeton présent
run_wiring_smoke.bat      # reconstruction et parcours structurel complet
dashboard.bat             # état HTML/DOT recalculé
```

Les données brutes, les artefacts `data/derived/`, les exécutions `runs/` et les
rapports générés sont ignorés par Git. Un clone contient la méthode et le registre,
mais doit régénérer ces artefacts. Le rapport principal est alors
`reports/generated/project-status.html`.

La méthode complète est dans [`docs/wiring-methodology.md`](docs/wiring-methodology.md)
et la politique de sources dans
[`docs/provenance-policy.md`](docs/provenance-policy.md).
