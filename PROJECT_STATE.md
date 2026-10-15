# État de reprise du projet

Mise à jour : 2026-10-15. L'inventaire/DAG, le compilateur périphérique et le
runner autonome minimal sont validés. Le prior neurotransmetteur/signe est gelé
et un modèle central signé minimal est désormais exécutable et structurellement
validé. Sept régimes non ajustés ont été caractérisés de façon reproductible ;
une première campagne technique a produit 32 candidats admissibles. Une étude
aval préenregistrée montre qu'ils divergent fortement aux sorties motrices. Une
contrainte indépendante de raffinement temporel exclut maintenant un candidat et
conserve 31 survivants, mais aucun paramètre de référence n'est identifié ni gelé.
Le modèle à douze paramètres partagés est désormais enregistré comme une hypothèse
de capacité à haut risque, pas comme la dimensionalité admise de MaleCNS. Le gate
plus amont est maintenant fermé globalement : ni ce runtime rate continu, ni un
LIF point-neuron homogène ne sont promus sur tout MaleCNS. L'ADR 0016 accepte une
architecture event-capable typée/hybride. Une première passe locale affecte maintenant les dix
motoneurones T1 fléchisseurs du tibia à une exigence événementielle ; les 36
afférences FeCO restent explicitement `dual_unresolved`. Les quatre frontières
locales sont maintenant exécutables et testées : cinématique→activité graduée,
cinématique→intensité événementielle, événements moteurs→force biologique, puis
force→commande directe MuJoCo comme pont surrogate séparé. Ce résultat ne choisit
aucune constante et ne généralise pas hors de ce périmètre. Les sources suivantes
sont maintenant préréférencées : trois tables FeCO traitées et leur README font
environ 2 Mo, tandis qu'un pilote moteur d'une cellule par classe fait environ
860 Mo au lieu des 48,76 Go complets. Les trois archives pilotes exactes sont
maintenant acquises et vérifiées (860 357 945 octets) ; le téléchargement reste
strictement opt-in et les données lourdes restent ignorées par Git.

La revue méthodologique du 15 octobre a rendu explicites quatre risques qui ne
doivent plus rester dispersés dans les résultats. Les conversions internes
event→graded et graded→event ont désormais leur propre famille de paramètres sous
l'ADR 0017 ; les constantes `0.5` et `0.05` des sentinelles restent des fixtures,
pas des valeurs par défaut. Les 166 419 populations `dual_unresolved` doivent être
réduites à un cône causal compté pour le premier claim local, pas masquées par les
deux extrêmes runtime. Le couplage source basale×efficacité×conversion×seuil est un
risque d'identifiabilité autonome. Enfin, la chaîne motrice reste bloquée pour
58 025 affectations contenant une classe lente, et le futur test tactile dépend
d'une chaîne mécanoréceptrice distincte de FeCO encore non calibrée.

Le petit code source moteur public est désormais lui aussi un contrat exécutable
hash-verrouillé : il comptabilise 23 cellules actives (7 rapides, 7 intermédiaires,
9 lentes), les 194 essais du pilote sélectionné et les règles agrégées de filtrage,
comptage de spikes et calibration de sonde. L'inventaire des MAT a ensuite montré
le schéma réel. Les deux scripts historiques qui construisaient les tables finales,
absents de la branche publique courante, ont été retrouvés dans le commit public
`ebe1e5008fc5f76954cea3973aa30b103ec3fa9a`. Le port Python versionné reprend donc
leurs fenêtres et regroupements sans les inférer : 194 essais déclarés, 11 exclus
par leur drapeau source, 183 utilisables et 22 lignes agrégées. L'équivalence
bit-à-bit avec MATLAB n'a pas été exécutée et aucun noyau temporel n'est identifié.

La procédure agrégée a maintenant consommé le manifeste hash-verrouillé et terminé
les trois ajustements. Pour la cellule lente, la droite passant par zéro reproduit
la forme du script source ; son application aux cellules rapide et intermédiaire
reste explicitement une extension diagnostique. Les pentes diagnostiques sont
respectivement 4,7753, 0,8268 et 0,02284 µN/spike : leur ordre rapide > intermédiaire
> lente est cohérent avec la publication, mais une cellule par classe ne mesure
ni distribution de population ni correspondance aux dix body IDs. Le bootstrap
porte sur les lignes agrégées, pas sur les essais bruts ; celui de l'intermédiaire
est dégénéré. Zéro pente est promue et aucune dynamique temporelle n'est prétendue.

Une campagne temporelle distincte exploite maintenant les traces brutes sans
confondre forme et amplitude. Elle comptabilise les 194 essais, puis retient 18
réponses mono-spike rapides et 15 intermédiaires à position neutre. Une forme
bi-exponentielle causale, identique à la famille exécutable du runtime, explique
0,7844 de l'énergie normalisée tenue à l'écart pour la cellule rapide mais
seulement 0,2767 pour l'intermédiaire. L'enveloppe rapide est relativement étroite ;
l'intermédiaire reste faible et large. La cellule lente ne contient aucun essai
mono-spike isolé et n'est donc pas ajustée par ce protocole. Comme le design a été
informé par une inspection exploratoire, que chaque trace est normalisée par son
propre pic et qu'il n'y a qu'une cellule par classe, ce résultat reste un
diagnostic de forme intra-cellule : zéro noyau populationnel, valeur runtime ou
affectation de body ID est promu.

Le pont force biologique→moteur direct est maintenant un ensemble d'ingénierie
exécutable, sans prétendre résoudre la conversion physique. Le diagnostic gèle
les hashes de topologie, de mécanique et d'actionnement, comptabilise les 110
routes candidates des dix motoneurones T1 vers 22 actionneurs des pattes
antérieures, puis exécute 198 essais tethered. Les 22 actionneurs répondent dès
la plus petite commande testée (`1e-6`) : leurs seuils exacts sont donc censurés
à gauche. Conditionnellement aux trois pentes une-cellule non promues, trois gains
de `4,3788e-5` à `1,0471e-3` commande/µN restent détectables tout en gardant la
force candidate la plus forte sous la moitié de la limite MuJoCo. Aucun gain,
offset, routage ou classe de body ID n'est sélectionné. L'absence de géométrie
d'insertion musculaire et de bras de levier maintient la conversion biologique
µN→couple explicitement non identifiée.

La première enveloppe locale sensorielle–CNS–motrice est maintenant compilée
sans sélectionner un chemin ni une valeur. Les 36 FeCO et les dix motoneurones
forment 360 couples : tous sont reliés dans le graphe canonique par un à trois
sauts dirigés (10 à un saut, 101 à deux, 249 à trois). L'enveloppe exhaustive
limitée à un/deux sauts contient dix arêtes directes, 682 chemins à deux sauts et
atteint chacun des dix terminaux moteurs. Elle expose 150 nouveaux neurones
intermédiaires non terminaux — 133 VNC intrinsèques, 7 ascendants, 7 moteurs et
3 descendants — conservés `dual_unresolved` plutôt que forcés dans le rate ou le
LIF. Côté interfaces, les sept chemins FeCO atomiques deviennent douze
combinaisons fonctionnelles et 24 alternatives avec les deux représentations
natives ; côté moteur, les 59 049 affectations de classes restent factorisées,
avec 110 arêtes de base de routage et trois gains. Sur 990 probes motrices
locales, 660 s'exécutent comme diagnostics rapide/intermédiaire et 330 restent
explicitement bloquées par l'absence de noyau temporel lent. Zéro paramètre,
route, chemin ou comportement est sélectionné. La chaîne est donc maintenant
structurellement et algorithmiquement comptabilisée, mais ses populations
intermédiaires et ses valeurs d'interface ne sont pas encore calibrées ni gelées.

La passe rules-first suivante ferme désormais la **comptabilité** des 150
intermédiaires sans prétendre fermer leur physiologie. Deux corps annotés `Ti
extensor MN` reçoivent une exigence événementielle au niveau du type, soutenue par
des enregistrements indépendants de spikes des motoneurones extenseurs tibiaux de
Drosophila. Les 148 autres restent `dual_unresolved` : 147 ont un type annoté mais
aucune preuve locale de dynamique native, et le corps `852122` n'a pas de type.
Les 150 ont un prior neurotransmetteur gelé (82 acétylcholine, 36 GABA, 27
glutamate, 5 `unclear`), mais ce prior n'est jamais transformé en choix
event/graded. Les 673 chemins à deux sauts passant par un nouvel intermédiaire
sont tous attribués ; leur participation sert seulement à prioriser l'acquisition
future de preuves. Zéro constante, chemin fonctionnel ou comportement est choisi.

La propagation de cette incertitude est maintenant préréférencée et exécutable
sans réduire silencieusement l'espace scientifique `2^148`. Un panneau
diagnostique déterministe de 50 profils fait apparaître chacun des 148 corps 25
fois comme candidat événementiel et 25 fois comme candidat gradué ; les 10 878
paires voient toutes les quatre combinaisons. Ce panneau ne couvre pas les
interactions d'ordre supérieur et ne définit aucune probabilité biologique. Les
24 alternatives FeCO sont acceptées comme ensemble non sélectionné. Côté moteur,
1 024 affectations ne contenant que les classes rapide/intermédiaire disposent de
noyaux diagnostiques ; les 58 025 affectations contenant la classe lente restent
explicitement bloquées. Aucun noyau lent n'est emprunté, et aucune valeur, route,
représentation native ou réponse corporelle n'est promue.

Le code public qui produit l'observation calcium FeCO est verrouillé sur un commit
précis et reproduit par un contrat exécutable. Il sépare activation locale et noyau
GCaMP causal normalisé, mais révèle deux divergences conservées comme telles :
centrage du claw à 80 ou 90 degrés selon le chemin, et seuils hook/club à 5 ou
50 degrés/s selon fitting ou application documentée. Zéro valeur est promue, et
le calcium reste une observation qui ne choisit pas entre événements et activité
graduée.

La comparaison biologique correspondante est maintenant une procédure
préenregistrée plutôt qu'une intention. Elle fixe sept chemins concurrents, tient
chaque animal complet à l'écart, conserve essais et ROI dans le même fold, et
recommence la convolution à chaque frontière d'essai. Contrairement au script
source, elle ne normalise pas par un maximum qui aurait lu le calcium tenu à
l'écart : les chemins fixes ajustent gain/offset sur les animaux d'entraînement,
tandis que les chemins de fit claw réajustent cinq coefficients à travers le
noyau GCaMP paddé. La concaténation exacte du script public et un port sûr par
essai coexistent explicitement. Cette différence de capacité et de frontière
interdit un gagnant automatique.
Les oracles synthétiques de séparation et de comptabilité passent. Le test
authentifié Dryad a maintenant acquis et vérifié exactement les trois Parquet et
leur documentation : 2 025 899 octets dans le sous-ensemble FeCO complet, 64 300
lignes inspectées, zéro doublon de ligne et aucun secret dans le rapport. Les deux
petits fichiers documentaires moteurs et les trois archives motrices totalisant
860 357 945 octets sont maintenant vérifiés ; leur acquisition a été explicitement
demandée et n'est jamais déclenchée par défaut.
Les sept candidats ont maintenant terminé leurs 86 folds biologiques tenus à
l'écart sur 33 766 lignes retenues, sans fold bloqué. Le chemin hook à seuil
-5 degrés/s a des résidus agrégés inférieurs au chemin d'application à -50
degrés/s ; les variantes claw et club restent proches. Aucun gagnant, paramètre
runtime ou représentation native n'est néanmoins promu : capacités et politiques
de frontière diffèrent, et le calcium seul ne tranche pas événement contre gradué.

Un front indépendant du jeton Dryad ferme désormais le **contrat de mesure** de
la future stabilité incarnée. `embodied_stability_metrics.bat` relit le replay
physique gelé d'une seconde et calcule sept groupes descriptifs : temps/finitude,
résumé CNS, racine, articulations, contacts et actionnement. Le run v0 compte 200
trames finies, un déplacement maximal de racine de 1,409 unité modèle, une dérive
d'orientation de 0,132 radian, quatre trames sans contact au sol et 261 transitions
de contact. Ces nombres ne sont pas des seuils et le mouvement n'est pas un
comportement. Cinq lacunes restent explicitement ouvertes : COM, limites
articulaires, énergie biologique, jerk physique et récupération sur trajectoires
appariées. Zéro paramètre ou seuil a été choisi.

