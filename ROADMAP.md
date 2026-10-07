# Roadmap Simple-AIOS — V0.1 et V0.2

Chaque étape représente une modification logique testable et un petit commit.
Ne réaliser que l'étape demandée. Les étapes futures décrivent des objectifs,
pas des fonctionnalités déjà présentes.

Statuts : `[done]` terminé, `[current]` en cours, `[todo]` à faire.

État : phases 0 à 10 de la V0.1 terminées. Étapes 11.1 à 11.4 de la V0.2 terminées.
Prochaine étape : 11.5 — Modification sécurisée d'un fichier, uniquement sur demande.

Validation de l'étape 0.1 sous Python 3.12 : installation éditable réussie,
`python -m pytest -q` : 1 test réussi ; `python -m aios` : `Simple-AIOS`.

Validation de l'étape 0.2 sous Python 3.12 : `python -m pytest -q` : 9 tests
réussis (invite, commandes, espaces, entrées vides ou inconnues, EOF et Ctrl+C).

Validation de l'étape 1.1 sous Python 3.12 : `python -m pytest -q` : 30 tests
réussis, dont 21 pour le chargement TOML, les valeurs par défaut et la validation.
À cette étape, le chargeur était indépendant du CLI, sans logging ni appel LLM.

Validation de l'étape 1.2 sous Python 3.12 : `python -m pytest -q` : 40 tests
réussis. Logs de démarrage, arrêt et erreurs, filtrage du niveau, absence de
doublons, fermeture des fichiers et protection des messages sensibles vérifiés.
Le CLI charge désormais les valeurs par défaut ou un fichier via `--config`.

Validation de l'étape 2.1 sous Python 3.12 : `python -m pytest -q` : 49 tests
réussis. Contrat abstrait, réponses prédéfinies, épuisement explicite et copie
indépendante des appels vérifiés, sans LLM ni accès réseau.

Validation de l'étape 2.2 sous Python 3.12 : `python -m pytest -q` : 76 tests
réussis. Requête Ollama sans streaming, modèle et URL configurés, timeout,
erreurs HTTP/réseau, réponses invalides, fermeture des réponses et préservation
des messages vérifiés avec un transport simulé, sans LLM ni accès réseau.
À cette étape, le provider était indépendant du CLI.

Validation de l'étape 2.3 sous Python 3.12 : `python -m pytest -q` : 85 tests
réussis. Conversation CLI avec contexte en mémoire, commandes locales,
configuration du provider, reprise après erreur Ollama, sorties propres et
absence de contenu sensible dans les logs vérifiées avec FakeLLMProvider.
Les réponses restent du texte ; aucun outil système n'est exécuté.

Validation de l'étape 3.1 sous Python 3.12 : `python -m pytest -q` : 126 tests
réussis. Contrat abstrait, cohérence des résultats, enregistrement et refus des
doublons, validation avant exécution, copie des arguments et erreurs sans
détails sensibles vérifiés avec des outils fictifs en mémoire. Aucun outil
système ni raccordement au CLI ou au LLM ajouté.

Validation de l'étape 3.2 sous Python 3.12 : `python -m pytest -q` : 142 tests
réussis. Résultat structuré de `system.info`, refus des arguments avant lecture,
uptime, erreurs de lecture et absence de commandes externes vérifiés. Un appel
réel sous Linux a également validé les cinq champs. Aucun raccordement au CLI
ou au LLM ajouté.

Validation de l'étape 3.3 sous Python 3.12 : `python -m pytest -q` : 169 tests
réussis. Résultat structuré de `system.memory`, conversion en octets, calculs
d'utilisation, refus des arguments et des données invalides, erreurs de lecture
et absence de commandes externes vérifiés. Un appel réel sous Linux a validé
les cinq champs. Aucun raccordement au CLI ou au LLM ajouté.

Validation de l'étape 3.4 sous Python 3.12 : `python -m pytest -q` : 198 tests
réussis. Résultat structuré de `system.disk`, chemin par défaut ou explicite,
validation des arguments, pourcentages et erreurs vérifiés. Des consultations
réelles de fichiers et dossiers ont confirmé l'absence de modification ; un
appel sur `/` a validé les cinq champs. Aucun raccordement au CLI ou au LLM ajouté.

Validation de l'étape 3.5 sous Python 3.12 : `python -m pytest -q` : 226 tests
réussis. Résultat structuré de `process.list`, tri par PID, limites de résultats,
validation avant lecture, processus disparus ou inaccessibles et erreurs
vérifiés. Les tests confirment que seuls les noms courts sont lus, sans modifier
les fichiers. Un appel réel sous Linux a validé le résultat avec une limite de
cinq processus. Aucun raccordement au CLI ou au LLM ajouté.

Validation de l'étape 4.1 sous Python 3.12 : `python -m pytest -q` : 240 tests
réussis. Niveaux `RiskLevel.READ`, `CONFIRM` et `DENY`, classification `DENY` par
défaut, déclaration `READ` des quatre outils existants et refus des niveaux
invalides à l'enregistrement vérifiés. Consultation des niveaux sans exécution
testée. Cette étape ajoute des métadonnées uniquement ; les décisions du Policy
Engine et la confirmation dans le CLI restent à implémenter aux étapes suivantes.

