# État de reprise du projet

Mise à jour : 2026-09-22, lot de colonnes visuelles R7/R8.

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
- Corps physique : **94 %**.
- Monde physique : **100 %**.
- Évaluation/fermeture de boucle : **20 %**.

Le dernier lot intègre le supplément officiel MaleCNS des colonnes optiques. Il
fixe 2 628 photorécepteurs R7/R8 dans 1 332 colonnes biologiques nommées, soit
43,1 % des 6 098 canaux visuels. La boîte de transduction impose désormais le même
œil, la compatibilité pale/jaune et un enregistrement injectif colonne→ommatidie.
Cet enregistrement et les 2 628 coefficients restent injectés de l'extérieur et
ne sont pas calibrés. Les 3 470 autres canaux visuels restent explicitement
ouverts. La vision passe de 74 à 86 % et le câblage global de 83 à 85 %.
Le smoke test traverse 17 884 entrées CNS, 26 028 386 arêtes centrales, 815 sorties
motrices et 102 actionneurs. Les 32 tests unitaires/intégration locaux passent.

## Fronts structurels restants

1. Fixer l'enregistrement spatial des 1 332 colonnes publiées sur les ommatidies
   FlyBody, sans utiliser l'ordre des lignes comme géométrie.
2. Trouver une source de colonne indépendante pour les 3 377 R1-R6 et traiter
   séparément les 93 autres canaux visuels encore ouverts.
3. Ajouter ou représenter explicitement contrainte et vibration pour les terminaux
   proprioceptifs encore ouverts.
4. Réduire les modalités sensorielles résiduelles lorsque les annotations le
   permettent, sans modifier leurs routes `bodyId` déjà exactes.
5. Fermer et tester la boucle physique complète et son interface d'évaluation,
   toujours sans contrôleur comportemental externe.
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
