# Instructions de travail — The Fly Matrix

## Finalité du projet

Construire une simulation incarnée dans laquelle MaleCNS reste le substrat de
calcul principal. Les interfaces entre monde, corps, connectome et actionneurs
doivent être locales, explicites, paramétrables et auditables. Un résultat visible
mais produit par un contrôleur comportemental externe n'est pas un succès du
projet.

La couverture terminale du **câblage structurel v0 est complète**. La phase
courante ouvre l'infrastructure de calibration, sans considérer le câblage comme
maximalement raffiné. Ne choisissez pas de valeurs physiologiques, gains, signes,
seuils ou comportements cibles hors d'une cible et d'une campagne versionnées.

## Sources de vérité à lire

Avant une modification structurelle ou de calibration, consulter au minimum :

1. `PROJECT_STATE.md` pour l'état courant et les fronts ouverts ;
2. `docs/wiring-methodology.md` pour la définition de « câblé » ;
3. `decisions/0002-exhaustive-terminal-coverage.md` pour les dispositions
   terminales et la cohérence sectorielle ;
4. les fiches pertinentes de `ledger/` et leurs validations ;
5. `docs/provenance-policy.md` lorsqu'une relation scientifique est ajoutée ou
   modifiée.
6. `docs/calibration-methodology.md`, l'ADR 0005 et `calibration/state.yaml` pour
   tout paramètre, cible, campagne ou protocole d'évaluation.

Le registre, les ADR et les manifestes reproductibles restent canoniques. Les
skills indiquent comment travailler avec eux ; ils ne remplacent pas leur contenu.

## Périmètre neuronal MaleCNS

La table d'annotations contient 211 577 corps, pas 211 577 neurones. Ne jamais
assimiler une ligne annotée à un neurone. Appliquer et contrôler les drapeaux de
l'ADR 0007 : les 166 700 neurones canoniques sont inclus dans le runtime, tandis
que glies et corps non résolus restent conservés, classifiés et auditables.

## Contrat de câblage

Chaque canal terminal d'entrée ou de sortie doit avoir exactement une disposition :
`exact`, `parameterized`, `basal`, `proxy`, `sink` ou `blocked`.

- Une boîte locale paramétrable peut valablement terminer un câblage même lorsque
  sa correspondance interne est inconnue.
- Une valeur injectée directement par un smoke test à la place d'une boîte reste
  `blocked`.
- Le smoke test peut fournir les entrées déclarées et des paramètres arbitraires,
  mais ne doit pas court-circuiter une transduction ou un routage absent.
- Une politique doit être cohérente à l'échelle d'une famille fonctionnelle. Des
  parties exactes et paramétrables peuvent coexister dans la même pile ; une autre
  nature de boîte exige une frontière biologique ou fonctionnelle justifiée.
- Une différence de cardinalité n'impose pas une correspondance point-à-point :
  utiliser une boîte de routage ou de transfert dont les degrés de liberté sont
  explicitement comptés.

## Traçabilité attendue

Toute décision substantielle doit permettre de retrouver :

- ce qui est couvert, simplifié, paramétrable, bloqué ou exclu ;
- le statut d'inventaire, routage/décomposition, implémentation et validation ;
- les cardinalités d'entrée, de sortie et les degrés de liberté ;
- la source utilisée, l'affirmation qu'elle soutient, la règle dérivée et les
  hypothèses restantes ;
- le test ou protocole associé, sa commande, ses critères et son dernier résultat ;
- ce qui reste à faire dans `next_action` et la raison de tout blocage ;
- les changements de progression dans `PROJECT_STATE.md` et le tableau de bord.

Une absence de source doit être déclarée. Ne jamais transformer une intuition en
fait pour améliorer un pourcentage.

## Contrat de calibration

- Distinguer `evidence_transfer`, `technical`, `local_interface`,
  `behavior_targeted` et `evaluation_only`.
- Une stabilité entraînée est un résultat technique, pas un comportement émergent.
- Toute action reconnaissable utilisée dans une loss, la sélection de modèle,
  l'early stopping ou le réglage manuel contamine la lignée pour ce comportement.
- Toute calibration comportementale exige l'accord explicite de l'utilisateur et
  un marquage très visible dans les registres, rapports et descendants.
- Les protocoles `evaluation_only` sont verrouillés avant fitting et ne servent
  jamais à choisir des paramètres. Une inspection qui entraîne un changement
  contamine cette version du protocole.
- Les valeurs biologiques reprises conservent source, unités, transformation,
  incertitude et limites d'applicabilité.
- La calibration ne doit ni modifier silencieusement la topologie, ni ajouter un
  contrôleur comportemental externe autour de MaleCNS.
- ADR 0006 autorise une unique exception diagnostique isolée :
  `diagnostic_viewer.bat` peut contourner MaleCNS pour explorer MuJoCo, mais son
  overlay, son namespace et ses sorties doivent rester `NOT MALECNS / NOT
  CALIBRATION`. Rien de ce chemin ne peut entrer dans une calibration, une
  évaluation scientifique ou un claim comportemental.
- Les sorties lourdes vont sous `runs/calibration/`; Git conserve les configs,
  lignées, hashes, résumés, échecs, décisions et prochaines actions.

## Initiative et cas non prévus

Ces règles définissent des invariants, pas une recette rigide. Adapter la méthode à
la forme réelle des données et préférer l'abstraction locale la plus simple qui
préserve l'intention scientifique. Un nouveau type de boîte ou une nouvelle
disposition peut être proposé s'il résout un cas réellement différent sans cacher
de capacité comportementale.

Prendre les décisions locales, réversibles et faiblement risquées qui permettent
d'avancer. Demander l'avis de l'utilisateur lorsqu'un choix modifierait la portée
scientifique, mélangerait des politiques incompatibles dans un secteur, ajouterait
une capacité de contrôle importante ou changerait irréversiblement l'interprétation
du projet. Documenter ensuite la décision sous forme d'ADR si elle est transversale.

## Validation et livraison

- Régénérer les manifestes lorsqu'une règle de câblage change.
- Ajouter des tests portant sur les invariants et les cardinalités, pas seulement
  sur des formulations textuelles.
- Lancer les tests pertinents ; lancer `run_wiring_smoke.bat` si le runtime ou le
  parcours global change ; régénérer `dashboard.bat` après un changement de statut.
- Les scripts destinés à être lancés par double-clic doivent afficher un avancement
  riche, un résumé final et attendre une touche avant fermeture.
- Ne pas versionner les données brutes, secrets, environnements, sorties `runs/`
  ou rapports générés.
- Préférer un commit local cohérent et validé par lot de travail. Ne jamais pousser
  sans demande explicite. Pour une simple analyse ou revue, ne pas modifier ni
  commiter sauf demande.

## Skills du dépôt

- Utiliser `flymatrix-wiring` pour construire ou modifier une boîte, un groupe, un
  fil, un manifeste ou un chemin runtime de câblage.
- Utiliser `flymatrix-wiring-audit` pour déterminer ce qui est réellement terminé,
  trouver les contournements et vérifier l'honnêteté des statuts et indicateurs.
- Utiliser `flymatrix-calibration` pour créer ou exécuter une cible, une campagne,
  un jeu de paramètres, un runner ou une dynamique temporelle de calibration.
- Utiliser `flymatrix-calibration-audit` pour auditer en lecture seule la
  reproductibilité, la provenance, les fuites comportementales et les claims.