La version complète v1 est maintenant validée par
`embodied_measurement_contract_v1.bat` sur trois resets passifs déterministes :
deux références répétées et une perturbation générique appariée. Elle mesure le
centre de masse pondéré sur 67 corps FlyBody, les 102 limites articulaires, le
jerk physique à cadence observée de 5 ms, six contacts et leurs forces, un proxy
de travail direct-MOTOR explicitement non biologique, les masques d'échec et la
récupération appariée. Le fixture passif produit déjà 27 échantillons hors limites
sur 14 trames ; cette observation n'est ni un seuil ni un résultat de stabilité.
Zéro paramètre, seuil, profil d'incertitude ou comportement a été sélectionné. Le
jalon suivant a donc été la préréférence du planning borné du pilote technique,
pas une nouvelle extension des mesures.

Ce planning est désormais matérialisé par
`neutral_embodied_pilot_schedule.bat`. Il contient exactement 120 tuples et 240
épisodes baseline/perturbé : les 50 profils intermédiaires, 24 alternatives FeCO,
110 routes et trois gains sont tous couverts. Un échantillon déterministe de 120
sur 1 024 affectations motrices rapide/intermédiaire est équilibré 60/60 pour
chacun des dix corps et couvre les quatre états de chaque paire. Les 904 variantes
exécutables non planifiées et les 58 025 variantes lentes bloquées restent
comptées. Il s'agit d'un panneau local sans fitting : les sorties non couvertes
sont gelées à zéro, aucun mouvement ne peut sélectionner un candidat et aucune
stabilité globale n'est encore revendiquée.

Le premier sentinel de l'adaptateur est maintenant exécuté par
`neutral_embodied_adapter_sentinel.bat`. Quatre IDs fixés avant observation ont
consommé le planning immuable et terminé 8/8 épisodes physiques appariés en
environ 18 secondes, soit une projection linéaire d'environ 9 minutes pour les
240 épisodes. Pour chaque tuple, la classe motrice rapide/intermédiaire, le noyau
diagnostique, la route et le gain produisent une trace directe-MOTOR isolée ; les
101 autres actionneurs restent exactement nuls. Ce résultat ferme la plomberie
moteur→physique, pas la chaîne complète : l'événement moteur est un fixture
synthétique déclaré, les alternatives FeCO et les 148 affectations intermédiaires
sont chargées mais n'affectent pas encore l'exécution. Aucun mouvement n'a servi à
choisir un candidat, aucune valeur n'est promue et aucune stabilité n'est évaluée.

Le second sentinel ferme maintenant le gate d'**exécution locale**, sans fermer
la calibration. `neutral_embodied_full_chain_sentinel.bat` reprend les mêmes
quatre IDs fixés et termine 4/4 tuples, soit 8/8 épisodes appariés, après avoir
effectivement exécuté la cinématique synthétique, les fonctions source FeCO, la
représentation graduée ou événementielle planifiée, les 150 intermédiaires typés,
les dix motoneurones événementiels, puis l'adaptateur moteur et MuJoCo. Les traces
neuronales diffèrent entre les quatre tuples et toutes les sorties non routées
restent nulles. Ce passage utilise volontairement des fixtures diagnostiques
visibles — projection round-robin des trois fonctions FeCO sur 36 corps, poids
locaux normalisés, candidat excitateur pour les signes inconnus et constantes
neuronales non ajustées. Il ne valide donc aucune affectation, valeur, stabilité
ou biologie. Le panneau local complet est maintenant exécuté par
`neutral_embodied_full_chain_panel.bat` : 120/120 tuples et 240/240 épisodes
appariés terminent, sans erreur runtime, paire non finie ni budget épuisé. Les 50
profils, 24 alternatives FeCO, 120 affectations motrices, 110 routes et trois
gains sont tous présents. Trois corps routés restent silencieux et sont conservés
dans le résultat ; 115 hashes neuronaux sont distincts, car changer une route ou
un gain moteur ne doit pas nécessairement changer la trace amont. Le mouvement
n'a sélectionné aucun candidat. Ce résultat ferme seulement la robustesse de
l'implémentation locale sur le panneau prévu : les fixtures diagnostiques restent
non calibrées et aucune stabilité globale n'est acceptée.

Le lot suivant supprime maintenant ces choix uniques au niveau du **planning**,
sans prétendre les avoir identifiés. Dix-sept groupes de canaux FeCO sont décrits
par 81 profils ternaires : chaque groupe reçoit 27 fois chacune des fonctions
claw/club/hook et chaque paire voit exactement neuf fois chacun des neuf états.
Les 32 intermédiaires dont `sign_code=0` sont décrits par 64 profils binaires :
chaque corps reçoit 32 fois chaque signe et chaque paire voit 16 fois chacun des
quatre états. Douze profils numériques séparent les constantes temporelles du
comparateur événementiel sourcé des amplitudes techniques non biologiques ; les
comptages structuraux utilisent un repère `incoming_L1_synapse_fraction` nommé,
pas une normalisation cachée. Le planning exact contient 240 tuples, reprend les
120 tuples précédents deux fois et couvre tous les nouveaux profils. Le sentinel
`neutral_embodied_declared_neural_sentinel.bat` exécute maintenant 240/240 lignes
finies sans MuJoCo. Il consomme les 81 profils FeCO, 64 profils de signe et 12
profils numériques ; les 32 inversions de signe ont une contribution aval non
nulle et antisymétrique, les trois axes numériques changent leur micro-probe et
chaque colonne structurelle non vide respecte exactement le repère incoming-L1.
Ces contrôles ferment le gate de consommation runtime, pas la calibration : zéro
membre, valeur ou stabilité est accepté, et les magnitudes neuronales ne servent
pas à classer les candidats. Le prochain gate est le premier panneau physique
neutre préenregistré avec mécanique et actionneurs gelés.

Ce gate physique causal est maintenant fermé sur un sentinel borné par
`neutral_embodied_declared_closed_loop_sentinel.bat`. La cinématique synthétique
normalisée sur sa trace complète a été remplacée par l'angle anatomique interne
fémur-tibia calculé causalement depuis les ancres MuJoCo des deux pattes avant.
L'oracle à cinq positions est strictement croissant à gauche et à droite et couvre
au minimum 139,76 degrés. Seize tuples choisis par un stride déterministe sur le
planning exact terminent 16/16, soit 32/32 épisodes appariés de 0,2 s, au même pas
physique et neuronal de 0,1 ms. Les sources FeCO sont actives dans chaque épisode,
la perturbation est détectée dans chaque paire, aucune commande ne fuit vers un
actionneur non planifié et cinq routes produisent effectivement une commande
motrice non nulle. Un dry-run non livré à quatre lignes avait laissé les quatre
routes silencieuses ; il a été refusé comme preuve de fermeture et cette exception
est conservée dans la campagne. Le résultat ne sélectionne pourtant aucun de ces
cinq cas : zéro fit, promotion, stabilité ou comportement. Les 14 frames de
violation de limites articulaires présentes dans chaque baseline restent une
pathologie descriptive. Le lot suivant a donc appliqué exactement ce contrat aux
240 membres avant tout filtrage technique.

Le panneau causal exhaustif a maintenant été exécuté par
`neutral_embodied_declared_closed_loop_panel.bat`, et son résultat négatif est
conservé plutôt que corrigé après inspection. Les 240 lignes sont comptabilisées :
237 terminent leurs deux branches réinitialisées, soit 474 épisodes physiques,
mais `declared_tuple_029`, `declared_tuple_041` et `declared_tuple_149` sont
arrêtés avant l'application d'une commande `MOTOR` non finie ou supérieure à la
limite gelée de 0,01. Tous trois utilisent `numeric_05` et le gain maximal ; 029
et 149 proviennent du même tuple de base avec d'autres profils déclarés. Les 16
paires de traces du sentinel sont reproduites bit à bit avec une unique instance
MuJoCo réinitialisée, ce qui exclut une dérive due à l'optimisation de runtime.
Parmi les 237 lignes terminées, 172 routes planifiées restent silencieuses et 65
émettent une commande non nulle ; ces nombres ne classent aucun candidat. Il n'y
a eu ni clipping, ni seuil ajouté après coup, ni fit, sélection, promotion,
stabilité ou exposition comportementale. La prochaine étape est un diagnostic
technique préenregistré et borné des trois interactions qui dépassent la limite,
puis seulement une politique de pathologie indépendante appliquée aux 240 lignes.

Ce diagnostic borné est maintenant fermé par
`neutral_embodied_command_limit_diagnostic.bat`. Les trois lignes, leurs branches
baseline/perturbée et deux répétitions déterministes donnent 12/12 premiers
franchissements identiques. Ils surviennent entre les pas natifs 634 et 1036
(63,4--103,6 ms) ; les commandes tentées, toutes finies, vont de 0,010008805 à
0,010057705 et sont arrêtées avant application. Le partage de `numeric_05` et du
gain maximal est visible, tout comme le partage du tuple de base et du corps routé
entre 029 et 149, mais cette observation ne prouve pas quel facteur est causal et
n'autorise aucun clipping ou rejet de domaine. La prochaine étape est donc le
plus petit panneau d'isolation factorielle préenregistré, puis une politique de
pathologie technique appliquée à toutes les 240 lignes.

Ce panneau d'isolation a été exécuté et son échec est conservé. Il teste quatre
ablations à un seul facteur autour de chacune des trois lignes, dans les deux
branches : 12 variantes et 24 probes au total. Le gain médian termine 6/6 probes,
mais les ablations numériques ne définissent pas un domaine sûr : dix branches
atteignent encore la limite et seulement 14/24 probes terminent. L'analyse du
planning révèle en outre que chacun des douze profils numériques n'y apparaît
qu'avec un seul des trois gains ; leurs effets principaux sont donc confondus dans
ce panneau historique. Aucune règle générale sur un gain ou un profil numérique
n'est tirée de ce résultat.

La politique indépendante suivante est maintenant fermée par
`neutral_embodied_command_pathology_policy.bat`. Elle ne généralise pas : les 240
lignes immuables ont chacune une disposition versionnée, 237 sont seulement
« observées dans la limite MOTOR » et peuvent entrer dans le prochain gate
technique, tandis que 029, 041 et 149 restent bloquées comme composites exacts.
Cela ne sélectionne ni ne promeut aucun survivant et n'accepte pas la stabilité.
Une combinaison nouvelle ou modifiée n'hérite jamais de ce statut : elle doit
exécuter le même garde avant application et échouer fermée. Le front actif devient
donc un gate de stabilité et d'identifiabilité sans comportement nommé sur les 237
lignes admises, avec le hash de cette politique gelé.

Ce gate causal est maintenant exécuté par
`neutral_embodied_feedback_identifiability.bat`. Les 237 lignes admises restent
toutes comptabilisées : les 172 routes dont la commande était exactement nulle
dans le panneau gelé sont conservées comme `silent_noninformative`, sans rejet ni
promotion ; les 65 routes actives ont chacune quatre branches de 0,2 s. Le replay
ouvert de la commande native de baseline reproduit l'état non perturbé dans la
tolérance gelée. Sous la même impulsion générique, 64 routes modifient leur
commande en boucle fermée et produisent un écart physique distinct du replay ;
`declared_tuple_028` ne modifie ni commande ni état sous ce probe et reste
non identifiable. Les trois composites 029, 041 et 149 restent bloqués avant
application. Ce résultat ferme l'identifiabilité causale du protocole, pas la
stabilité : aucune amplitude, route ou configuration n'est classée par qualité,
et aucun paramètre n'est promu.

Le critère technique suivant a été préenregistré puis exécuté sans adaptation
postérieure avec `neutral_embodied_feedback_nonamplification.bat`. Les 65 routes
actives reçoivent chacune une baseline, son rejeu exact, puis quatre perturbations
miroir (translation avant/arrière et rotation ±) en commande gelée et en feedback,
soit 650 épisodes finis. Trois composites exacts — `declared_tuple_129`,
`declared_tuple_141` et `declared_tuple_238` — passent simultanément les critères
d'adaptation de commande, d'effet physique, de position finale, de vitesse finale
et de non-aggravation des masques de défaillance. Soixante-et-un sont mixtes ou
amplifiants et le tuple 028 reste non identifiable. Les trois survivants forment
un ensemble technique local fini et non classé ; aucune valeur individuelle,
physiologie, stabilité du corps entier ou comportement n'est promu. Les 172 routes
silencieuses et les trois lignes bloquées restent explicitement non résolues.

