# ADR 0002 — Couverture terminale exhaustive par des boîtes explicites

## Statut

Accepté.

## Contexte

Une correspondance biologique inconnue ne doit pas imposer une résolution
point-à-point avant la calibration. Elle ne doit pas non plus devenir une valeur
d'activité injectée directement par le banc d'essai dans une entrée MaleCNS. Le
câblage vise une couverture exécutable exhaustive, pas une connaissance anatomique
parfaite.

## Décision

Chaque canal terminal d'entrée et de sortie doit appartenir exactement à une des
dispositions suivantes :

- `exact` : relation fixée par une donnée ou une règle déterministe auditée ;
- `parameterized` : ensemble source et ensemble cible connus, reliés par une boîte
  locale dont le routage ou la fonction de transfert reste paramétrable ;
- `basal` : modalité volontairement neutralisée par une boîte de signal nominal ;
- `proxy` : observable physique de substitution explicitement déclarée ;
- `sink` : sortie sans effecteur représenté, consommée sans effet physique ;
- `blocked` : canal encore dépourvu de contrat exécutable.

Seul `blocked` constitue un fil qui tombe dans le vide. Un secteur n'est câblé à
100 % que s'il ne contient plus aucun canal `blocked` et si son chemin global
n'injecte aucune activité anonyme directement dans un port interne ou MaleCNS.

Le smoke test peut choisir des paramètres et alimenter les entrées déclarées des
boîtes. Il ne peut pas remplacer une boîte absente en fournissant directement son
vecteur de sortie. Une valeur pseudo-aléatoire est donc acceptable à l'entrée
d'une boîte basale ou comme paramètre de test, mais pas comme substitut d'un
capteur, d'une transduction ou d'un routage manquant.

## Cohérence sectorielle

Une politique d'interface s'applique à une famille fonctionnelle cohérente. Des
sous-relations exactes et paramétrables peuvent coexister dans une même boîte, mais
elles doivent partager le même contrat sensoriel ou moteur. Par exemple, toute la
vision doit traverser la pile vision physique → transduction → routage. Les
photorécepteurs dont la colonne est publiée peuvent y avoir des paramètres fixés,
et les autres une sous-matrice libre ; ces derniers ne doivent pas être remplacés
ponctuellement par un clamp basal simplement parce que leur correspondance est
moins bien documentée.

Une politique différente dans un même secteur exige une frontière biologique ou
fonctionnelle explicite et une justification dans le registre.

## Conséquences

- La résolution anatomique et la couverture exécutable sont deux indicateurs
  distincts.
- Une grosse boîte noire locale est acceptable lorsque ses ports, sa localité, ses
  degrés de liberté et son futur protocole de calibration sont explicites.
- Les API `unresolved_values` du chemin global sont une dette de câblage, même si
  elles rendent un smoke test exécutable.
- Les clamps olfactif, gustatif et thermo-hygrométrique sont des terminaisons
  complètes de type `basal`, pas des secteurs inachevés.
- Au moment de l'adoption, 3 470 canaux visuels contournaient encore une boîte
  déclarée. Cette dette historique est maintenant fermée; l'état courant et ses
  dispositions restent décrits dans le registre plutôt que figés dans cet ADR.
