# État de reprise du projet

Mise à jour : 2026-09-22, lot de transduction mécanoréceptrice.

Cette fiche doit être actualisée après tout commit qui modifie le score de câblage
ou les fronts structurels. En cas d'écart, le registre et le tableau de bord
recalculé font autorité.

## Objectif courant

Terminer le **câblage structurel** avant toute calibration. À 100 %, les signaux
doivent pouvoir parcourir l'ensemble monde/corps → MaleCNS → actionneurs avec des
paramètres injectés arbitrairement. Aucun comportement plausible n'est encore
attendu.

## État synthétique

- Câblage global : **83 %**.
- Graphe central MaleCNS : **100 % structurel**.
- Sortie motrice : **100 % structurel**.
- Proprioception : **86 %**.
- Entrées sensorielles non résolues : **88 %**.
- Clamps basaux : **87 %**.
- Vision : **74 %**.
- Mécanosensation : **82 %**.
- Corps physique : **94 %**.
- Monde physique : **100 %**.
- Évaluation/fermeture de boucle : **20 %**.

Le dernier lot étend la matrice mécanoréceptrice à 2 108 arêtes candidates. Les
charges des six pattes et les positions/vitesses de 19 articulations d'antenne,
d'aile, d'haltère et de pièces buccales alimentent 303 canaux. Les 16 canaux PDMN
du notum consomment maintenant la force nette du thorax central et les 4 canaux ON
péri-optiques celle de la tête. La couverture atteint donc 323/323 canaux et les
4 291 neurones. Le registre suit séparément les 1 306 arêtes de contact et les 802
arêtes articulaires. La résolution tête/thorax reste volontairement centrale et
grossière, car FlyBody ne fournit pas ici de localisation gauche/droite plus fine.
L'indice mécanorécepteur passe de 81 à 82 % ; les gains restent seulement candidats.
Le smoke test traverse 17 884 entrées CNS, 26 028 386 arêtes centrales, 815 sorties
motrices et 102 actionneurs. Les 31 tests unitaires/intégration locaux passent.

## Fronts structurels restants

1. Établir une rétinotopie indépendante entre les ommatidies FlyBody et les
   photorécepteurs MaleCNS.
2. Ajouter ou représenter explicitement contrainte et vibration pour les terminaux
   proprioceptifs encore ouverts.
3. Réduire les modalités sensorielles résiduelles lorsque les annotations le
   permettent, sans modifier leurs routes `bodyId` déjà exactes.
4. Fermer et tester la boucle physique complète et son interface d'évaluation,
   toujours sans contrôleur comportemental externe.
5. N'affiner les candidats tête/thorax que si une observable corporelle plus
   localisée devient disponible, sans inventer de latéralité.

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