Un compilateur de frontière de gel conditionnelle est maintenant exécuté avec
`front_leg_member_conditioned_freeze_boundary.bat`. Il reconstruit les trois
survivants depuis leurs lignes exactes verrouillées par hash et produit un hash
sémantique par bundle sensoriel–central–moteur. Il ne transforme pas leur succès
composite en succès marginal : aucune famille n'est gelée indépendamment, aucun
membre n'est classé ou choisi comme référence. Les six familles de sources basales
sont comptées mais explicitement `not_exercised_no_freeze`, donc aucune valeur
nulle implicite ne contaminera le prochain run.

Le gate basal a d'abord révélé que l'étape « corps entier » formulée auparavant
était trop optimiste. Après fermeture de la comptabilité globale et du moteur
décrites ci-dessous, `basal_low_capacity_readiness.bat` a été régénéré : il
comptabilise les six familles, 2 212 canaux et 6 041 terminaux, consomme les
166 431 dispositions atteintes et accepte la mécanique des deux extrêmes du
runtime typé/hybride. Il préenregistre toujours trois formes de sensibilité
pauvres et comportement-naïves sans émettre magnitude, seed ou série temporelle.
Ce blocker d'implémentation est maintenant fermé par
`basal_source_bridges.bat`. Les 6 041 terminaux possèdent chacun deux candidats
explicites : un processus de présence événementielle de Poisson semé, avec borne
de collision par pas, et une conversion Hz→activité graduée monotone, bornée et
à échelle explicite. Les trois formes préenregistrées — silence, uniforme par
terminal et masse égale par famille — ont toutes été exécutées pendant 96 pas
sous les deux extrêmes d'affectation. Les six runs CUDA sont finis et laissent
les 269 neurones inactifs au repos. Les taux, seeds et l'échelle utilisés ne sont
que des fixtures d'ingénierie non promouvables : aucune classe `dual_unresolved`,
valeur basale ou échelle de conversion n'est acceptée. Le comparateur rate
normalisé historique ne peut toujours pas servir de raccourci silencieux.

Le point de contrôle visuel existe néanmoins sous une frontière causale exacte.
`front_leg_member_physical_preview.bat` produit trois trajectoires indépendantes
du contrôleur, une pour chacun des tuples 129, 141 et 238. Elles contiennent le
corps FlyBody complet pendant 0,2 s et passent toutes le lecteur headless, mais le
contrôleur n'est que la chaîne locale 36 afférences → 150 intermédiaires → 10
motoneurones avec un actionneur ciblé. Elles n'exécutent ni basal, ni vision, ni
MaleCNS récurrent complet et ne prouvent aucun comportement ou stabilité. Le point
d'inspection utilisateur reste ouvert ; celle-ci ne peut provoquer un réglage,
classement ou rejet implicite.

Le bloc de comptabilité global demandé par le gate basal est maintenant fermé.
`basal_population_reachability.bat` reconstruit les six familles disjointes (2 212
canaux, 6 041 corps terminaux) et calcule leur fermeture dirigée exacte sur le
graphe canonique. Leur union atteint 166 431/166 700 neurones en cinq sauts au
plus : ce front consomme donc pratiquement tout MaleCNS, et non un petit module.
Les douze corps déjà acceptés localement restent `event_required`; les 166 419
autres sont conservés `dual_unresolved`. Les 25 582 574 arêtes internes à cette
portée sont toutes réparties entre les quatre classes de frontière event/dual, et
chaque terminal source possède une disposition de pont event/graded. Zéro valeur,
générateur d'événements ou conversion Hz→activité graduée n'est choisi. Les formes
de pont ont depuis été rendues exécutables par des fixtures diagnostiques, sans
qu'aucune valeur ne soit acceptée.

Le gate d'**exécution typée/hybride globale** est maintenant fermé au niveau
logiciel, sans résoudre la physiologie. `basal_typed_hybrid_runtime_sentinel.bat`
fait du vecteur d'affectation par neurone une entrée explicite du noyau sparse et
exécute deux extrêmes diagnostiques sur les 166 431 neurones atteints. Le premier
conserve les douze exigences événementielles exactes et instancie les 166 419
inconnus comme candidats gradués : ses quatre frontières event→event,
event→graded, graded→event et graded→graded sont toutes actives. Le second
instancie tous les neurones atteints comme candidats événementiels. Les deux runs
CUDA de 24 pas restent finis, livrent les événements au délai déclaré de 1,8 ms
et laissent les 269 neurones hors portée exactement au repos. Ils mesurent environ
quelques centaines de pas/s selon le profil et utilisent environ 217 Mo de mémoire GPU.
Ces deux points ne couvrent pas l'espace `2^166419`, ne choisissent aucune classe
et ne calibrent aucune constante. Le lot suivant a depuis exécuté les ponts
source avec des fixtures explicitement non physiologiques ; il n'en accepte
toujours aucune valeur.

Le gate global de classe neuronale est maintenant fermé avec la décision
`revise`. Une référence
LIF événementielle à délai fixe reproduit exactement une implémentation NumPy
indépendante sur un petit graphe récurrent, puis comptabilise les 25 582 938
arêtes du MaleCNS canonique. Le benchmark CPU/GPU complet livre chaque événement
attendu sous trois charges synthétiques et tient largement dans les 8 Go du GPU,
mais l'implémentation Torch générique n'atteint encore qu'environ 0,04 fois le
temps réel à 0,1 ms. Les probes temporels établissent trois pertes d'information
du rate à 5 ms. Le pilote aBN1 est directionnellement positif pour LIF et les neuf
séries rate/bridge : il ne justifie pas les quelque seize GPU-heures du run complet
pour forcer un vainqueur global. L'architecture retenue exige les événements et
délais là où ils sont nécessaires, permet les populations graduées sourcées et
laisse l'inconnu `dual_unresolved`.

La transférabilité de la première référence circuitaire indépendante est désormais
auditée plutôt que supposée. aBN1, aDN1 et aDN2 ont des correspondances de type
exactes dans MaleCNS et les quatre classes de chemins JON→aBN et aBN→aDN sont
présentes. La correspondance aBN2 reste toutefois partielle : `CB1740` et
`CB1779` se replient sur un ensemble candidat MaleCNS ambigu de quatre cellules,
tandis que `CB3129` n'a pas de correspondant résolu. Le protocole scientifique
reste donc non verrouillé et aucun seuil de réponse n'a été choisi.

Un second gate causal est maintenant fermé, dans un périmètre borné, avant toute
calibration incarnée globale. Le chemin courant utilise explicitement 102 actionneurs MuJoCo
`ActuatorType.MOTOR`, et non des servos de position ou de vitesse ; le risque
signalé n'est donc pas copié littéralement. L'abstraction directe articulation/
couple peut néanmoins remplacer muscles, compliance et réflexes locaux. La
première passe a hashé le contrat bas niveau et mesuré impulsion, échelon,
relâchement et saturation sur les 102 canaux. La seconde passe sépare maintenant
mécanique passive, commandes gelées en boucle ouverte et feedback MaleCNS. Le
rejeu gelé reproduit exactement l'état non perturbé ; le feedback réagit mais ne
change la déviation physique finale que d'environ deux parties par million. Une
fixture tethered sans sol confirme 102/102 réponses et une symétrie intrinsèque
des 41 paires homologues. Le direct-motor est donc accepté comme surrogate court
terme explicite, jamais comme physiologie musculaire ou preuve de stabilisation.

L'ADR 0015 ajoute les risques de compensation par interfaces périphériques,
d'afférences inconnues, de mécanismes absents et d'homogénéité point-neuron. Il
autorise explicitement un modèle neuronal typé ou hybride. La préférence
prospective pour le premier test devient une réponse tactile localisée et
latéralisée d'une patte, sous réserve de résolution physique et de sources ; ce
n'est toujours ni un protocole verrouillé ni une cible d'entraînement.

Le premier gate local de sources basales est maintenant exécuté. Il comptabilise
les 2 212 canaux couvrant 6 041 afférences, dérive 211 partitions d'audit et
n'émet volontairement aucune valeur. Les mesures publiées sont en spikes/s alors
que l'entrée centrale courante est une activité normalisée sur le vecteur sensoriel
complet. Ce conflit d'unités ne sera pas résolu par un convertisseur universel :
chaque pont doit viser une population événementielle, graduée, ou une frontière
de conversion typée dont les unités et l'incertitude sont explicites.

Cette fiche doit être actualisée après tout commit qui modifie le score de câblage
ou les fronts structurels. En cas d'écart, le registre et le tableau de bord
recalculé font autorité.

## Objectif courant

La couverture terminale du **câblage structurel v0 est complète** : aucun fil
d'interface inventorié ne reste sans disposition. La revalidation indépendante
des regroupements, matrices candidates et proxies est également terminée. Il ne
reste donc aucun lot de câblage obligatoire avant calibration ; toute future
extension d'une enveloppe candidate ou modification de topologie ouvrira une
nouvelle version de câblage plutôt qu'une correction silencieuse.

La **revalidation scientifique indépendante du précâblage est
`independently_validated`**. Elle conserve la portée historique de 26 objets :
7 boîtes, 7 groupes, 10 fils et 2 familles de
paramètres couvrant vision, proprioception, mécanoréception et sortie motrice.
Leurs implémentations et `integration_pass` restent des preuves d'exécution et de
cardinalité ; l'acceptation scientifique supplémentaire porte sur les enveloppes
topologiques bornées, jamais sur les valeurs physiologiques ou de transfert.

L'objectif courant est d'exécuter
[`target.population_dynamics_assignment.v0`](calibration/targets/population-dynamics-assignment-v0.yaml) :
la première chaîne locale est préréférencée et comptabilisée. Ses 46 neurones
canoniques sont tous couverts : 10 motoneurones T1 fléchisseurs du tibia exigent
une représentation événementielle sur preuve de type, tandis que 36 afférences
FeCO conservent les deux représentations admissibles. Leurs contrats de conversion
sont maintenant exécutables sans valeur implicite ni observation d'un comportement
nommé. Les plus petits sous-ensembles de sources sont désormais verrouillés et le
contrat source de l'observation calcium passe. La recette de fit tenue à l'écart
est désormais exécutée sur les tables biologiques exactes : sept chemins, 86/86
folds par animal, zéro blocage et zéro valeur promue. Une décision d'acceptation
distincte devra conserver ou rejeter des chemins sans prétendre que ce seul
résultat décide de la représentation native. Le pilote moteur reste opt-in et la
correspondance individuelle des body IDs reste un ensemble. Son diagnostic
temporel est lui aussi terminé : rapide soutenu dans cette cellule, intermédiaire
faiblement contraint et lent non identifié, sans promotion.
Le pont moteur aval est également terminé dans sa portée technique conditionnelle,
et les trois gains, les trois classes par body ID et toutes les routes candidates
sont désormais propagés ensemble par la première enveloppe locale, sans sélection
par trajectoire corporelle. Les 150 populations intermédiaires ont maintenant une
disposition exhaustive : deux exigences événementielles et 148 alternatives
`dual_unresolved`. Leur propagation tractable est maintenant exécutée sur le
panneau immuable de 120 tuples sans sélection ni promotion. Le prochain gate doit
remplacer les fixtures diagnostiques par les plus petites familles de paramètres
déclarées, sourcées ou techniquement bornées, tout en propageant les alternatives
non identifiées. La proximité topologique et le neurotransmetteur ne valent
toujours pas affectation de dynamique ni calibration.

Le précédent front
[`target.neural_model_class_gate.v0`](calibration/targets/neural-model-class-gate-v0.yaml)
est terminé. Son évaluation conclut `revise`, et
[`ADR 0016`](decisions/0016-event-capable-typed-hybrid-neural-runtime.md)
fixe le contrat `model.malecns_event_capable_typed_hybrid.v0`. Le runtime rate et
le LIF source-aligné restent deux comparateurs exécutables ; ni leurs paramètres,
ni une classe homogène ne sont promus.