Validation de l'étape 4.2 sous Python 3.12 : `python -m pytest -q` : 268 tests
réussis. Décisions `ALLOW`, `CONFIRM` et `DENY` depuis les risques du registre,
refus des outils inconnus, des noms et niveaux invalides, classification par
défaut et relecture des niveaux à chaque appel vérifiés. Le moteur ne déclenche
ni validation des arguments, ni exécution d'outil, ni demande de confirmation.
Les quatre outils existants sont reconnus comme `ALLOW` sans être exécutés.
La confirmation CLI et le raccordement au LLM restent aux étapes suivantes.

Validation de l'étape 4.3 sous Python 3.12 : `python -m pytest -q` : 301 tests
réussis. Composant CLI de confirmation relié aux décisions du Policy Engine,
accord explicite `oui`, refus des réponses vides ou ambiguës, EOF, Ctrl+C,
erreurs et entrées non interactives vérifiés. Affichage des arguments avec
caractères de contrôle échappés, absence de logs et d'exécution, relecture de
la policy et absence de réutilisation d'un accord testés. Un essai dans un
terminal a confirmé le refus d'une entrée vide et l'acceptation de `oui`.
La conversation reste textuelle ; aucun appel d'outil du LLM ajouté.

Validation de l'étape 5.1 sous Python 3.12 : `python -m pytest -q` : 365 tests
réussis. Format JSON unique `tool` / `arguments`, champs et types stricts,
refus des doublons à tous les niveaux, des nombres non finis et des documents
entourés de texte ou multiples vérifiés. Limites de taille et de profondeur,
conservation des valeurs, erreurs génériques et absence de logs testées.
Une réponse de FakeLLMProvider est parsée sans consultation du registre,
décision de policy, confirmation ni exécution. La conversation reste textuelle ;
le raccordement des appels d'outils reste prévu à l'étape 5.2.

Validation de l'étape 5.2 sous Python 3.12 : `python -m pytest -q` : 399 tests
réussis. Circuit CLI complet avec FakeLLMProvider : format strict, registre,
validation unique des arguments, policy, confirmation éventuelle, exécution et
retour JSON au modèle vérifiés. Refus, erreurs génériques, résultats non
sérialisables, absence de contenu sensible dans les logs et conservation du
résultat après une erreur du provider testés. Un essai réel avec `system.info`
a confirmé le retour des cinq champs au faux provider. Un seul appel d'outil
est traité par demande ; aucune boucle ni étape suivante ajoutée.

Validation de l'étape 5.3 sous Python 3.12 : `python -m pytest -q` : 412 tests
réussis. Enchaînement des appels avec leurs résultats, arrêt sur réponse
textuelle et limite de cinq tentatives par requête vérifiés avec FakeLLMProvider.
Les appels invalides, refusés ou échoués consomment aussi le budget. Un sixième
appel est bloqué avant validation, confirmation ou exécution ; une réponse
textuelle après le cinquième résultat reste possible. Remise à zéro du compteur
à la demande suivante, relecture de la policy, confirmations indépendantes,
historique après limite ou erreur du provider et absence de données sensibles
dans les logs testés. Aucune étape suivante ajoutée.

Validation de l'étape 6.1 sous Python 3.12 : `python -m pytest -q` : 469 tests
réussis. `systemd.status` classé READ, validation d'un nom explicite `.service`,
commande `systemctl show` fixe sans shell, timeout et résultat structuré testés.
États actifs, inactifs, en échec ou masqués, noms invalides, service introuvable,
sorties mal formées, erreurs sans détails sensibles et retour au modèle via le
CLI vérifiés avec `systemctl` simulé et FakeLLMProvider. L'essai local sans
systemd a confirmé l'échec structuré attendu ; aucun service réel n'a pu être
interrogé dans cet environnement. Aucune étape suivante ajoutée.

Validation de l'étape 6.2 sous Python 3.12 : `python -m pytest -q` : 511 tests
réussis. `systemd.list` classé READ, commande fixe `systemctl list-units` sans
shell, timeout, liste des services connus triée par nom et bornée avec indicateur
de troncature vérifiés. Limite par défaut de 20, bornes de 1 à 100, liste vide,
états et noms échappés, refus des arguments invalides, des lignes mal formées ou
dupliquées, erreurs génériques et retour au modèle testés avec `systemctl` simulé
et FakeLLMProvider. L'essai local sans systemd a confirmé l'échec structuré
attendu ; aucune liste réelle n'a pu être interrogée ici. Aucune étape suivante
ajoutée.

Validation de l'étape 6.3 sous Python 3.12 : `python -m pytest -q` : 584 tests
réussis. `systemd.restart` classé CONFIRM, nom `.service` strict, rejet des
arguments invalides avant autorisation, commande fixe sans shell ni élévation
de privilèges et résultat structuré vérifiés. Refus sans fonction d'autorisation,
confirmation explicite dans un terminal, refus par défaut, accord non réutilisé,
erreurs sans détails sensibles et timeout à issue inconnue testés. Le CLI
transmet succès, refus et erreurs au modèle. Tous les redémarrages sont simulés
avec `systemctl` remplacé et FakeLLMProvider ; aucun service réel n'a été
redémarré. Aucune étape suivante ajoutée.

