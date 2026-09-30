# Roadmap Simple-AIOS — V0.1

Chaque étape représente une modification logique testable et un petit commit.
Ne réaliser que l'étape demandée. Les étapes futures décrivent des objectifs,
pas des fonctionnalités déjà présentes.

Statuts : `[done]` terminé, `[current]` en cours, `[todo]` à faire.

État : étape 2.2 terminée. Aucune étape en cours ; prochaine étape : 2.3,
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
Le provider reste indépendant du CLI.

## Phase 0 — Fondation

- [done] 0.1 — Initialisation : package Python, bannière, tests et documentation.
- [done] 0.2 — CLI interactif : invite `ai>`, `/help`, `/exit`, `/version`, sans LLM.

## Phase 1 — Configuration

- [done] 1.1 — Configuration : provider, modèle, URL Ollama, données et logs.
- [done] 1.2 — Logging : démarrage, arrêt et erreurs, sans secrets.

## Phase 2 — LLM

- [done] 2.1 — Interface LLMProvider et FakeLLMProvider pour les tests.
- [done] 2.2 — OllamaProvider : API locale, timeout et gestion des erreurs.
- [todo] 2.3 — Conversation CLI avec le provider, sans outil système.

## Phase 3 — Outils

- [todo] 3.1 — Tool, ToolResult et ToolRegistry, avec validation des arguments.
- [todo] 3.2 — `system.info` : hostname, OS, kernel, architecture et uptime.
- [todo] 3.3 — `system.memory` : résultat structuré.
- [todo] 3.4 — `system.disk` : lecture uniquement.
- [todo] 3.5 — `process.list` : nombre de résultats limité.

## Phase 4 — Policy Engine

- [todo] 4.1 — Niveaux de risque READ, CONFIRM et DENY pour chaque outil.
- [todo] 4.2 — Policy Engine : décisions ALLOW, CONFIRM et DENY, avec tests.
- [todo] 4.3 — Confirmation explicite dans le CLI, refus par défaut.

## Phase 5 — LLM et outils

- [todo] 5.1 — Format JSON des appels d'outils, validation stricte.
- [todo] 5.2 — Validation, policy, exécution et retour du résultat au modèle.
- [todo] 5.3 — Boucle limitée à cinq appels d'outils par requête.

## Phase 6 — systemd

- [todo] 6.1 — `systemd.status` en lecture seule.
- [todo] 6.2 — `systemd.list` en lecture seule.
- [todo] 6.3 — `systemd.restart` avec confirmation et validation stricte du service.

## Phase 7 — Diagnostic

- [todo] 7.1 — Prompt système : rôle, outils, résultats réels et permissions.
- [todo] 7.2 — Diagnostic général à partir de plusieurs outils READ.

## Phase 8 — Mémoire

- [todo] 8.1 — Historique SQLite : tâche, timestamp et statut.
- [todo] 8.2 — Historique des outils : arguments non sensibles, résultat et statut.
- [todo] 8.3 — Commande `/history`.

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