Le protocole v0 et son résultat compact sont conservés dans
[`campaign.neural_model_class_lif_feasibility.v0`](calibration/campaigns/neural-model-class-lif-feasibility-v0.yaml)
et
[`runner_result.neural_model_class_lif_feasibility.v0`](calibration/runner/neural-model-class-lif-feasibility-v0.yaml).
Un audit de fidélité a toutefois montré que v0 copiait les constantes mais pas le
reset de `g`, le gel réfractaire de `v/g` ni l'intégrateur linéaire du code source
épinglé. Il reste un benchmark historique de ses propres sémantiques.

Le remplacement
[`campaign.neural_model_class_source_fidelity.v1`](calibration/campaigns/neural-model-class-source-fidelity-v1.yaml)
et son
[`résultat compact`](calibration/runner/neural-model-class-source-fidelity-v1.yaml)
épinglent le commit source `91bdd1e7dcf1`, ses hashes, le reset, le gel
réfractaire et la mise à jour linéaire couplée. La double référence NumPy/Torch
concorde exactement sur les états et les spikes
du graphe de test. Le balayage sortant visite 166 700 lignes, 25 582 938 arêtes et
124 177 617 contacts ; son CSR additionnel occupe 205 330 308 octets. Sur le GPU
RTX 4060 Laptop, les charges forcées de 1, 10 et 50 spikes/s/neuron réservent
environ 0,34 Go et mesurent environ 0,039 à 0,043 fois le temps réel. Le CPU mesure
environ 0,038 à 0,058 selon charge et répétition : le GPU
n'est donc pas encore exploité efficacement par ce noyau générique. Aucun spike
endogène n'apparaît dans cette charge volontairement faible ; la récurrence est
testée sur le petit graphe, pas présentée comme une activité MaleCNS calibrée.
La campagne directe
[`campaign.neural_model_class_brian2_conformance.v1`](calibration/campaigns/neural-model-class-brian2-conformance-v1.yaml)
a reproduit l'environnement historique Python 3.10 / Brian2 2.5.1 sans modifier
le venv principal. Elle a détecté puis corrigé deux erreurs d'ordonnancement :
livraison synaptique intégrée un pas trop tôt et fin de réfractarité un pas trop
tard. Le résultat concorde ensuite à `1.42e-14` mV près sur l'intégration, le
reset, la réfractarité et le délai de 1,8 ms. C'est une preuve d'implémentation,
pas une validation physiologique.

La campagne
[`campaign.neural_model_class_temporal_probes.v1`](calibration/campaigns/neural-model-class-temporal-probes-v1.yaml)
montre qu'à 5 ms le rate confond exactement des trains distincts par phase
intra-bin, ordre inter-canaux et délai sous-bin, alors que la trace événementielle
à 0,1 ms les distingue. Les deux comparateurs passent les contrôles bornés de
silence et finitude. Ce résultat établit une perte d'information, pas sa nécessité
biologique générale. Le pilote aBN1 complet-graph étant non discriminant entre
les représentations, le gate global se ferme par révision vers une architecture
typée plutôt que par un choix binaire artificiel.
Le détail et la décision de ne pas télécharger prématurément la morphologie sont
dans [`docs/neural-model-class-gate.md`](docs/neural-model-class-gate.md).

Le front indépendant d'actionnement est désormais fermé dans son scope borné :
[`target.actuator_semantics_gate.v0`](calibration/targets/actuator-semantics-gate-v0.yaml).
Il ne choisit aucun comportement ni gain moteur. Il fige et inventorie le contrat
bas niveau. La campagne
[`campaign.actuator_semantics_gate.v0`](calibration/campaigns/actuator-semantics-gate-v0.yaml)
a vérifié les 102 transmissions articulaires à gain unitaire, sans biais ni
dynamique interne, avec limite de force ±0,01. Chaque canal transmet exactement
la commande 0,005, sature comme déclaré et produit une réponse articulaire locale
non nulle. Le reset standard ne constitue pas une charge symétrique :
quatre pattes sur six sont en contact et quelques paires homologues montrent de
forts écarts. Une seconde campagne préenregistrée a montré, dans une fixture
tethered sans sol, un écart relatif maximal inférieur à `4.88e-5` sur 41 paires ;
les forts écarts au sol provenaient donc du contact ou de la configuration. Le
résultat local initial est dans
[`runner_result.actuator_semantics_gate.v0`](calibration/runner/actuator-semantics-gate-v0.yaml)
et le résultat causal final dans
[`runner_result.actuator_causal_attribution.v1`](calibration/runner/actuator-causal-attribution-v1.yaml).
Son interprétation est dans
[`docs/actuator-semantics-gate.md`](docs/actuator-semantics-gate.md). Ce gate
autorise le surrogate direct-motor gelé pour les premiers horizons courts ; il ne
valide ni transfert moteur, ni feedback MaleCNS, ni stabilité, ni comportement.

L'audit reproductible de transfert du circuit antennaire est enregistré dans
[`evidence.antennal_grooming_circuit_transferability.v0`](calibration/evidence/antennal-grooming-circuit-transferability-v0.yaml)
et son résultat compact dans
[`runner_result.antennal_grooming_circuit_transferability.v0`](calibration/runner/antennal-grooming-circuit-transferability-result-v0.yaml).
Il vérifie les hashes des sources, 146 JON nommés pour 147 annoncés, les types
croisés et le graphe MaleCNS complet. Il conclut `partial_mapping_abn2_unresolved`,
pas « référence acceptée ». Son utilisation future pour sélectionner un modèle
contaminerait le grooming antennaire ; les évaluations finales looming/optomotrice
et autres réponses latéralisées restent distinctes.

Le protocole étroit v1 reste l'historique du verrou anatomique, mais sa métrique
`spikes/s` n'était pas définie pour le candidat rate. Le protocole corrigé
[`evidence.antennal_abn1_model_class_reference.v2`](calibration/evidence/antennal-abn1-model-class-reference-v2.yaml)
compare donc uniquement les contrastes dans l'unité native de chaque candidat.
Il mesure directement aBN1 sous JO-CE
et JO-F et exclut explicitement aBN2, aDN, moteurs, corps et grooming. Le manque
`CB3129` ne bloque donc pas ce probe aBN1, mais continue de bloquer tout claim sur
le circuit de grooming complet. Fréquences, durée, répétitions, métriques et sens
qualitatif JO-CE > JO-F sont figés avant exécution ; aucun seuil numérique n'a été
inventé depuis une formulation qualitative. L'archive primaire des sorties est
un ZIP monolithique de 4 499 610 373 octets et n'a pas été téléchargée pour
fabriquer un seuil d'amplitude.

Le pilote v2 non décisionnel a maintenant exécuté le graphe complet : une graine,
20/120/220 Hz, le LIF source-aligné et trois membres sentinelles rate sous trois
ponts d'unité. L'événementiel donne respectivement 28, 167,5 et 230 spikes/s par
neurone aBN1 pour JO-CE, contre zéro pour JO-F. Les neuf séries rate ont également
JO-CE > JO-F aux trois fréquences. Ce résultat valide le chemin expérimental et
suggère que la référence aBN1 teste la capacité mais départage peu les classes ;
il ne sélectionne aucun modèle. L'extrapolation sans batching est d'environ
8,5 h GPU pour l'événementiel et 7,8 h pour les 31 membres rate × trois ponts,
soit 64 860 unités. Le résultat compact est
[`runner_result.neural_model_class_abn1.v2`](calibration/runner/neural-model-class-abn1-v2.yaml).
La campagne complète attend donc un exécuteur batché/reprenable et une décision
explicite sur sa valeur d'information, ou une seconde référence plus sensible au
temps.

Une prévalidation microscopique dédiée couvre désormais le chemin avant toute
nouvelle exécution longue. `neural_model_micro_tests.bat` regroupe 37 oracles sur
petits graphes : poids scientifique et provenance, multiplicité et signe,
chronologie délai/intégration, reset/réfractaire, événements consécutifs, état
frais et indépendance d'ordre, absence de mutation du CSR, parité CPU/GPU,
agrégation rate, liaison configuration réelle→graphe minimal, conformité Brian2,
pertes temporelles rate/event, processus source de Poisson et conversion
Hz→gradué. Ce jalon ferme une faiblesse de vérification du
code ; il ne ferme pas le gate scientifique de classe de modèle.

Le premier jalon de cette infrastructure est franchi. Le registre
[`calibration/parameter_families/`](calibration/parameter_families/) inventorie
22 familles : six sources basales, quatre routages, sept transferts — dont les
deux ponts basaux event et Hz→gradué et le pont interne event↔graded —, trois
familles de dynamique centrale, la mécanique FlyBody conservée comme dépendance
externe gelée et l'enveloppe numérique motrice isolée comme nuisance technique.
Le [`DAG`](calibration/dependency-dag.yaml) contient vingt-et-une dépendances et est validé
acyclique. Les dimensions maximales exécutables sont séparées des degrés de
liberté scientifiques encore à choisir. Le couplage historique entre routage et
gain en proprioception, mécanoréception et sortie motrice est désormais résolu à
la frontière runtime par `compiler.peripheral_routing_transfer.v0`. Il impose des
simplexes de routage explicites, des affectations de partage explicites et les
hashes des enveloppes acceptées ; il ne choisit ni route, ni gain, ni valeur.
Les 3 746 routes motrices logiques sont notamment distinguées de leurs 7 849
coefficients runtime développés.

Le runner autonome minimal est maintenant validé. Il refuse les entrées dont le
hash a dérivé, vérifie les frontières topologiques de chaque famille, interdit aux
modes fitting/validation d'accéder aux scénarios held-out et n'exécute que des
évaluateurs enregistrés dans le code. Chaque essai est conservé comme `accepted`,
`rejected`, `error` ou `skipped_budget_exhausted`; les répétitions sont comparées
par hash sémantique et aucun essai planifié ne peut disparaître du décompte.

Le run `20261002T113512989298Z--runner-validation-peripheral-parameter-compiler-v0`
a exécuté deux fois chacun des trois contrats périphériques : **6/6 essais
acceptés, zéro rejet, zéro erreur et zéro cas non déterministe**. Son hash
sémantique est `1efcfd166625598d7f259e24dad4d948ee546dcff4dce3d709defa88f6e8d34a`.
Ce run utilise des simplexes uniformes et gains unitaires éphémères ; il valide
l'infrastructure seulement et n'accepte aucune valeur de mouche. Il a été produit
depuis le commit `f90f052` avec un worktree propre. Le contrat est
documenté dans [`docs/calibration-runner.md`](docs/calibration-runner.md).

Le premier nœud de preuve du DAG est également franchi. La recette
[`evidence.transmitter_sign_prior.v0`](calibration/evidence/transmitter-sign-prior-v0.yaml)
reconstruit une ligne pour chacun des 166 700 neurones canoniques à partir des
trois sources MaleCNS v1.0 hashées. Elle trouve 166 522 enregistrements de
neurotransmetteur et conserve 178 absences explicites. Le parameter set
[`parameters.central_transmitter_sign_prior.v0`](calibration/parameter_sets/central-transmitter-sign-prior-v0.yaml)
est gelé comme dépendance de preuve, pas comme dynamique calibrée.

Le prior attribue une classe excitatrice aux 103 720 neurones cholinergiques et
une classe inhibitrice aux 22 069 neurones GABAergiques. Glutamate, histamine,
monoamines, consensus `unclear` et absences restent contextuels ou inconnus. À
l'échelle du graphe, 14 745 137 arêtes ont un prior excitateur, 4 925 557 un
prior inhibiteur et **5 912 244 restent inconnues ou dépendantes du contexte**.
Le code numérique zéro encode cette absence d'affirmation ; il ne supprime jamais
une synapse. Deux exécutions propres ont reproduit le hash sémantique
`fb3777b99eb913b41a86962cae33b8bf41a96bc0c26c25ca68ce34229a7a44da`.