Validation de l'étape 7.1 sous Python 3.12 : `python -m pytest -q` : 589 tests
réussis. Prompt système fixe décrivant le rôle, les sept outils, leurs arguments,
les résultats réels et les permissions ajouté. Catalogue et risques comparés au
registre, exemples validés sans exécution et budget d'appels vérifié. Message
`system` unique en tête de la conversation, conservation après appels d'outils
ou erreurs, remise à zéro entre sessions et transmission au transport Ollama
vérifiées. Les textes utilisateur et résultats restent dans leurs rôles prévus,
sans promotion en instructions système. Tests avec FakeLLMProvider et HTTP
simulé, sans LLM réel ; aucun nouveau mécanisme de diagnostic ajouté.

Validation de l'étape 7.2 sous Python 3.12 : `python -m pytest -q` : 610 tests
réussis. `/diagnose` collecte cinq contrôles READ fixes avec validation et policy
avant chaque exécution, puis demande une unique synthèse au provider. Refus des
risques non READ sans confirmation, erreurs partielles ou totales, résultats
invalides, conservation après erreur du provider, nouvelles lectures à chaque
diagnostic et retour au budget conversationnel vérifiés. Aucun appel d'outil du
modèle ne peut être exécuté pendant la synthèse. Tests avec FakeLLMProvider et
lectures simulées. Un essai local a validé les lectures réelles de system.info,
system.memory, system.disk et process.list ; systemd.list a échoué proprement
dans cet environnement sans systemd actif. Aucun redémarrage, aucune correction
automatique ni étape suivante ajoutés.

Validation de l'étape 8.1 sous Python 3.12 : `python -m pytest -q` : 641 tests
réussis, dont 31 pour l'historique SQLite. Installation éditable effectuée avec
les dépendances de construction déjà disponibles localement, sans ajout de
dépendance au projet. Tâche, horodatage UTC et statut persistés avant et après
traitement ; réouverture, requêtes SQL paramétrées, erreurs, interruptions et
fermeture des connexions vérifiées avec de vrais fichiers SQLite et FakeLLMProvider.
Commandes locales exclues, une ligne par demande ou diagnostic, conservation
après erreur du provider et absence de reprise automatique testées. Marqueurs
sensibles masqués avant écriture, réponses et détails d'outils non persistés,
erreurs de stockage sans détails sensibles et arrêt avant traitement si
l'insertion échoue vérifiés. Aucun historique détaillé d'outil ni `/history`
ajouté ; aucune étape suivante commencée.

Validation de l'étape 8.2 sous Python 3.12 : `python -m pytest -q` : 672 tests
réussis, dont 31 nouveaux pour l'historique des outils. Table SQLite reliée aux
tâches, ajout à une base 8.1 existante sans perte, horodatage UTC, arguments
demandés filtrés, résultat et statut persistés vérifiés. Tentative enregistrée
avant validation et résultat avant le prochain appel au provider. Succès, refus,
appels invalides ou inconnus, erreurs, interruption et résultat non sérialisable
testés avec FakeLLMProvider et des exécutions simulées. Filtrage récursif sans
mutation des données en mémoire, confirmation toujours obligatoire, diagnostic,
limite de cinq tentatives, conservation après erreur du provider et arrêt sans
réexécution en cas d'échec de stockage vérifiés. Aucune dépendance ajoutée,
aucun service réel redémarré et aucune commande `/history` implémentée.

Validation de l'étape 8.3 sous Python 3.12 : `python -m pytest -q` : 684 tests
réussis, dont 12 nouveaux pour `/history`. Consultation locale sans argument,
historique vide, 20 dernières tâches et appels associés dans leur ordre,
persistance entre sessions et rafraîchissement après une demande vérifiés.
Lecture seule avec écritures SQLite interdites pendant le test, absence de
nouvelle tâche, d'appel au provider, d'exécution ou de réinjection dans le
contexte conversationnel testées. Statuts incomplets, valeurs nulles, masquage,
échappement des caractères de contrôle, arguments refusés et erreurs de lecture
sans détails sensibles vérifiés. Le test du CLI installé couvre `/history`
sans serveur Ollama. Aucune dépendance ajoutée ni étape suivante commencée.

Validation de l'étape 9.1 sous Python 3.12 : installation éditable réussie,
`python -m pytest -q` : 705 tests réussis, dont 21 nouveaux pour le Core sans
terminal. Conversation, contexte, diagnostic, policy, boucle d'outils et
historique extraits dans `aios.core.Core`. Le CLI conserve saisie, affichage,
commandes locales, confirmation et gestion des ressources. Sessions séparées,
refus par défaut sans gestionnaire de confirmation, accord strict et impossibilité
de contourner DENY vérifiés. Limite de cinq appels, diagnostic READ, résultats
conservés après erreur du provider et statuts d'interruption testés sans LLM
ni action système réelle. Les tests CLI existants passent après adaptation.
Aucune dépendance ajoutée, aucun daemon ni socket implémenté.

