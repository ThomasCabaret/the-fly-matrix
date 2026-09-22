# ADR 0001 — Terminer le câblage avant la calibration

## Statut

Accepté.

## Contexte

Les interfaces physiques, les populations MaleCNS et les actionneurs n'ont pas
toujours la même cardinalité. Leurs relations exigent des boîtes de routage ou de
transfert paramétrables. Régler ces paramètres pendant que la topologie reste
incomplète rendrait les échecs difficiles à localiser et risquerait de faire
compenser une mauvaise interface par la calibration.

## Décision

Le projet termine d'abord un réseau structurel exécutable : groupes les plus fins
justifiables, routes exactes ou candidates explicites, terminaux inconnus comptés,
et passage déterministe de bout en bout avec valeurs arbitraires injectées.

La calibration des activités basales, gains, signes, dynamiques neuronales,
fonctions de transfert et paramètres mécaniques constitue une phase ultérieure.

## Conséquences

- Le score principal courant exclut entièrement l'état des paramètres.
- Les smoke tests peuvent employer des valeurs arbitraires, mais ne les persistent
  jamais comme paramètres scientifiques.
- Un câblage à 100 % ne revendique aucun comportement biologique correct.
- Les problèmes de stabilité et les validations comportementales ne bloquent pas
  la fin du câblage, mais restent visibles dans le registre.
- Une boîte partiellement reliée doit exposer ses entrées manquantes au lieu de les
  remplacer par une hypothèse silencieuse.