Le candidat [`model.malecns_typed_signed_rate.v0`](calibration/models/malecns-typed-signed-rate-v0.yaml)
rend maintenant ce prior exécutable sans créer 25,6 millions de poids libres. Il
expose neuf efficacités partagées par classe de neurotransmetteur et trois
paramètres globaux de dynamique. Les signes acétylcholine/GABA sont contraints par
le prior gelé ; les sept classes contextuelles, `unclear` ou `missing` conservent
chacune un paramètre signé explicite. Aucun résidu par arête n'est autorisé en v0.

Le run propre
`20261003T082053529120Z--runner-validation-signed-dynamics-contract-v0` a parcouru
deux fois les **25 582 938 arêtes** : 25 582 938/25 582 938 sont assignées, les
5 912 244 arêtes inconnues/contextuelles sont exercées avec un probe non nul,
zéro arête est supprimée et le hash sémantique répété est
`c45acd00346e5ee4bdd1f93686dbcb286be385187dac1ce056e809bf852a6789`.
Cette preuve accepte la représentation sparse et la comptabilité seulement. Les
valeurs du probe, l'équation comme modèle biologique, la stabilité et tout
comportement restent explicitement non acceptés.

Le run diagnostique propre
`20261003T090226460183Z--campaign-diagnostic-central-unfitted-characterization-v0`
a ensuite exécuté sept régimes non ajustés pendant 200 ms chacun sur le graphe
complet. Une seconde exécution propre reproduit le hash sémantique
`351e883439080618af35a1e685efcd54058e8bd1f88cf206f6210d5863f41ace`.
Le régime faible sans entrée s'éteint, les régimes intermédiaires récupèrent
après la petite perturbation, tandis que le régime fort conserve un gain de
perturbation de 3,988 et atteint 96,5 % de neurones numériquement actifs. Ces
observations montrent que le banc distingue plusieurs modes, pas que l'un d'eux
est acceptable. Aucun probe, seuil ou paramètre n'est promu.

La première véritable campagne de fitting technique est maintenant exécutée et
reproductible. `campaign.technical_neural_dynamics_pilot.v0` reconstruit 32
candidats Sobol sur les douze paramètres partagés, puis soumet chacun à trois
scénarios train et deux scénarios de validation locale distincts des probes
diagnostiques. Les deux runs propres
`20261003T132548498439Z--campaign-technical-neural-dynamics-pilot-v0` et
`20261003T132656622969Z--campaign-technical-neural-dynamics-pilot-v0` reproduisent
le hash sémantique
`68b0166693c21734d0cf2c7dc195e2377e156a21c2ee96aa30ec89512289a8ff`.

Les **32/32 candidats passent** : zéro saturation numérique, gain de perturbation
maximal entre 0,633 et 0,937, résidu final maximal entre 5,85e-7 et 0,170 et
demi-récupération stable en 2 à 11 pas. Ce résultat valide une large admissibilité
technique sur les cinq scénarios mais révèle surtout une non-identifiabilité : les
critères ne distinguent aucun vecteur de référence. L'ensemble reconstructible est
conservé, sans sélection post hoc, sans gel et sans claim physiologique.

L'étude diagnostique préenregistrée
`diagnostic.central_ensemble_motor_sensitivity.v0` a ensuite comparé les 32
membres sur trois motifs synthétiques, chaque stimulus étant soustrait à un sham
partant du même état initial. Elle observe exhaustivement 96 réponses aux 815
terminaux moteurs MaleCNS bruts, sans traverser le transfert moteur, les
actionneurs, le corps ou le monde. Les runs propres
`20261003T143327383160Z--campaign-diagnostic-central-ensemble-motor-sensitivity-v0`
et
`20261003T143423135154Z--campaign-diagnostic-central-ensemble-motor-sensitivity-v0`
reproduisent le hash sémantique
`c7dc9aa65e1bc3d030b32e4e97474d3ca9f7fb523290fc2962b12308c386917e`.

Le résultat est **hautement sensible**, pas identifiant : la distance cosinus P90
entre motifs candidats atteint 1,124 et le rapport d'amplitudes P90/P10 atteint
17,596 ; aucune des 96 réponses n'est numériquement nulle. Un candidat arbitraire
changerait donc matériellement la suite. L'étude ne classe aucun membre et ne
fournit aucune vérité biologique ; elle impose d'ajouter une contrainte centrale
non comportementale indépendante ou de propager l'ensemble complet.

La première contrainte indépendante est désormais exécutée. Le protocole
`constraint.central_timestep_convergence.v1` compare, pendant la même durée de
400 ms, les réponses stimulus-moins-sham du CNS complet intégrées à 5,0, 2,5 et
1,25 ms. Il contrôle séparément les 166 700 neurones canoniques et les 815 sorties
motrices brutes, sans transfert moteur, corps, monde, rendu ni comportement. Les
deux runs propres
`20261003T185726564390Z--campaign-central-timestep-convergence-v1` et
`20261003T190037078175Z--campaign-central-timestep-convergence-v1` reproduisent le
hash sémantique
`12667c186699cdb3cbdbbd4f275a2522f4c0ebd8fe3675e872dc214057db6062`.

Les **31/32 candidats passent**. Le candidat 30 est rejeté car son erreur relative
L2 sur l'état central complet atteint 0,286 à 5 ms (limite 0,15) et 0,116 à
2,5 ms (limite 0,075). Aucun survivant n'est classé ou choisi. La v0, conservée
comme résultat méthodologique supersédé, avait aussi révélé neuf inversions
d'ordre sous 1e-4 dues aux réductions sparse CUDA ; la v1 a préenregistré ce
plancher numérique sans modifier les seuils matériels. Le nouvel ensemble est
donc plus portable numériquement, pas plus physiologique ni comportemental.

L'[`ADR 0013`](decisions/0013-ensemble-propagation-and-model-adequacy.md)
formalise la conservation de l'incertitude et interdit de choisir arbitrairement
un des 31 membres. L'[`ADR 0014`](decisions/0014-neural-dynamics-fidelity-gate.md)
ajoute un gate plus amont : ces membres appartiennent tous à la même classe rate
non validée et ne seront donc pas propagés scientifiquement avant la comparaison
rate-versus-événements. Ils restent disponibles comme ensemble d'ingénierie. Si
la classe rate franchit le gate dans un scope déclaré, les règles de propagation
d'ensemble de l'ADR 0013 s'appliqueront alors sans exiger de singleton.

Un catalogue prospectif de sept observations comportementales est maintenant
consigné dans
[`docs/prospective-emergent-behavior-evaluations.md`](docs/prospective-emergent-behavior-evaluations.md)
et dans son
[`registre YAML`](calibration/evaluation_candidates/emergent-behavior-catalog-v0.yaml) :
grooming localisé et hiérarchique, looming, latéralisation, réponse optomotrice
simple et temporelle, et motifs spontanés structurés. Ce ne sont ni des cibles
d'entraînement, ni des protocoles verrouillés, ni des résultats. Aucun scénario,
seed ou seuil n'est ouvert. Chaque futur protocole devra comparer sham, MaleCNS
gelé et plusieurs contrôles topologiques, dont des rewires à paramètres gelés et
des rewires soumis à la même calibration non comportementale.

Le compilateur
[`evidence.basal_source_readiness.v0`](calibration/evidence/basal-source-readiness-v0.yaml)
ouvre le premier front local sans comportement. Il vérifie les hashes des quatre
tables structurelles et attribue exactement une disposition de preuve aux 329
canaux basaux connus et aux 1 883 sources résiduelles. Les annotations produisent
54 partitions olfactives, 66 gustatives, 8 thermo-hygrosensorielles et 83
partitions résiduelles d'audit. Sur les canaux connus, 286 ont un support
qualitatif de partition et 31 canaux labellaires disposent de mesures numériques
partielles qui ne sont pas encore reliées à leur identité fonctionnelle MaleCNS.

Deux compilations déterministes reproduisent le hash sémantique
`c2db66b99ad9d8d93dca343c10e4ae389d5df995d9125dd4c4fb2eb17d548f96`.
Elles acceptent l'exhaustivité et la provenance, mais **zéro valeur** : aucune des
six familles n'est ajustée ou gelée. Le blocage visible est un contrat d'unités :
les sources biologiques donnent des spikes/s, tandis que le runtime v0 divise le
vecteur sensoriel complet par son maximum absolu avant le gain central. Le gate
ADR 0014 interdit désormais de construire ce pont avant d'avoir choisi la classe
de dynamique ; un modèle à spikes pourrait consommer ces taux comme intensités
d'un processus événementiel déclaré. Les 1 883 sources résiduelles restent
explicitement sans valeur biologique transférable.

La méthode de revue est fixée par
[`ADR 0008`](decisions/0008-independent-scientific-wiring-reaudit.md) et
[`validation.scientific_wiring_reaudit`](ledger/validations/scientific-wiring-reaudit.yaml).
Chaque secteur doit être reconstruit depuis les données brutes versionnées et les
sources primaires sans prendre le manifeste courant comme recette, puis comparé
relation par relation. Aucun paramètre scientifique n'est accepté par cette
clôture. Les futures campagnes peuvent désormais prendre les hashes acceptés comme
frontière topologique gelée, selon le contrat de calibration séparé.

Le ruleset `wiring-revalidation.rules.v1` et son runner constituent le premier
palier reproductible de cette revue. Le run
`wiring-revalidation-20260927T183911Z` a reconstruit depuis les sources brutes
12 658 terminaux uniques et 7 124 groupes, puis comparé leurs appartenances et
dispositions au précâblage : aucune différence et aucune exception inattendue ne
subsistent. Le supplément officiel a aussi reproduit exactement les 2 628
relations R7/R8 `bodyId`→colonne optique. Cette passe ne régénère pas encore les
familles de matrices candidates fines. La sortie motrice, la mécanoréception, la
proprioception et la vision disposent maintenant de clean builders acceptés ;
aucune famille fine ne reste bloquée. La portée et les commandes sont documentées dans
[`docs/wiring-revalidation.md`](docs/wiring-revalidation.md).

Le run global `wiring-revalidation-20260928T205213Z` a reconstruit les 815
terminaux moteurs et 441 groupes dans une destination vide, puis produit 3 746
relations groupe→actionneur, soit 7 849 relations terminal→actionneur. Le hash
sémantique `0cd753e02283e42f3bf963e3fe223b7728b1a343da5b2db78e6414d4de8c5ca3`
a été reproduit par un second clean build. Après seulement, la matrice exécutable
a été ouverte : ses 7 849 relations sont toutes confirmées, sans ajout, retrait
ni doublon. Les contraintes négatives de côté et d'appendice, la capacité miroir
et la couverture des 102 actionneurs passent ; les 10 groupes non représentés
restent des `sink`. Cette validation accepte l'enveloppe topologique candidate,
pas une correspondance muscle biologique exacte et aucun des 7 849 gains.

Le run global `wiring-revalidation-20260929T140029Z` a ensuite reconstruit les
4 291 terminaux mécanorécepteurs et leurs 323 groupes sans ouvrir la matrice
exécutable. Les règles utilisent seulement les annotations MaleCNS, les drapeaux
canoniques et les inventaires physiques FlyBody : sept observables de charge par
patte, positions/vitesses des appendices du même côté et trois composantes de
force grossière pour la tête ou le thorax. Elles produisent 2 108 relations
groupe→observable, soit 28 514 relations terminal→observable. Le hash sémantique
`70e71d9a5c36edcc8ce5f01e367c7a5349f8d1942ea3b1a72e0e0a9868cc9fd2`
a été reproduit par un second clean build. Après seulement, le précâblage a été
ouvert : toutes les relations sont confirmées, sans ajout, retrait ni doublon.
Les contraintes de côté, position de patte, appendice et segment, ainsi que les
capacités de 131 clés miroir, passent sans exception. Cette validation accepte
l'enveloppe candidate locale, pas la physiologie récepteur→signal et aucun des
28 514 coefficients de transfert.