Validation de l'étape 9.2 sous Python 3.12 : installation éditable réussie,
`python -m pytest -q` : 746 tests réussis, dont 41 nouveaux pour le daemon.
Entrée `aiosd`, configuration existante et socket Unix `0600` vérifiés avec de
vrais échanges entre processus. Protocole JSON par ligne pour conversation,
diagnostic et historique ; limites de taille et d'attente, champs stricts,
UTF-8, trames fragmentées et sessions distinctes testés. Policy, refus sans
confirmation, budget de cinq appels, persistance et conservation des résultats
après erreur ou déconnexion vérifiés avec FakeLLMProvider et outils simulés.
Arrêts SIGINT/SIGTERM, fermeture SQLite, préservation des chemins existants,
nettoyage du socket et erreurs sans détails sensibles testés. Les tests ont
nécessité l'accès aux sockets Unix, bloqués par le sandbox initial. Aucun LLM
ni service réel sollicité, aucune dépendance ajoutée. CLI et unité systemd
laissés aux étapes suivantes.

Validation de l'étape 9.3 sous Python 3.12 : installation éditable réussie,
`python -m pytest -q` : 805 tests réussis. CLI relié au daemon par une connexion
Unix persistante et ouverte à la première requête ; conversation, diagnostic
et historique vérifiés entre vrais processus, avec FakeLLMProvider et outils
simulés. Aucune construction locale du Core, du provider ou de SQLite, commandes
locales sans daemon et fermeture du client sans arrêt du serveur testées.
Confirmation liée à un identifiant neuf par action, arguments validés côté
daemon, accord strict, refus en entrée non interactive, absence d'accord ou
rejeu vérifiés. Sessions conservées pendant la saisie, limites des trames,
réponses invalides, absence de daemon, timeout et erreurs du provider couverts
sans reconnexion ni renvoi automatique. Tests métiers existants conservés via
un adaptateur en mémoire, tests de transport exécutés avec l'accès aux sockets
Unix. Aucun vrai LLM ni service sollicité, aucune dépendance ni unité systemd
ajoutée ; aucune étape suivante commencée.

Validation de l'étape 9.4 sous Python 3.12 : installation éditable réussie,
`python -m pytest -q` : 807 tests réussis, dont deux nouveaux pour l'unité
utilisateur `systemd/simple-aios.service`. Syntaxe validée par
`systemd-analyze --user verify` (systemd 255), avec le chemin personnel adapté
au répertoire temporaire du test. Commande `aiosd` exécutée directement depuis
le venv : connexion du client, historique sans Ollama, permissions privées,
arrêt SIGTERM, retrait du socket et conservation de SQLite et des logs vérifiés.
L'unité fonctionne avec les chemins par défaut du CLI, sans privilèges
supplémentaires ni redémarrage automatique. Utilisation manuelle documentée.
Aucun gestionnaire systemd n'étant actif ici, le lancement sous son contrôle
n'a pas été testé ; aucun service n'a été installé ou activé. Aucune dépendance
ni script d'installation ajouté ; aucune étape suivante commencée.

Validation de l'étape 10.1 sous Python 3.12 : installation éditable réussie,
`python -m pytest -q` : 834 tests réussis, dont 27 nouveaux pour l'installation.
Script Python standard créant ou réutilisant le venv du dépôt, installant le
package sans dépendances de test et préparant l'unité utilisateur au chemin
réel. Réexécution, XDG_CONFIG_HOME, chemins avec espaces, accents et pourcentages,
prérequis invalides, refus root, préservation des unités personnalisées, des
configurations et des données, échecs de sous-processus et validation systemd
couverts. Installation réelle également vérifiée sous un compte non privilégié
dans un dossier temporaire, hors réseau avec les outils de construction locaux :
venv neuf, package non éditable, CLI `/version` et `/exit`, aide du daemon et
unité générée validés. Aucun service activé ou démarré, aucun LLM sollicité.
Documentation d'utilisation mise à jour ; aucune dépendance ajoutée ni étape
de désinstallation ou guide Ubuntu/Debian commencée.

Validation de l'étape 10.2 sous Python 3.12 : installation éditable réussie,
`python -m pytest -q` : 860 tests réussis, dont 26 nouveaux pour la désinstallation.
Script limité au package du venv et à l'unité générée pour ce dépôt : arrêt et
désactivation utilisateur avant retrait, puis rechargement de systemd. Refus
root, validation du venv, unités personnalisées ou étrangères, liens symboliques,
modification concurrente de l'unité, absence d'installation, réexécution,
XDG_CONFIG_HOME, erreurs et timeouts couverts. Dépôt, venv, autres paquets,
configurations, historique et logs conservés. Installation puis désinstallation
réelles vérifiées sous un compte non privilégié dans un dossier temporaire,
hors réseau avec les outils de construction locaux et systemctl simulé :
package et entrée aiosd retirés, données préservées et seconde exécution réussie.
Aucun service réel modifié ni LLM sollicité. Documentation d'utilisation mise
à jour ; aucune dépendance ajoutée ni guide Ubuntu/Debian commencé.

