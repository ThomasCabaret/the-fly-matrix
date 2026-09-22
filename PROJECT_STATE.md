# État de reprise du projet

Mise à jour : 2026-09-22, lot de fermeture physique FlyBody/MuJoCo.

Cette fiche doit être actualisée après tout commit qui modifie le score de câblage
ou les fronts structurels. En cas d'écart, le registre et le tableau de bord
recalculé font autorité.

## Objectif courant

Terminer le **câblage structurel** avant toute calibration. À 100 %, les signaux
doivent pouvoir parcourir l'ensemble monde/corps → MaleCNS → actionneurs avec des
paramètres injectés arbitrairement. Aucun comportement plausible n'est encore
attendu.

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

1. Fixer l'enregistrement spatial des 1 332 colonnes publiées sur les ommatidies
   FlyBody, sans utiliser l'ordre des lignes comme géométrie.
2. Trouver une source de colonne indépendante pour les 3 377 R1-R6 et traiter
   séparément les 93 autres canaux visuels encore ouverts.
3. Ajouter ou représenter explicitement contrainte et vibration pour les terminaux
   proprioceptifs encore ouverts.
4. Réduire les modalités sensorielles résiduelles lorsque les annotations le
   permettent, sans modifier leurs routes `bodyId` déjà exactes.
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