Le run global `wiring-revalidation-20260929T144947Z` a ensuite reconstruit les
1 454 terminaux proprioceptifs et leurs 262 groupes depuis les annotations, les
drapeaux canoniques et le seul inventaire articulaire FlyBody. Les règles
produisent 1 439 arêtes candidates directes pour 171 groupes et 553 arêtes proxy
pour 91 groupes, soit 1 992 relations groupe→observable et 10 518 relations
terminal→observable. Le hash sémantique
`782b98d147b5ecd15861dca0241d7fabf2995b1b9b6ef5b9c50d8e94ea5dd665`
a été reproduit dans une deuxième destination vide avant ouverture du
précâblage. Les 10 518 relations existantes sont toutes confirmées sans ajout,
retrait, doublon ni exception ; les contraintes de côté, appendice, spécialisation
FeCO, partition direct/proxy et capacité miroir passent. Cette acceptation porte
sur l'enveloppe structurelle locale. Les proxies de déformation/vibration et les
10 518 paramètres continus restent non calibrés.

Le run global `wiring-revalidation-20260929T182220Z` clôt la vision et la revue
globale. Il reconstruit 6 098 terminaux visuels et 4 802 unités d'enregistrement :
1 332 colonnes publiées contenant 2 628 R7/R8, 3 463 photorécepteurs sans colonne
et 7 HBeyelet proxy. Une représentation normalisée de six ensembles de sources
compte exhaustivement 3 091 576 relations candidates, soit 3 665 347 relations
terminal→observable développées. Le hash
`130b45c285aa86f97886648a607de29617422e9c8c94aed51be711ae5a836152`
a été reproduit avant ouverture du précâblage ; les 6 098 décisions terminales et
4 802 enveloppes existantes correspondent exactement. Les contraintes de côté,
palette, injectivité des colonnes et séparation HBeyelet passent sans exception.
Les 4 795 enregistrements discrets, 6 098 gains et dynamiques visuelles restent
non calibrés.

Le projet adopte désormais une politique d'**automatisation proportionnée par
règles avec rapports d'exception**. Les travaux répétitifs doivent, lorsque c'est
rentable, être exprimés comme des règles versionnées appliquées hors quota ; chaque
exécution comptabilise ce qui a été traité, exclu, bloqué ou surpris, puis produit
les cas ambigus pour une décision compacte. Cette préférence ne justifie pas une
infrastructure plus coûteuse que le traitement direct des rares cas restants. Le
contrat est dans [`docs/rules-first-automation.md`](docs/rules-first-automation.md)
et l'[`ADR 0009`](decisions/0009-proportional-rules-first-automation.md).

L'[`ADR 0011`](decisions/0011-reconstructible-peripheral-topology.md) fixe le
jalon de sortie de cette revalidation : sources immuables, règles versionnées et
petite table d'exceptions doivent reconstruire chaque famille dans une destination
vide avec le même hash sémantique. Les matrices générées sont des caches. Les
espaces candidats doivent rester locaux et leur capacité être quantifiée ; les
paramètres discrets de routage sont séparés des paramètres continus de fonction de
transfert. Les tests doivent inclure contraintes négatives, symétries/topographies
pertinentes et gold standards masqués non circulaires lorsqu'ils existent.

Le **banc d'exécution du vrai graphe MaleCNS est maintenant implémenté et mesuré**.
Il transforme les 25 582 938 arêtes canoniques en CSR float32, compare chaque run
GPU à une référence CPU déterministe et compile les boîtes déclarées en un vecteur
de 17 884 entrées et un décodeur de 815 sorties motrices vers 102 commandes. Le
profil temporel `benchmark.malecns.leaky_tanh.v0` est explicitement
`BENCHMARK ONLY / UNCALIBRATED` : sa normalisation, sa fuite et ses paramètres
aléatoires déterministes sont des choix d'ingénierie et aucunement une dynamique
biologique acceptée.

Le run `benchmark-20260927T081439Z`, produit depuis le commit moteur `ba7e9f4`, a
simulé 5,0 secondes du graphe complet en 2,077 secondes de noyau sur la RTX 4060
Laptop : **481,4 pas/s**, soit **2,407 fois le temps réel** au pas arbitraire de
5 ms. Le CSR occupe 195,8 Mio, le pic alloué
sur le GPU 210,2 Mio et l'accord CPU/GPU présente une erreur absolue maximale de
1,49e-08 après trois pas. La trace compacte des 102 commandes, six métriques et
256 sondes neuronales occupe 1,22 Mio. Ces mesures démontrent la faisabilité
d'exécution, pas la validité du comportement produit.

Le contrat de ce banc est dans
[`docs/runtime-execution-benchmark.md`](docs/runtime-execution-benchmark.md). Le
benchmark ne remplace aucune preuve de câblage scientifique et ne constitue pas
une calibration.

La **boucle incarnée réelle est maintenant exécutable et enregistrable**. À
chaque pas de 5 ms, elle lit la vision FlyBody, les contacts et la proprioception,
traverse toutes les boîtes d'entrée, avance le vrai graphe MaleCNS sur CUDA,
décode ses 815 sorties motrices, applique 102 commandes protégées par une enveloppe
numérique explicitement non physiologique, puis exécute 50 sous-pas MuJoCo natifs.
Il n'existe aucun contrôleur comportemental externe dans ce chemin.

Le run `closed-loop-20260927T124854Z`, produit depuis le commit moteur `add05df`,
a calculé **une seconde fermée complète** : 200 pas neuronaux, 10 000 pas MuJoCo
et une nouvelle acquisition visuelle à chaque pas neuronal. Il a pris 16,854 s,
soit 0,0593 fois le temps réel. Les capteurs et interfaces ont pris 8,079 s,
MaleCNS 2,799 s et la physique 2,072 s. La trajectoire autonome de 200 trames
occupe 971 225 octets et son rejeu contre une instance FlyBody neuve a passé le
contrat de modèle.

Le format `the_fly_matrix.physical_trajectory` conserve `qpos`, `qvel`, commandes,
forces, observations articulaires, contacts, rétine, résumés neuronaux et
provenance. Le player ne dépend pas du contrôleur producteur. Les modes headless,
live et replay partagent la même construction FlyBody et le même shell de viewer.
L'architecture est actée dans l'[`ADR 0010`](decisions/0010-controller-independent-physical-trajectories.md)
et documentée dans [`docs/embodied-runtime.md`](docs/embodied-runtime.md).

Cette validation est uniquement une preuve d'intégration. La règle neuronale,
les paramètres d'interface et le garde-fou moteur restent non calibrés. Le front
d'ingénierie suivant consiste à inventorier les familles et leurs dépendances,
puis à préparer l'injection de jeux de paramètres versionnés dans cette unique
boucle. L'inspection du replay et le profilage de la vision restent des outils du
baseline et du futur runner, pas un substitut à cet inventaire.

Un viewer physique temps réel est maintenant disponible via
`diagnostic_viewer.bat`. Il utilise un faux CNS récurrent de 64 états, déterministe
par seed, qui lit les 102 positions/vitesses articulaires et commande les 102
adresses FlyBody. Il contourne explicitement MaleCNS et la transduction motrice,
affiche en permanence `NOT MALECNS / NOT CALIBRATION` et ne modifie aucun statut
scientifique. Son profil interactif utilise un pas diagnostique de 0,5 ms, un
contrôleur à 100 Hz et un rendu à 30 FPS ; le pas physique natif de 0,1 ms reste
accessible par option. La séparation est actée dans
[`ADR 0006`](decisions/0006-isolated-physical-viewer-diagnostic.md).

Une analyse structurelle de la récurrence du vrai MaleCNS est disponible via
`cycle_topology.bat`. L'analyse corrigée conserve les 211 577 corps annotés dans
un registre par corps, mais calcule le graphe neuronal sur les 166 700 corps
canoniques seulement. Elle marque séparément l'accessibilité depuis les 17 884
entrées et la capacité à atteindre les 815 sorties motrices. Les quatre classes
obtenues sont 165 494 neurones du cœur causal entrée→sortie, 1 126 accessibles
sans conséquence sur les sorties motrices modélisées, 9 capables d'atteindre une
sortie sans être accessibles depuis les entrées déclarées et 71 dans aucun des
deux ensembles. Ces étiquettes décrivent le périmètre actuel ; elles ne déclarent
pas les neurones biologiquement inutiles.

Les composantes fortement connexes sont exactes. En revanche, la profondeur BFS
multi-source est comprimée et ne mesure ni une profondeur biologique ni la taille
réelle des cycles ; l'ancienne lecture « retours surtout locaux » est retirée.
La méthode et les limites sont décrites dans
[`docs/connectome-cycle-topology.md`](docs/connectome-cycle-topology.md).

La prochaine analyse topologique ne cherchera pas à assimiler les SCC à des
modules. Elle testera une hypothèse de **modularité hiérarchique quasi
feed-forward** : chaque module doit admettre un ordre interne majoritairement
feed-forward avec des skips et retours surtout locaux, tandis que le graphe dirigé
des modules conserve ses arêtes et peut former des cycles macroscopiques longs.
Cette hypothèse doit pouvoir être rejetée si aucune partition stable ne l'explique.

La définition normative est désormais celle de
[`ADR 0002`](decisions/0002-exhaustive-terminal-coverage.md) : chaque canal doit
avoir une disposition `exact`, `parameterized`, `basal`, `proxy`, `sink` ou
`blocked`. Une boîte noire locale paramétrable termine valablement un câblage même
si sa correspondance interne est inconnue. En revanche, une activité fournie
directement par le smoke test à la place d'une boîte reste `blocked`.
Le score historique du registre mesure aussi la maturité des décompositions et des
routes. Il ne doit donc pas être confondu avec la couverture terminale : celle-ci
est désormais exhaustive dans la carte, sans canal d'entrée ni groupe moteur
`blocked`, alors que l'indicateur global reste inférieur à 100 %.

La première carte interactive exhaustive est désormais implémentée. Elle exporte
depuis les manifestes locaux 31 041 nœuds et 55 198 relations : 1 552 observables
physiques, 8 895 boîtes d'entrée, 17 884 entrées CNS, 815 sorties CNS, 441 groupes
moteurs et 102 actionneurs. Les terminaux bloqués restent visibles au lieu d'être
filtrés. Après le présent lot, elle compte 2 212 entrées `basal`, 6 585
`parameterized`, 98 `proxy` et aucune entrée `blocked`. Côté sortie, 431 groupes
sont `parameterized` et les 10 groupes sans effecteur représenté sont explicitement
`sink`, pas `blocked`. La carte offre zoom/panoramique, focus sectoriel sans retrait de topologie,
recherche et panneau de traçabilité. Elle ne contient aucune valeur de calibration.
L'architecture, les invariants visuels et le contrat de traçabilité sont actés en anglais dans
[`ADR 0003`](decisions/0003-interactive-wiring-map.md).

## État synthétique

- Maturité historique du câblage : **81 %**.
- Graphe central MaleCNS : **100 % structurel**.
- Sortie motrice : **79 %** historique ; topologie candidate indépendamment validée, gains inconnus.
- Proprioception : **81 %** historique ; topologie candidate indépendamment validée, paramètres inconnus.
- Entrées sensorielles non résolues : **96 %**.
- Clamps basaux : **87 %**.
- Vision : **79 %** historique ; topologie candidate indépendamment validée, enregistrements et gains inconnus.
- Mécanosensation : **74 %** historique ; topologie candidate indépendamment validée, coefficients inconnus.
- Corps physique : **100 %**.
- Monde physique : **100 %**.
- Évaluation/fermeture de boucle : **20 %**.
- Couverture terminale de la carte : **100 % sans disposition `blocked`**.
- Revalidation scientifique : **`independently_validated` ; 4/4 familles fines, zéro exception et zéro famille bloquée**.
- Calibration : **inventaire de 22 familles et DAG de 21 dépendances validés ; le gate global rate/LIF est fermé avec `revise` vers une architecture event-capable typée/hybride ; 12 neurones sont `event_required` et 166 419 restent `dual_unresolved` dans la portée basale ; les ponts basaux externes et les quatre directions internes s'exécutent, mais la conversion interne event↔graded est désormais une famille distincte non ajustée et toutes les constantes restent des fixtures ; le couplage source×efficacité×conversion×seuil et l'ablation à ~89 % de la famille inconnue sont des risques prioritaires ; côté moteur, 58 025 affectations lentes restent bloquées ; zéro valeur individuelle ou affectation physiologique est promue et la stabilité du corps entier reste non calibrée**.
- Évaluations émergentes : **7 candidats prospectifs documentés ; zéro protocole verrouillé, zéro comportement observé et zéro résultat exposé à la calibration**.
- Attribution incarnée : **gate ADR 0015 fermé comme surrogate borné : 102 actionneurs directs `MOTOR`, zéro servo, rejeu ouvert exact, séparation passif/ouvert/fermé et symétrie tethered ; feedback non calibré actuellement presque nul, aucune fidélité musculaire ni stabilité validée**.
- Mesure de stabilité incarnée : **contrat court-horizon v1 complet (COM réel, 102 limites, jerk physique, 6 contacts/forces, proxy de travail déclaré, récupération appariée et masques) ; zéro seuil choisi et stabilité toujours non calibrée**.