Validation de l'étape 10.3 sous Python 3.12 : `python -m pytest -q` : 860 tests
réussis avant l'interruption. À la reprise du 5 octobre 2026, après installation
éditable, la même commande donne 803 tests réussis et 57 échecs liés aux sockets
Unix interdits par l'environnement ; l'accès supplémentaire a été refusé par
la politique d'approbation. Aucun code ni test n'a été modifié pour cette étape.
Guide `docs/installation-ubuntu-debian.md` ajouté pour Ubuntu 24.04 LTS, Debian
13 et les environnements Debian 12 dont Python est trop ancien.
Prérequis, installation du dépôt, Ollama et modèle `qwen3`, service systemd
utilisateur, vérifications CLI, configuration facultative, dépannage, mise à
jour et désinstallation sont décrits à partir des scripts et chemins réellement
présents dans le projet. Les commandes et liens vers les sources officielles
ont été relus ; les 14 blocs Bash passent `bash -n`, l'exemple TOML correspond
à la configuration fournie et les cibles des liens locaux existent. Aucun essai
complet sur une machine Ubuntu ou Debian neuve, aucun démarrage sous systemd
actif ni appel à un LLM réel n'a été réalisé. Aucune dépendance ajoutée ni étape
suivante définie.

Validation de l'étape 11.1 sous Python 3.12 : installation éditable réussie.
Les tests ciblés (`test_filesystem_list.py`, `test_system_prompt.py` et
`test_cli.py`) donnent 139 réussites, dont 53 nouveaux tests pour le listing.
`python -m pytest -q` : 856 réussites et 57 échecs liés aux sockets Unix interdits
par l'environnement, comme lors de la validation précédente ; aucun de ces
tests n'a été supprimé ou ignoré. Outil `filesystem.list` READ intégré au Core
et au prompt, autorisation par le Policy Engine avant accès, workspace fixe
`~/AIOS-Workspace`, chemins relatifs stricts et liens jamais suivis vérifiés.
Liste non récursive bornée à 100 entrées, nom/type/taille, troncature, erreurs
génériques, remplacement concurrent d'un chemin, fermeture des descripteurs,
absence de lecture du contenu des fichiers, d'écriture ou de commande externe
testés sur des fichiers temporaires et avec FakeLLMProvider. Aucun vrai LLM
sollicité, aucune dépendance ajoutée, aucune configuration des workspaces ni
étape suivante implémentée.

Validation de l'étape 11.2 sous Python 3.12 : les tests ciblés de lecture,
listing, prompt, CLI, Core et historique d'outils donnent 251 réussites,
dont 60 nouveaux tests. `python -m pytest -q` : 916 réussites et 57 échecs liés
aux sockets Unix interdits par l'environnement, comme à l'étape précédente ;
aucun test supprimé ou ignoré. Outil `filesystem.read` READ intégré au Core et
au prompt, avec le workspace fixe de 11.1 et les mêmes contrôles de chemins
partagés. Lecture UTF-8 stricte bornée à 64 Kio, taille en octets, fichier vide,
lectures courtes, croissance concurrente, refus des liens, dossiers et fichiers
spéciaux, remplacement du fichier et fermeture des descripteurs vérifiés.
Validation et policy avant lecture, erreurs sans contenu partiel, absence
d'écriture ou de commande externe et contenu remplacé avant persistance SQLite
testés avec des fichiers temporaires et FakeLLMProvider. Aucun vrai LLM,
aucune dépendance ajoutée, aucune configuration des workspaces ni étape
suivante implémentée.

Validation de l'étape 11.3 sous Python 3.12 : installation éditable réussie.
Les tests ciblés filesystem, CLI, prompt, Core et historique d'outils donnent
331 réussites, dont 80 nouveaux tests. `python -m pytest -q` : 996 réussites et
57 échecs liés aux sockets Unix interdits par l'environnement, comme à l'étape
précédente ; aucun test supprimé ou ignoré. `filesystem.mkdir` CONFIRM intégré
au Core et au prompt, avec le workspace fixe et les contrôles de chemins
existants. Création d'un seul dossier, parents préexistants, permissions 0700
réduites par l'umask, refus des entrées existantes et des liens symboliques,
changements concurrents de chemins et fermeture des descripteurs vérifiés.
Validation avant confirmation, refus par défaut même en Python direct, accord
CLI explicite et non réutilisé, DENY non contournable, erreurs génériques et
résultat réel transmis au modèle et à SQLite testés. Dossiers temporaires et
FakeLLMProvider uniquement, sans commande externe, privilèges supplémentaires,
nouvelle dépendance ni étape suivante implémentée.

Validation de l'étape 11.4 sous Python 3.12 : installation éditable réussie.
Les tests ciblés filesystem, CLI, prompt, Core et historique d'outils donnent
434 réussites, dont 103 nouveaux tests. `python -m pytest -q` : 1099 réussites
et 57 échecs liés aux sockets Unix interdits par l'environnement, comme aux
étapes précédentes ; aucun test supprimé ou ignoré. `filesystem.write` CONFIRM
intégré au Core et au prompt : création exclusive d'un fichier UTF-8 neuf,
contenu borné à 64 Kio, chemin relatif validé, parents préexistants, permissions
0600 réduites par l'umask. Refus des destinations existantes, liens symboliques
et physiques, fichiers spéciaux, chemins invalides et contenu hors limites
vérifiés. Écritures courtes, changements concurrents de chemins, erreurs et
interruptions sans faux succès, fermeture des descripteurs et signalement d'un
fichier potentiellement incomplet testés. Confirmation du chemin et du contenu,
refus par défaut, DENY non contournable et masquage du contenu avant toute
insertion SQLite vérifiés avec des fichiers temporaires et FakeLLMProvider.
Aucun shell, privilège supplémentaire ou dépendance ajouté ; aucune modification
de fichier existant ni étape suivante implémentée.

