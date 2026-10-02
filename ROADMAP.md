# Roadmap Simple-AIOS — V0.1

Chaque étape représente une modification logique testable et un petit commit.
Ne réaliser que l'étape demandée. Les étapes futures décrivent des objectifs,
pas des fonctionnalités déjà présentes.

Statuts : `[done]` terminé, `[current]` en cours, `[todo]` à faire.

État : étape 8.3 terminée. Aucune étape en cours ; prochaine étape : 9.1,
à commencer uniquement sur demande.

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

- [todo] 9.1 — Séparer le Core du terminal.
- [todo] 9.2 — Daemon local `aiosd`, communication par Unix socket.
- [todo] 9.3 — Connecter le CLI au daemon.
- [todo] 9.4 — Unité systemd `simple-aios.service`.

## Phase 10 — Installation

- [todo] 10.1 — Script d'installation simple.
- [todo] 10.2 — Script de désinstallation.
- [todo] 10.3 — Guide d'installation Ubuntu/Debian.