Le lot structurel correspondant a supprimé la dernière injection directe d'entrée. Les 1 883
afférences sensorielles résiduelles conservent leurs routes `bodyId` exactes et sont
désormais possédées par trois sources nominales type A disjointes : 57 canaux
`chemosensory`, 11 `mechanosensory_tbc` et 1 815 canaux de modalité inconnue. Chaque
canal a un paramètre explicite non calibré. Cette disposition `basal` est un joker
structurel réversible, sans attribution de capteur physique ni valeur
physiologique. Le smoke test traverse ces trois boîtes avant le routeur et atteste
qu'aucun vecteur terminal n'est injecté directement. La politique est actée dans
[`ADR 0004`](decisions/0004-residual-sensory-nominal-sources.md).

La carte corrige en parallèle la disposition des 10 groupes moteurs sans effecteur
FlyBody : les 11 neurones concernés sont des terminaux `sink` explicites, conformément
au runtime qui consomme leur activité sans produire de commande. Il ne reste donc
aucun terminal `blocked` dans les interfaces cartographiées. Cela ne signifie pas
que les paramètres ou les comportements sont calibrés.

Le dernier lot supprime l'injection directe des 91 groupes proprioceptifs qui
attendaient une mesure de contrainte ou de vibration. Les 171 groupes déjà reliés
au corps conservent leurs 1 439 arêtes candidates `parameterized`. Les 91 autres,
couvrant 468 neurones, traversent désormais 553 arêtes `proxy` limitées aux
cinématiques du même appendice et du même côté lorsque l'annotation le permet.
L'unique groupe sans nerf ni côté connus ne voit que cinq articulations centrales
thorax–tête/abdomen. Les 262/262 groupes sont exécutables sans vecteur terminal de
secours et aucun coefficient n'est fixé.

Le score global historique était resté à 86 %. Le score proprioceptif passe de 86 à
85 % parce que le nouveau fil proxy est honnêtement enregistré au palier
`candidates_known`, ce qui augmente le dénominateur de cet ancien indicateur. Il
ne s'agit pas d'une régression du réseau : les canaux `blocked` proprioceptifs
passent de 91 à zéro. Les 1 883 afférences résiduelles sont maintenant terminées
par les sources nominales décrites ci-dessus, sans modifier ce lot proprioceptif.

Le dernier lot élimine toute injection directe dans les 6 098 terminaux visuels.
Les 2 628 R7/R8 présents dans le supplément officiel conservent leur colonne
biologique exacte et un enregistrement colonne→ommatidie externe. Les 3 463 autres
photorécepteurs possèdent chacun un choix discret parmi les 721 ommatidies du même
œil et un gain libre. Les 7 HBeyelet, absents du capteur FlyBody, utilisent un proxy
explicitement déclaré : la moyenne lumineuse de l'œil indiqué par leur instance,
avec un gain libre. Le smoke test calcule désormais les 6 098 activités depuis le
rendu MuJoCo et les paramètres de boîte; il n'accepte plus de vecteur terminal de
secours. Aucun choix rétinotopique ni gain scientifique n'a été persisté.

Le score visuel passe de 86 à 89 % et le score global de 85 à 86 %. La différence
restante dans ce secteur mesure surtout la résolution et la validation à affiner,
pas un fil pendant : la disposition terminale visuelle est exhaustive.

Le dernier lot ferme l'exécution physique après la sortie motrice. Le runtime
construit un FlyBody articulé dans MuJoCo, vérifie l'ordre des 102 actionneurs,
applique réellement les commandes pendant 20 pas, puis relit les 102 positions et
vitesses par l'interface proprioceptive. Le rejeu depuis le même état est identique
bit à bit et diffère du témoin passif. Une enveloppe numérique propre au smoke test
protège MuJoCo des paramètres arbitraires; elle n'est pas une calibration. Le
secteur corps physique était alors passé de 94 à 100 %. Le score global restait arrondi à 85 %,
mais son composant de routage des fils passe de 69 à 70 %.

Le lot d'interface n'avait pas modifié ce score. `wiring_map.bat` compile l'application
React/Cytoscape, régénère `reports/generated/wiring-map/wiring-map.json`, démarre
un serveur HTTP strictement local et ouvre la vue. La disposition fixe les colonnes
monde/corps → modèles source → adaptateurs → entrées CNS → MaleCNS → sorties CNS
→ groupes moteurs → actionneurs afin que deux générations restent comparables.

Le smoke test traverse toujours 17 884 entrées CNS et 815 sorties motrices, toutes
canoniques, mais le runtime central est maintenant limité aux 25 582 938 arêtes
entre les 166 700 neurones canoniques. Les 211 577 lignes d'annotation restent
conservées et classifiées. Les tests découverts actuellement passent, y compris les
garde-fous du runner, les tests de compilation, le runtime et les validations
structurelles.

## Statut structurel

Le câblage structurel v0 est terminé : couverture terminale 100 %, quatre familles
fines sur quatre indépendamment validées, aucune exception inattendue et aucune
famille bloquée. Aucun travail structurel n'est requis pour ouvrir la calibration.
Les raffinements futurs restent possibles, mais deviennent de nouvelles versions
topologiques et invalident explicitement les campagnes qui dépendaient des hashes
précédents.

## Front de calibration

**Ouvert.** Le gate global de classe neuronale est fermé avec `revise`. Il interdit
un défaut homogène rate ou LIF et accepte le contrat event-capable typé/hybride de
l'ADR 0016. Le front actif affecte maintenant les dynamiques à des populations
bornées dans une chaîne sensorielle et une chaîne motrice locales. Zéro
constante n'est encore promue. La portée locale complète couvre exactement 196
neurones : l'exigence événementielle de 10 motoneurones T1 fléchisseurs et de deux
intermédiaires tibia-extenseurs est acceptée, tandis que les 36 afférences FeCO et
148 autres intermédiaires restent `dual_unresolved`. Les 31
survivants rate et le LIF source-aligné restent des comparateurs, et la suffisance
des douze paramètres partagés demeure un risque ouvert.

Le front ne consiste donc plus à construire une nouvelle mécanique globale. Il
doit fermer ou propager quatre incertitudes concentrées : le propriétaire et les
bornes de la conversion interne event↔graded, le couplage non identifiable entre
sources basales/efficacité/seuils, le cône causal réellement requis parmi les
166 419 affectations inconnues, et la dépendance motrice lente/bodyId. L'ADR 0017
interdit de traiter les échelles diagnostiques comme des valeurs par défaut et de
geler indépendamment un descendant qui en dépend matériellement.

Le premier audit local est terminé sans choisir de valeur : les partitions de
preuve basales sont exhaustives et les limites des publications sont enregistrées.
Le transfert numérique vise maintenant des frontières typées explicites ; aucun
pont global n'est inventé. `local_conversion_contract.bat` exerce les sorties FeCO
graduée et événementielle sans en choisir une, puis conserve deux étapes motrices
distinctes : événements→force biologique et force→commande MuJoCo. Les tests
contrôlent unités, formes, causalité, superposition, symétrie de fixture, seed et
hashes topologiques. Le dépôt FeCO inspecté ne contient que les scripts d'analyse.
Le manifeste minimal et la campagne tenue à l'écart sont maintenant préenregistrés ;
les trois tables sont localement vérifiées et le fit biologique est complet sous
forme d'ensemble candidat non promu (86/86 folds, zéro bloqué). Les données
motrices brutes représentent environ 48,76 Go ; le pilote opt-in de 860 Mo est
maintenant acquis, hash-vérifié et inventorié sans extraction. Le port des scripts
historiques a normalisé ses 194 essais en 22 lignes agrégées et les trois fits
diagnostiques sont terminés sans promotion. La correspondance
fast/intermediate/slow des 10 body IDs reste un ensemble non résolu : chaque corps
conserve trois classes candidates, soit une borne supérieure factorisée de 59 049
affectations jointes, sans probabilité, symétrie ou cardinalité de classe inventée.

1. Inventorier les familles de paramètres : rôle, type, dimension, unités,
   partage, origine, données autorisées, identifiabilité et incertitude.
2. Construire leur DAG de dépendances et geler pour chaque campagne les hashes de
   topologie, règles et exceptions issus du câblage accepté.
3. Compiler les transferts de preuves, statistiques basales et priors de
   neurotransmetteurs/signes avec confiance et masques inconnus.
4. Séparer les paramètres logiques de routage/transfert des vecteurs runtime et
   verrouiller leurs enveloppes candidates sans choisir de valeur.
5. Construire le runner autonome minimal avec comptabilité exhaustive des essais,
   splits locaux et comportementaux, critères préenregistrés et artefacts immuables.
6. Calibrer et geler les familles locales avant les contraintes globales, sauf
   non-identifiabilité documentée justifiant une campagne conjointe.
7. Conserver séparément le meilleur essai et l'ensemble scientifiquement
   admissible ; un échec ne doit pas augmenter silencieusement la capacité.
8. N'ouvrir le protocole stimulus/sham `evaluation_only` qu'après gel des
   paramètres et du protocole.

À ce jour : une campagne déterministe de transfert de preuve a été acceptée ; elle
n'a ajusté aucune valeur. Le compilateur factorisé vérifie maintenant les 1 992
coefficients proprioceptifs, 2 108 mécanorécepteurs et 7 849 moteurs à partir de
routes et transferts séparés. Son test uniforme/unitaire est synthétique, en
mémoire et explicitement non calibré. Le runner autonome reproduit ce contrôle en
six essais exhaustivement comptabilisés et protège déjà frontières, lignée,
budgets et scénarios tenus à l'écart. Le contrat central signé ajoute neuf
efficacités de classe et trois paramètres globaux, tous non ajustés, et couvre
exhaustivement le graphe avec un probe structurel non promouvable. Aucun parameter
set complet n'a été promu et aucune cible comportementale n'est autorisée. L'étude
aval préenregistrée est terminée : elle classe l'ensemble comme hautement sensible
en motif et en amplitude, sans sélectionner de candidat. La première contrainte
de portabilité numérique retire le candidat 30 et conserve 31 survivants sans les
classer. Le gate borné de classe neuronale est maintenant terminé avec `revise` :
référence déterministe, comptabilité exhaustive, Brian2, pertes temporelles et
pilote aBN1 sont enregistrés. Le transfert circuitaire complet reste partiel avec
un type aBN2 non résolu, mais cette lacune ne bloque pas les chaînes locales qui
l'excluent explicitement. Aucun paramètre dont les unités dépendent d'une
population non affectée ne doit être promu. Les fichiers de
`calibration/` déterminent l'ordre effectif ; cette section en est le résumé humain.

Le gate d'évidence basal ferme l'inventaire mais conclut qu'aucune valeur n'est
encore transférable. Le gate de readiness ajoute trois formes de sensibilité sans
valeur et refuse explicitement le run global : 196 neurones locaux sont comptés sur
166 700, et les six familles basales sont hors de ce corridor. Le prochain lot ne
doit ni répéter cet inventaire ni inventer le pont d'unités : il doit étendre
l'affectation aux populations effectivement atteintes, puis définir leurs interfaces
natives en conservant l'incertitude `dual_unresolved`. La première moitié est
maintenant fermée par la comptabilité exhaustive : 166 431 neurones atteints ont
une disposition et les 25 582 574 frontières internes sont comptées. La seconde
est maintenant scindée : le noyau global typé/hybride est exécutable avec un
vecteur d'affectation explicite, et les 6 041 sources compilent désormais vers
les deux ponts event/graded. Leur classe native reste `dual_unresolved` et leurs
taux/échelles physiologiques restent absents. Les deux extrêmes et les six runs
de formes basales ferment la mécanique du runtime et de l'interface, pas
l'espace combinatoire ni la calibration des interfaces.