## Phase 0 — Fondation

- [done] 0.1 — Initialisation : package Python, bannière, tests et documentation.
- [done] 0.2 — CLI interactif : invite `ai>`, `/help`, `/exit`, `/version`, sans LLM.

## Phase 1 — Configuration

- [done] 1.1 — Configuration : provider, modèle, URL Ollama, données et logs.
- [done] 1.2 — Logging : démarrage, arrêt et erreurs, sans secrets.

## Phase 2 — LLM

- [done] 2.1 — Interface LLMProvider et FakeLLMProvider pour les tests.
- [done] 2.2 — OllamaProvider : API locale, timeout et gestion des erreurs.
- [done] 2.3 — Conversation CLI avec le provider, sans outil système.

## Phase 3 — Outils

- [done] 3.1 — Tool, ToolResult et ToolRegistry, avec validation des arguments.
- [done] 3.2 — `system.info` : hostname, OS, kernel, architecture et uptime.
- [done] 3.3 — `system.memory` : résultat structuré.
- [done] 3.4 — `system.disk` : lecture uniquement.
- [done] 3.5 — `process.list` : nombre de résultats limité.

## Phase 4 — Policy Engine

- [done] 4.1 — Niveaux de risque READ, CONFIRM et DENY pour chaque outil.
- [done] 4.2 — Policy Engine : décisions ALLOW, CONFIRM et DENY, avec tests.
- [done] 4.3 — Confirmation explicite dans le CLI, refus par défaut.

## Phase 5 — LLM et outils

- [done] 5.1 — Format JSON des appels d'outils, validation stricte.
- [done] 5.2 — Validation, policy, exécution et retour du résultat au modèle.
- [done] 5.3 — Boucle limitée à cinq appels d'outils par requête.

## Phase 6 — systemd

- [done] 6.1 — `systemd.status` en lecture seule.
- [done] 6.2 — `systemd.list` en lecture seule.
- [done] 6.3 — `systemd.restart` avec confirmation et validation stricte du service.

## Phase 7 — Diagnostic

- [done] 7.1 — Prompt système : rôle, outils, résultats réels et permissions.
- [done] 7.2 — Diagnostic général à partir de plusieurs outils READ.

## Phase 8 — Mémoire

- [done] 8.1 — Historique SQLite : tâche, timestamp et statut.
- [done] 8.2 — Historique des outils : arguments non sensibles, résultat et statut.
- [done] 8.3 — Commande `/history`.

## Phase 9 — Daemon

Commencer uniquement lorsque les phases précédentes fonctionnent.

- [done] 9.1 — Séparer le Core du terminal.
- [done] 9.2 — Daemon local `aiosd`, communication par Unix socket.
- [done] 9.3 — Connecter le CLI au daemon.
- [done] 9.4 — Unité systemd `simple-aios.service`.

## Phase 10 — Installation

- [done] 10.1 — Script d'installation simple.
- [done] 10.2 — Script de désinstallation.
- [done] 10.3 — Guide d'installation Ubuntu/Debian.

## Simple-AIOS V0.2

Les étapes 11.1 à 11.4 sont terminées ; les autres étapes ci-dessous restent `[todo]`.
Les étapes à faire décrivent des objectifs, pas des fonctionnalités présentes.
La V0.2 commence par **11.1 — `filesystem.list`**.

Les contraintes de sécurité s'appliquent dès la première étape concernée :
chemins autorisés, sauvegarde avant modification et helper minimal autorisé
pour toute opération root, même si leur configuration ou leur extension fait
l'objet d'une phase ultérieure.

### Phase 11 — Fichiers

#### [done] 11.1 — `filesystem.list`

Ajouter un outil READ permettant de lister le contenu d'un dossier autorisé.

Résultat structuré :

- nom ;
- type fichier/dossier ;
- taille si applicable.

Pas de modification du filesystem.

Commit :
`feat: add filesystem listing tool`

#### [done] 11.2 — `filesystem.read`

Ajouter un outil READ permettant de lire un fichier texte.

Contraintes :

- taille maximale ;
- UTF-8 ;
- refus des fichiers non autorisés ;
- résultat borné pour ne pas envoyer des fichiers énormes au LLM.

Commit :
`feat: add filesystem read tool`

#### [done] 11.3 — `filesystem.mkdir`

Créer un dossier.

Niveau de risque :
`CONFIRM`

Validation stricte du chemin.

Commit :
`feat: add directory creation tool`

#### [done] 11.4 — `filesystem.write`

Créer un nouveau fichier texte.

Niveau :
`CONFIRM`

Contraintes :

- chemin validé ;
- contenu borné ;
- UTF-8 ;
- refus d'écraser silencieusement un fichier existant.

Commit :
`feat: add file creation tool`

#### [todo] 11.5 — Modification sécurisée d'un fichier

Permettre de modifier un fichier texte existant.

Niveau :
`CONFIRM`

Créer automatiquement une sauvegarde avant modification.

Commit futur :
`feat: add safe file update tool`

### Phase 12 — Sécurité filesystem

#### [todo] 12.1 — Workspaces autorisés

