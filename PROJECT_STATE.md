# État de reprise du projet

Mise à jour : 2026-09-22, après le commit structurel `0e4f336`.

Cette fiche doit être actualisée après tout commit qui modifie le score de câblage
ou les fronts structurels. En cas d'écart, le registre et le tableau de bord
recalculé font autorité.

## Objectif courant

Terminer le **câblage structurel** avant toute calibration. À 100 %, les signaux
doivent pouvoir parcourir l'ensemble monde/corps → MaleCNS → actionneurs avec des
paramètres injectés arbitrairement. Aucun comportement plausible n'est encore
attendu.

## État synthétique

- Câblage global : **80 %**.
- Graphe central MaleCNS : **100 % structurel**.
- Sortie motrice : **100 % structurel**.
- Proprioception : **86 %**.
- Entrées sensorielles non résolues : **88 %**.
- Clamps basaux : **87 %**.
- Vision : **74 %**.
- Mécanosensation : **62 %**.
- Corps physique : **94 %**.
- Monde physique : **100 %**.
- Évaluation/fermeture de boucle : **20 %**.

Le dernier lot a créé 1 439 arêtes candidates entre 204 observables articulaires
et 171 des 262 canaux proprioceptifs terminaux. Les 91 autres canaux attendent des
observables de contrainte ou vibration. Le smoke test traverse 17 884 entrées CNS,
26 028 386 arêtes centrales, 815 sorties motrices et 102 actionneurs. Les 29 tests
unitaires/intégration locaux passent.

## Fronts structurels restants

1. Relier les observables physiques aux groupes mécanorécepteurs sans inventer de
   surfaces ou d'organes absents.
2. Établir une rétinotopie indépendante entre les ommatidies FlyBody et les
   photorécepteurs MaleCNS.
3. Ajouter ou représenter explicitement contrainte et vibration pour les terminaux
   proprioceptifs encore ouverts.
4. Réduire les modalités sensorielles résiduelles lorsque les annotations le
   permettent, sans modifier leurs routes `bodyId` déjà exactes.
5. Fermer et tester la boucle physique complète et son interface d'évaluation,
   toujours sans contrôleur comportemental externe.

Les `next_action` du registre et le tableau de bord déterminent l'ordre concret du
prochain lot ; cette liste ne remplace pas ces sources de vérité.

## Reproduction locale

```text
setup.bat                 # si l'environnement n'existe pas
download_data.bat         # si les trois tables MaleCNS sont absentes
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