Le gate suivant propage désormais une enveloppe technique finie jusqu'à la chaîne
locale gelée, sans la présenter comme une calibration physiologique. Les 39 runs
GPU couvrent deux profils d'affectation, trois niveaux de charge par forme, trois
échelles graded, deux silences, douze ablations famille par famille et un contrôle
event de 96 ms. Tous sont finis et les 6 041 sources restent comptées. Sous le
fixture mixed/graded de référence, l'ablation des 1 815 afférences de modalité
inconnue modifie d'environ 89 % les métriques du probe moteur : cette famille est
donc un risque prioritaire, pas une valeur à choisir. Le profil tout-event atteint
les 36+150+10 neurones locaux au contrôle long mais reste sous le seuil de génération
d'événements internes. Ce résultat pointe un gate d'échelle/seuil, sans invalider
ni sélectionner le modèle event.

Ce gate est maintenant cartographié par une grille technique appariée et figée,
sans sélectionner de valeur. Un silence et douze croisements entre 20/80/320 Hz
par terminal et 0,05/0,2/0,8/3,2 mV ont exécuté 96 ms sur les 166 700 neurones ;
les quatre échelles d'une même intensité ont reçu exactement les mêmes événements
sources. Onze membres non nuls restent sous le seuil ; seul le coin 320 Hz / 3,2
mV génère six événements runtime, le premier à 26,2 ms. Le résultat confirme que
l'intensité source et l'échelle synaptique sont un risque couplé. Il ne transforme
pas ce coin en valeur physiologique, ne valide pas l'affectation tout-event et
n'autorise pas à étendre cette grille après observation.

En parallèle, le gate d'actionneurs est maintenant terminé sans attendre le choix
rate/LIF, car ses probes sont physiques et comportement-naïfs. Le prochain front
indépendant doit figer une chaîne sensorielle locale minimale et une chaîne motrice
locale minimale. Aucune campagne de stabilité incarnée ne doit libérer en même
temps les familles centrales, sensorielles, motrices et mécaniques ; la mécanique
et le contrat direct-motor restent gelés et l'identifiabilité des interfaces doit
être explicitement testée.

Le contrat complet préalable à cette stabilité est exécutable via
`embodied_measurement_contract_v1.bat`. Il valide les observables et les paires
baseline/perturbée sur un fixture passif, pas la stabilité. Les étapes
FeCO→CNS typé→moteur sont maintenant exécutées par le panneau complet sur 120/120
tuples et 240/240 épisodes. Le prochain lot doit conserver ce résultat comme
baseline d'implémentation et définir le plus petit régime fermé ensemble-aware
qui remplace les constantes, signes et projections diagnostiques par des familles
déclarées et des valeurs sourcées ou techniquement bornées. Les mécanismes
physiques restent gelés et aucun candidat d'interface ne peut être sélectionné à
partir de la trajectoire corporelle.

La préférence prospective tactile reste conditionnelle. La chaîne FeCO avancée
est proprioceptive et ne remplace pas la chaîne mécanoréceptrice : celle-ci compte
323 groupes, 2 108 routes candidates et jusqu'à 1 785 dimensions de routage, avec
transfert non ajusté et aucun dataset local admis. Avant de verrouiller un
protocole de contact, il faut accepter une chaîne mécanoréceptrice minimale ou
documenter son échec et enregistrer, avant observation, une alternative
proprioceptive biologiquement sourcée.

Les `next_action` du registre et le tableau de bord déterminent l'ordre concret du
prochain lot ; cette liste ne remplace pas ces sources de vérité.

## Reproduction locale

Le parcours canonique depuis un clone vierge est
[`docs/reproduction-pipeline.md`](docs/reproduction-pipeline.md). Il fait foi pour
l'ordre des commandes, les prérequis non versionnés, les tailles, les jetons et la
séparation entre reconstruction obligatoire, campagnes courantes et replays
historiques. La liste ci-dessous reste un aide-mémoire des points d'entrée, pas
une demande de tout rejouer séquentiellement.

```text
setup.bat                 # si l'environnement n'existe pas
download_data.bat         # si les tables MaleCNS ou le supplément optique sont absents
status.bat
run_analysis.bat          # inventaires et manifestes ; neuPrint si jeton présent
run_wiring_smoke.bat      # reconstruction et parcours structurel complet
dashboard.bat             # état HTML/DOT recalculé
wiring_map.bat            # carte exhaustive interactive locale
connectome_benchmark.bat  # vrai MaleCNS CPU/GPU + trace compacte non calibrée
closed_loop_record.bat    # vrai MaleCNS en boucle fermée + trajectoire physique
physical_replay.bat       # viewer autonome de la dernière trajectoire physique
closed_loop_live.bat      # même boucle directement dans le viewer, même si lente
diagnostic_viewer.bat     # viewer MuJoCo + faux CNS isolé, non scientifique
embodied_stability_metrics.bat # métriques descriptives du replay gelé ; aucun seuil ni claim de stabilité
embodied_measurement_contract_v1.bat # COM/limites/jerk/contacts/récupération appariée ; aucun fit ni seuil
neutral_embodied_pilot_schedule.bat # reconstruit les 120 tuples/240 épisodes ; n'exécute pas encore le panel
neutral_embodied_adapter_sentinel.bat # 4 tuples/8 épisodes moteur→MuJoCo ; FeCO/CNS restent explicitement non exécutés
neutral_embodied_full_chain_sentinel.bat # 4 tuples/8 épisodes FeCO→CNS typé→moteur→MuJoCo ; fixtures diagnostiques, aucune calibration
neutral_embodied_full_chain_panel.bat # 120 tuples/240 épisodes du même contrat ; comptabilité exhaustive, aucune sélection ni stabilité
neutral_embodied_declared_envelope.bat # 240 tuples, profils FeCO/signes/numériques déclarés ; planning seulement, zéro fit/exécution
neutral_embodied_declared_neural_sentinel.bat # exécute les 240 tuples neuraux déclarés, oracles d'axes, zéro fit/physique/sélection
neutral_embodied_declared_closed_loop_sentinel.bat # 16 tuples/32 épisodes corps→FeCO→CNS local→moteur→corps ; zéro fit/sélection
neutral_embodied_declared_closed_loop_panel.bat # 240 lignes comptées ; résultat courant 237 complètes/3 bloquées par limite MOTOR ; zéro clipping/sélection
neutral_embodied_command_limit_diagnostic.bat # 3 lignes x 2 branches x 2 répétitions ; localise le premier franchissement sans l'appliquer
neutral_embodied_feedback_nonamplification.bat # 65 lignes actives x 10 épisodes ; produit l'ensemble technique local non classé de 3 composites
front_leg_member_conditioned_freeze_boundary.bat # reconstruit les 3 bundles exacts ; zéro gel marginal, 6 familles basales non exercées
basal_low_capacity_readiness.bat # 3 formes basales sans valeur ; expose les blockers du run typé/hybride global
basal_population_reachability.bat # 6 familles -> 166431 neurones ; dispositions exhaustives, valeurs physiologiques encore bloquées
basal_typed_hybrid_runtime_sentinel.bat # 2 extrêmes plein graphe ; 4 frontières, zéro affectation/valeur promue
basal_source_bridges.bat # 6041 sources x 2 ponts candidats ; 3 formes x 2 extrêmes, fixtures non promouvables
basal_source_envelope.bat # 39 membres, 12 ablations, probe local 196 neurones ; sensibilité technique sans promotion
basal_event_scale_gate.bat # silence + grille 3x4 appariée ; compatibilité event seulement, aucune valeur promue
front_leg_member_physical_preview.bat # génère 3 replays physiques : FlyBody complet, contrôleur local seulement
front_leg_member_preview_replay.bat [129|141|238] # ouvre un replay ; aucun membre n'est une référence scientifique
cycle_topology.bat        # topologie cyclique structurelle du vrai MaleCNS
wiring_revalidation.bat   # règles indépendantes, comparaisons et exceptions input/output
calibration_status.bat     # inventaire des familles + cohérence/acyclicité du DAG
compile_calibration_evidence.bat # prior neurotransmetteur/signe reproductible
parameter_compiler_check.bat # factorisation routage/transfert, test structurel seulement
calibration_runner_check.bat # runner autonome, six essais d'infrastructure non calibrants
signed_dynamics_contract_check.bat # couverture signée exhaustive, probes non calibrants
characterize_signed_dynamics.bat # 7 régimes centraux non ajustés, diagnostic seulement
fit_signed_dynamics_pilot.bat # 32 candidats centraux, fitting technique sans comportement
central_ensemble_sensitivity.bat # sensibilité des 32 candidats sur 815 sorties brutes
constrain_central_timestep_v1.bat # filtre 5/2,5/1,25 ms, aucun comportement
compile_basal_evidence.bat # couverture/preuves basales, zéro valeur sans affectation locale et unités natives
neural_model_gate.bat # benchmark v0 historique, supersédé pour le gate scientifique
neural_model_source_fidelity.bat # audit source + sémantiques LIF v1 + benchmark CPU/GPU, aucune calibration
setup_brian2_reference.bat # environnement historique isolé Python 3.10 / Brian2 2.5.1 sous runs/
brian2_conformance.bat # frontières scheduler Brian2: intégration, délai, reset et réfractarité
temporal_model_probes.bat # collisions rate/event et pathologies techniques, aucun comportement
audit_circuit_reference.bat # transfert FlyWire→MaleCNS + chemins structuraux ; résultat partiel, zéro fitting
run_abn1_gate_pilot.bat # répétition bornée v2 sur graphe complet ; descriptif seulement, aucune sélection
neural_model_micro_tests.bat # 27 oracles rapides de mécanique neuronale ; aucune validation biologique
lock_abn1_reference.bat # reconstruit/verrouille le probe aBN1 JO-CE/JO-F avant toute sortie candidate
actuator_semantics_gate.bat # contrat local des 102 moteurs, probes passives et saturation
actuator_attribution_gate.bat # attribution passif/ouvert/fermé + symétrie tethered, zéro fitting/comportement
prepare_local_source_data.bat # sources FeCO/moteur checksum-lockées ; gros pilote moteur opt-in
feco_observation_contract.bat # fidélité du modèle calcium public, divergences conservées, zéro valeur promue
fit_feco_calcium_observation.bat # 7 chemins FeCO, 86 folds leave-one-animal-out ; ensemble non promu
inspect_motor_pilot.bat # 3 archives exactes vérifiées, 1 022 membres inventoriés sans extraction
motor_source_contract.bat # 5 sources publiques, cohorte/filtres/unités ; zéro fit et aucun noyau temporel
parse_motor_spike_force_pilot.bat # port source retrouvé, 194 essais comptés, tables normalisées ignorées par Git
fit_motor_spike_force_pilot.bat # 3 fits agrégés diagnostiques terminés, aucune valeur promue
fit_motor_twitch_temporal_pilot.bat # 33 traces mono-spike, rapide soutenu, intermédiaire faible, lent non identifié
motor_actuator_bridge_envelope.bat # 198 probes tethered, ensemble de 3 gains conditionnels, aucune promotion
front_leg_chain_envelope.bat # 360 couples CNS, 24 alternatives FeCO, 990 probes motrices, aucune sélection
front_leg_intermediate_dynamics.bat # 150 intermédiaires comptés, 2 event_required, 148 dual_unresolved
front_leg_uncertainty_panel.bat # 50 profils pairwise, FeCO/moteur factorisés, zéro promotion
```

Les données brutes, les artefacts `data/derived/`, les exécutions `runs/` et les
rapports générés sont ignorés par Git. Un clone contient la méthode et le registre,
mais doit régénérer ces artefacts. Le rapport principal est alors
`reports/generated/project-status.html`.

La méthode complète est dans [`docs/wiring-methodology.md`](docs/wiring-methodology.md)
et la politique de sources dans
[`docs/provenance-policy.md`](docs/provenance-policy.md).
La méthode de calibration et son registre sont dans
[`docs/calibration-methodology.md`](docs/calibration-methodology.md) et
[`calibration/`](calibration/README.md).