Ajouter une configuration définissant les chemins dans lesquels Simple-AIOS peut travailler.

Exemple conceptuel :

```toml
filesystem_roots = [
    "~/AIOS-Workspace"
]
```

Tout accès en dehors de ces chemins doit être refusé.

Commit futur :
`feat: restrict filesystem workspaces`

#### [todo] 12.2 — Validation renforcée des chemins

Protéger contre :

- `..` ;
- traversée de répertoires ;
- chemins hors workspace ;
- liens symboliques permettant une sortie du workspace ;
- chemins ambigus.

Commit futur :
`feat: harden filesystem path validation`

#### [todo] 12.3 — Limites filesystem

Ajouter des limites configurables ou raisonnables pour :

- taille maximale de lecture ;
- taille maximale d'écriture ;
- nombre maximal d'éléments listés.

Commit futur :
`feat: add filesystem safety limits`

### Phase 13 — Gestion de paquets APT

Limiter cette phase aux systèmes Debian/Ubuntu.

#### [todo] 13.1 — `package.search`

Ajouter un outil READ permettant de rechercher un paquet APT.

Aucune installation.

Commit futur :
`feat: add apt package search tool`

#### [todo] 13.2 — `package.info`

Permettre de connaître :

- si le paquet existe ;
- s'il est installé ;
- version installée ;
- version candidate si disponible.

READ uniquement.

Commit futur :
`feat: add apt package info tool`

#### [todo] 13.3 — `package.install`

Installer un ou plusieurs paquets explicitement nommés.

Niveau :
`CONFIRM`

Interdictions :

- aucun shell arbitraire ;
- aucun argument brut généré par le LLM ;
- noms de paquets strictement validés ;
- utilisation de `subprocess` avec `shell=False`.

Commit futur :
`feat: add confirmed package installation`

#### [todo] 13.4 — `package.remove`

Désinstaller explicitement un paquet.

Niveau :
`CONFIRM`

Validation stricte et confirmation explicite.

Ne pas ajouter d'option destructive automatique telle que suppression massive des dépendances sans étape dédiée.

Commit futur :
`feat: add confirmed package removal`

### Phase 14 — Actions privilégiées

Simple-AIOS et `aiosd` doivent continuer à fonctionner sans privilèges root.

#### [todo] 14.1 — Helper privilégié minimal

Créer un composant distinct permettant uniquement les actions système explicitement prévues nécessitant root.

Il ne doit PAS fournir un shell général.

Commit futur :
`feat: add privileged action helper`

#### [todo] 14.2 — Allowlist des opérations privilégiées

Le helper doit accepter uniquement des opérations structurées prédéfinies, par exemple :

- installation d'un paquet ;
- suppression d'un paquet ;
- éventuellement d'autres opérations ajoutées ultérieurement explicitement.

Tout appel non connu doit être refusé.

Commit futur :
`feat: restrict privileged operations`

#### [todo] 14.3 — Audit des actions privilégiées

Enregistrer :

- opération ;
- date ;
- résultat ;
- statut ;
- arguments non sensibles.

Ne jamais journaliser de secret.

Commit futur :
`feat: audit privileged actions`

### Phase 15 — Processus

#### [todo] 15.1 — `process.info`

Afficher des informations détaillées sur un PID :

- PID ;
- nom ;
- état ;
- utilisateur si disponible ;
- mémoire ;
- CPU si disponible.

READ uniquement.

Commit futur :
`feat: add process information tool`

#### [todo] 15.2 — `process.signal`

Permettre dans un premier temps uniquement l'envoi de `SIGTERM`.

Niveau :
`CONFIRM`

Pas de SIGKILL dans cette première version.

Commit futur :
`feat: add confirmed process termination`

### Phase 16 — Réseau

#### [todo] 16.1 — `network.interfaces`

Afficher :

- interfaces ;
- état ;
- adresses IP ;
- éventuellement MTU.

READ uniquement.

Commit futur :
`feat: add network interface tool`

#### [todo] 16.2 — `network.routes`

Afficher les routes IPv4/IPv6 de façon structurée.

READ uniquement.

Commit futur :
`feat: add network route tool`

#### [todo] 16.3 — `network.dns`

Ajouter des fonctions simples de diagnostic DNS :

- résolution d'un hostname ;
- affichage du résultat ;
- erreurs structurées.

READ uniquement.

Commit futur :
`feat: add dns diagnostic tool`

#### [todo] 16.4 — `network.tcp_check`

Tester la possibilité d'établir une connexion TCP vers :

- un hôte ;
- un port.

READ uniquement.

Contraintes :

- timeout court ;
- validation stricte hôte/port ;
- pas de scan de plage ;
- pas de scan massif.

Commit futur :
`feat: add tcp connectivity tool`

### Phase 17 — Docker

Docker reste facultatif.

Simple-AIOS doit continuer à fonctionner sans Docker installé.

#### [todo] 17.1 — `docker.list`

Lister les conteneurs et leur état.

READ uniquement.

Commit futur :
`feat: add docker container listing`

#### [todo] 17.2 — `docker.logs`

Lire les derniers logs d'un conteneur.

READ uniquement.

Contraintes :

- nombre de lignes borné ;
- taille maximale ;
- nom de conteneur validé.

Commit futur :
`feat: add docker log reading tool`

#### [todo] 17.3 — `docker.restart`

Redémarrer un conteneur explicitement nommé.

Niveau :
`CONFIRM`

Commit futur :
`feat: add confirmed docker restart tool`

### Phase 18 — Plans d'exécution

#### [todo] 18.1 — Aperçu du plan

Lorsqu'une demande nécessite plusieurs actions, Simple-AIOS doit pouvoir produire un plan structuré avant exécution.

Exemple :

```text
1. Vérifier nginx             READ
2. Installer nginx            CONFIRM
3. Créer index.html           CONFIRM
4. Vérifier nginx             READ
```

Commit futur :
`feat: add execution plan preview`

#### [todo] 18.2 — Validation du plan

Permettre à l'utilisateur d'approuver explicitement un plan comportant des actions sensibles.

L'approbation globale ne doit jamais permettre de contourner une opération `DENY`.

Le Policy Engine reste autoritaire.

Commit futur :
`feat: add plan approval workflow`

#### [todo] 18.3 — Résumé d'exécution

Après un plan, afficher :

- actions réussies ;
- actions échouées ;
- actions refusées ;
- actions non exécutées.

Commit futur :
`feat: add execution summary`

### Phase 19 — Sauvegarde et rollback

#### [todo] 19.1 — Backup avant modification

Avant toute modification d'un fichier existant, créer une sauvegarde contrôlée.

Conserver les métadonnées nécessaires à la restauration.

Commit futur :
`feat: add file backup before changes`

#### [todo] 19.2 — Rollback de fichier

Ajouter un outil permettant de restaurer une sauvegarde connue.

Niveau :
`CONFIRM`

Commit futur :
`feat: add file rollback tool`

#### [todo] 19.3 — Historique des changements système

Étendre l'historique pour distinguer les actions ayant modifié la machine.

Exemples :

- fichier créé ;
- fichier modifié ;
- paquet installé ;
- conteneur redémarré ;
- service redémarré.

READ pour la consultation.

Commit futur :
`feat: add system change history`

### Phase 20 — Santé de Simple-AIOS

#### [todo] 20.1 — Commande `/health`

Ajouter une commande locale permettant de vérifier :

- état de `aiosd` ;
- socket ;
- SQLite ;
- configuration ;
- disponibilité du provider.

Elle ne doit pas modifier le système.

Commit futur :
`feat: add aios health command`

#### [todo] 20.2 — Santé Ollama

Ajouter un test léger de connexion Ollama.

Utiliser un endpoint simple ne nécessitant pas de génération lorsque possible.

Retourner un diagnostic structuré :

- joignable ;
- timeout ;
- erreur HTTP ;
- indisponible.

Commit futur :
`feat: add ollama health check`

#### [todo] 20.3 — État du modèle Ollama

Vérifier que le modèle configuré est disponible sur le serveur Ollama.

Ne pas télécharger automatiquement un modèle.

READ uniquement.

Commit futur :
`feat: add ollama model status`

### Phase 21 — Stabilisation V0.2

#### [todo] 21.1 — Tests d'intégration

Ajouter des scénarios couvrant plusieurs composants ensemble, sans nécessiter :

- root réel ;
- vrai LLM ;
- modifications dangereuses de la machine.

Utiliser mocks/fakes lorsque nécessaire.

Couvrir notamment :

- fichiers ;
- Policy Engine ;
- paquets ;
- réseau ;
- Docker ;
- plans ;
- rollback.

Commit futur :
`test: add v0.2 integration tests`

#### [todo] 21.2 — Documentation

Documenter :

- nouveaux outils ;
- niveaux de risque ;
- filesystem roots ;
- gestion de paquets ;
- helper privilégié ;
- Docker ;
- réseau ;
- rollback ;
- `/health`.

Commit futur :
`docs: document v0.2 tools`

#### [todo] 21.3 — Release V0.2

Préparer la release V0.2 :

- version ;
- changelog ;
- documentation ;
- validation des tests ;
- vérification installation/désinstallation.

Commit futur :
`chore: prepare v0.2 release`

### Principes obligatoires pour toute la V0.2

Ces règles s’appliquent à toutes les étapes de la V0.2 :

1. Une étape = une petite modification logique et testable.
2. Ne jamais commencer automatiquement l'étape suivante.
3. Aucun shell arbitraire accessible au LLM.
4. Utiliser `subprocess` avec `shell=False` lorsque nécessaire.
5. Tous les arguments venant du LLM doivent être validés.
6. Le Policy Engine reste indépendant du LLM.
7. READ peut être automatique.
8. CONFIRM nécessite une autorisation explicite.
9. DENY ne peut jamais être contourné par le modèle.
10. Les opérations root passent uniquement par un helper minimal explicitement autorisé.
11. Les tests ne doivent pas effectuer de modification dangereuse réelle.
12. Les tests ne doivent pas nécessiter un vrai LLM.
13. Ne jamais stocker ou journaliser volontairement de secrets.
14. Privilégier la bibliothèque standard Python.
15. Éviter toute nouvelle dépendance sans nécessité claire.
16. Docker doit rester facultatif.
17. Ubuntu/Debian restent les plateformes principales.
18. Toujours conserver un état Git fonctionnel entre les étapes.
