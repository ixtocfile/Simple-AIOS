# Simple-AIOS

Prototype minimal d'une couche intelligente au-dessus de Linux, uniquement en
ligne de commande. Linux reste responsable du système et du matériel.

Le projet fournit un CLI conversationnel avec Ollama, un chargeur de
configuration, des logs applicatifs, un historique SQLite des tâches et appels
d'outils, et un faux provider pour les tests.
Les sept outils de lecture sont accessibles à la conversation après
validation de l'appel et autorisation par le Policy Engine. `systemd.restart`
permet aussi de redémarrer un service après confirmation explicite dans le CLI.
La commande `/diagnose` rassemble cinq lectures pour un bilan général.
Le daemon local `aiosd` expose aussi le Core par un socket Unix privé.

## Installation

Pour le parcours complet, consultez le
[guide d'installation Ubuntu/Debian](docs/installation-ubuntu-debian.md).

Sous Linux, avec Python 3.12 ou ultérieur et son module `venv` disponible,
lancez depuis le dépôt, avec votre compte utilisateur :

```bash
python3 scripts/install.py
```

Le script crée `.venv` dans le dépôt, puis y installe le package avec pip,
sans les dépendances de test. Il prépare l'unité utilisateur dans
`~/.config/systemd/user/simple-aios.service`, ou sous `$XDG_CONFIG_HOME`
si ce chemin absolu est défini. La commande du service utilise directement
le Python de ce venv avec `-m aios.daemon`, au chemin réel du dépôt.
Conservez le dépôt et son venv à cet emplacement.

L'installation utilise les valeurs par défaut existantes. Vos fichiers TOML,
données SQLite et logs sont conservés. Un venv valide et une unité identique
sont réutilisés ; une unité différente, un lien symbolique à ces emplacements
ou un `.venv` invalide provoque un refus avant installation. Les personnalisations
d'une unité existante doivent donc être examinées manuellement.

L'exécution avec root est refusée. Le chemin du dépôt accepte espaces, accents
et `%` ; guillemets, apostrophe, antislash, dollar, accent grave, accolades et
caractères de contrôle sont refusés pour rester compatible avec la construction
du package et systemd. Une erreur de venv ou de pip interrompt l'installation
avant la création de l'unité ; un venv partiellement créé peut rester sur place.
Pip peut accéder au réseau pour récupérer les outils de construction déclarés
dans `pyproject.toml`. Ollama et le modèle configuré sont des prérequis séparés
pour les conversations.

Après installation, démarrez explicitement le daemon, puis ouvrez le CLI :

```bash
systemctl --user daemon-reload
systemctl --user start simple-aios.service
.venv/bin/python -m aios
```

Le script affiche aussi ces commandes, avec le chemin absolu du CLI. Le démarrage
et l'activation du service se font manuellement. L'activation à l'ouverture de
session est décrite dans « Unité systemd utilisateur ». Pour réinstaller après
une mise à jour du dépôt, arrêtez d'abord le daemon, puis relancez le script.

## Désinstallation

Avec le même compte utilisateur et le même `XDG_CONFIG_HOME` qu'à l'installation,
depuis le dépôt utilisé par `scripts/install.py` :

```bash
python3 scripts/uninstall.py
```

Fermez le CLI et arrêtez au préalable tout daemon lancé manuellement. Le script
reconnaît l'unité générée pour ce dépôt, arrête puis désactive
`simple-aios.service` avec `systemctl --user`, désinstalle uniquement le package
`simple-aios` du venv, retire l'unité et recharge le gestionnaire utilisateur.
Le dépôt, le venv et ses autres paquets, les fichiers TOML, l'historique SQLite
et les logs sont conservés. Aucune option de purge des données n'est prévue.

Python 3.12 ou ultérieur est requis, et l'exécution avec root est refusée.
Une unité personnalisée, liée à un autre dépôt, ou des fichiers dans son dossier
local `simple-aios.service.d` provoquent un refus avant toute action. Les liens
symboliques à l'emplacement de l'unité, de ce dossier ou du venv sont également
refusés. Ces installations nécessitent un examen manuel pour préserver leurs
personnalisations. Le Python du venv est vérifié avant toute désinstallation.

Si l'unité existe, un gestionnaire systemd utilisateur accessible est nécessaire.
Un échec d'arrêt ou de désactivation interrompt le script avant le retrait du
package ou de l'unité. Chaque sous-processus a un délai de 30 secondes ; les
erreurs sont signalées avec un code de sortie non nul, sans poursuivre les
actions suivantes. Les actions déjà réussies ne sont pas annulées : si le
rechargement final échoue, relancez `systemctl --user daemon-reload` après avoir
rétabli l'accès au gestionnaire.

Une unité absente n'entraîne aucune commande systemd ; un venv absent n'entraîne
aucun appel à pip. Une nouvelle exécution après désinstallation est sans effet
sur les fichiers conservés. Pour réinstaller, relancez `scripts/install.py`.

## Développement

Python 3.12 ou ultérieur est requis. Depuis la racine du dépôt :

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
aiosd
```

Laissez le daemon ouvert, puis lancez le CLI dans un second terminal, depuis
la racine du dépôt :

```bash
. .venv/bin/activate
python -m aios
```

Sortie attendue :

```text
Simple-AIOS
ai>
```

Commandes disponibles :

- `/help` : afficher l'aide.
- `/version` : afficher la version du package.
- `/diagnose` : diagnostic général en lecture seule, avec synthèse par le modèle.
- `/history` : consulter les 20 dernières tâches et leurs appels d'outils.
- `/exit` : quitter.

Une entrée vide affiche une nouvelle invite. Une commande inconnue commençant
par `/` affiche un message d'aide et laisse le shell ouvert. `/help`, `/version`
et `/exit` restent locales. `/history` consulte le daemon sans appeler le modèle.
Ctrl+D (fin d'entrée) ou Ctrl+C ferment proprement le shell ; Ctrl+C fonctionne
aussi pendant un appel au provider.

## Conversation

Entrez un message à l'invite `ai>` pour l'envoyer au daemon, qui interroge Ollama.
Ollama doit être accessible et le modèle configuré déjà installé. Le CLI affiche la réponse,
puis propose une nouvelle invite.

Les échanges réussis sont conservés en mémoire pendant la session et transmis
avec chaque nouveau message pour maintenir le contexte. Ce contexte est oublié
à la fermeture du CLI. Les demandes, leurs statuts et les appels d'outils sont
persistés dans l'historique SQLite décrit ci-dessous, après filtrage des données
sensibles. Les réponses textuelles du modèle restent en mémoire.

Une erreur Ollama affiche un message sur stderr et rend l'invite disponible.
Si elle survient avant un appel d'outil, le tour échoué n'est pas ajouté
au contexte en mémoire. Si l'outil a déjà été traité, son appel et son résultat sont
conservés, même si une réponse suivante du modèle échoue. Les échanges précédents
restent disponibles ; après cette erreur du provider, aucun outil ni appel au
provider n'est relancé automatiquement.

Une réponse contenant un appel JSON strict passe par le circuit d'exécution
décrit ci-dessous. Les autres réponses sont affichées comme texte ; les
commandes shell proposées par le modèle ne sont jamais exécutées.

## Core et terminal

`aios.core.Core(provider, history, *, registry=None, permission_handler=None)`
porte une session synchrone indépendante du terminal. Il conserve le contexte,
valide les appels, applique la policy et la limite de cinq tentatives, exécute
les outils autorisés et enregistre tâches et résultats dans l'historique.
Par défaut, `build_tool_registry()` fournit les huit outils existants.

- `chat(text)` traite un message non vide et renvoie la réponse textuelle.
- `diagnose()` collecte les cinq contrôles READ et demande leur synthèse.
- `recent_history()` renvoie les dernières tâches et leurs outils sans écrire
  ni modifier le contexte de conversation.

Le Core ne lit aucune entrée, n'affiche rien et ne configure pas les logs.
Le CLI conserve les commandes locales, l'affichage et la confirmation interactive.
Le daemon construit le provider, ouvre `TaskHistory` et fournit ces objets au
Core. Il reste responsable de leur durée de vie et ferme la base à son arrêt.
Chaque instance de Core possède son propre contexte. Les erreurs et
interruptions se propagent à l'appelant après la tentative d'enregistrement
du statut, sans relance automatique.

Le gestionnaire facultatif `permission_handler(decision, name, arguments)`
reçoit une décision calculée par le Core et une copie des arguments validés.
`ALLOW` ne le sollicite pas. Pour `CONFIRM`, seul le booléen `True` autorise
l'action ; sans gestionnaire, elle est refusée. Le gestionnaire peut présenter
un refus `DENY`, mais ne peut pas l'annuler. Le diagnostic reste limité à READ.
Les tests utilisent directement le Core avec `FakeLLMProvider`, des outils
simulés et les opérations de terminal interdites.

## Daemon local `aiosd`

Après installation du package, lancez le serveur en premier plan :

```bash
aiosd
```

`python -m aios.daemon` est équivalent. `--config FILE` charge la configuration
TOML existante ; `--socket PATH` permet de choisir le chemin du socket. Par
défaut, il se trouve dans `<data_dir>/aiosd.sock`, soit
`~/.local/share/simple-aios/aiosd.sock`. Le socket Unix est créé avec les
permissions `0600`, sans écoute TCP. Un chemin trop long pour un socket Unix
doit être remplacé par un chemin plus court avec `--socket`.

Le serveur traite un client à la fois, jusqu'à sa déconnexion. Chaque connexion
crée une session Core distincte ; plusieurs demandes sur cette connexion
partagent leur contexte. Une reconnexion repart sans contexte conversationnel,
mais retrouve l'historique SQLite du même `data_dir`. Le daemon possède la
connexion SQLite et les logs pendant toute sa durée de vie.

Le protocole transporte un objet JSON UTF-8 par ligne, terminé par `\n`.
Les requêtes acceptées ont exactement les champs suivants :

| Requête | Champ `result` en cas de succès |
| --- | --- |
| `{"method":"chat","message":"Bonjour"}` | Réponse textuelle du Core. |
| `{"method":"diagnose"}` | Synthèse des cinq contrôles READ. |
| `{"method":"history"}` | Liste des dernières tâches et de leurs outils. |

La réponse est `{"ok":true,"result":...}` ou `{"ok":false,"error":"..."}`,
également sur une seule ligne. Les caractères de contrôle sont échappés dans
le JSON. La requête est limitée à 65 536 octets, fin de ligne comprise ; le
message de conversation doit être une chaîne non vide. Champs supplémentaires,
doublons, UTF-8 invalide et requêtes incomplètes sont refusés avant le Core.
Une requête invalide produit `Invalid request` et ferme cette connexion.
Une réception de trame déjà entamée ou une écriture bloquée pendant 30 secondes
ferme aussi la connexion. L'attente du premier octet reste sans délai pour
laisser l'utilisateur lire ou saisir sa réponse. Le provider garde son propre timeout.

Les validations, la policy et la limite de cinq appels restent celles du Core.
Par défaut, `CONFIRM` et `DENY` sont refusés. Un client peut ajouter le booléen
`"confirmations":true` à une requête `chat` pour recevoir les demandes d'accord
décrites ci-dessous. Ce champ annonce une capacité ; il n'autorise aucune action.
`DENY` reste toujours refusé, sans demande d'accord.
Une erreur Ollama renvoie `Provider unavailable` et permet de continuer la
session, en conservant les résultats déjà obtenus. Une erreur de stockage ou
interne renvoie `Request failed`, puis arrête le daemon avec le code 1.
Les détails des erreurs et les échanges ne sont pas copiés dans les logs.

Fermer le client ne garantit pas l'annulation d'une demande déjà commencée.
Ses résultats peuvent être persistés même si la réponse n'a pas été reçue ;
le serveur ne relance jamais automatiquement la demande ou ses outils.

Ctrl+C ou `SIGTERM` ferme les ressources et retire le socket créé par ce
processus. Tout chemin déjà présent est refusé au démarrage, y compris un
socket laissé par un arrêt brutal : vérifier que son serveur est arrêté avant
de retirer manuellement ce socket. Le nettoyage préserve un fichier qui aurait
remplacé le socket pendant l'exécution.

Pour vérifier la communication sans appeler Ollama, depuis un autre terminal
avec le daemon démarré et sa configuration par défaut :

```python
import json
from pathlib import Path
import socket

path = Path.home() / ".local/share/simple-aios/aiosd.sock"
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
    client.settimeout(5)
    client.connect(str(path))
    with client.makefile("rb") as stream:
        client.sendall(b'{"method":"history"}\n')
        print(json.loads(stream.readline()))
```

## Unité systemd utilisateur

Le script d'installation prépare une copie de `systemd/simple-aios.service`
adaptée au chemin du dépôt. Elle lance le daemon avec le compte de l'utilisateur,
via `systemctl --user`. Utilisez le même compte pour le CLI.

Pour une installation manuelle, le fichier fourni suppose le dépôt dans
`~/Simple-AIOS`, avec le package déjà installé dans sa `.venv` comme décrit dans
« Développement ». Cette unité exécute directement
`%h/Simple-AIOS/.venv/bin/aiosd` ; `%h` représente le répertoire personnel.
Il n'est pas nécessaire d'activer le venv dans un terminal pour le service.

Depuis la racine du dépôt, copiez l'unité :

```bash
install -d "$HOME/.config/systemd/user"
install -m 0644 systemd/simple-aios.service "$HOME/.config/systemd/user/"
```

Si le dépôt est ailleurs, adaptez `ExecStart` dans la copie installée avant le
démarrage : indiquez le chemin absolu de `.venv/bin/aiosd`, entre guillemets.
Pour une configuration personnalisée, ajoutez `--config` suivi du chemin absolu
d'un fichier TOML existant. Aucun fichier de configuration n'est chargé
automatiquement. Le répertoire de travail est le répertoire personnel ; les
chemins de données relatifs dans le TOML sont donc relatifs à celui-ci.

Arrêtez d'abord tout daemon lancé manuellement sur le même socket, puis :

```bash
systemctl --user daemon-reload
systemctl --user start simple-aios.service
systemctl --user status simple-aios.service
```

Le CLI reste lancé séparément avec `python -m aios`. Par défaut, le service
conserve `~/.local/share/simple-aios` pour les données, les logs et le socket ;
aucun argument supplémentaire n'est requis côté CLI. Si vous changez ces
chemins, configurez le CLI pour joindre le même socket. Ollama reste un service
indépendant, nécessaire seulement aux demandes qui sollicitent le modèle.

Pour lancer l'unité à l'activation du gestionnaire systemd de l'utilisateur :

```bash
systemctl --user enable simple-aios.service
```

Cette activation concerne la session utilisateur, pas un service système
global au démarrage de la machine. `systemctl --user stop simple-aios.service`
envoie `SIGTERM` ; le daemon ferme SQLite et ses logs, puis retire son socket.
Le délai d'arrêt est de 10 secondes avant l'arrêt forcé par systemd. L'unité
ne redémarre pas automatiquement en cas d'échec (`Restart=no`) : après un arrêt
brutal, vérifiez que le daemon est arrêté avant de retirer un éventuel socket
résiduel et de relancer le service. Les données et logs sont conservés.

`UMask=0077` rend les nouveaux fichiers privés au compte, sans modifier les
permissions des fichiers déjà présents. `NoNewPrivileges=yes` empêche les
processus lancés d'acquérir des privilèges supplémentaires à l'exécution.
La policy et les confirmations du CLI restent obligatoires ; l'unité ne
donne aucun droit supplémentaire sur les services du système.

Les tests vérifient la syntaxe avec `systemd-analyze --user verify` lorsque cet
outil est disponible, puis exécutent la commande de l'unité dans un répertoire
temporaire : socket privé, consultation d'historique et arrêt propre. Ils
n'installent ni n'activent de service sur la machine de test. La commande
`systemctl --user start` nécessite une session avec un gestionnaire systemd actif.

## CLI connecté au daemon

`python -m aios` utilise `aios.client.DaemonClient`. La connexion est ouverte
à la première conversation, au premier `/diagnose` ou `/history`, puis réutilisée
jusqu'à la sortie. `/help`, `/version`, `/exit` et les entrées vides ou inconnues
fonctionnent sans daemon. Le CLI ne construit aucun Core ni provider, n'ouvre
pas SQLite et ne lance pas automatiquement `aiosd`.

Les deux programmes acceptent `--config FILE` et `--socket PATH`. Utilisez le
même chemin de socket ; sans `--socket`, il est déduit du `data_dir` de chaque
processus. Le CLI utilise aussi son `log_level`, mais seule la configuration
chargée par `aiosd` choisit le provider, le modèle, l'URL Ollama et la base SQLite.
Modifier le fichier du CLI ne reconfigure pas un daemon déjà démarré.

Une connexion absente, refusée, perdue ou une réponse invalide produit une
erreur générique sur stderr et termine le CLI avec le code 1. La connexion
initiale attend au plus 5 secondes ; les lectures de réponse attendent au plus
600 secondes chacune. Les réponses sont limitées à 16 Mio. Une demande trop
volumineuse est refusée avant envoi et rend l'invite disponible. Une erreur
du provider garde la session ouverte. Aucun échec ne provoque de reconnexion,
de renvoi automatique ou d'exécution locale.

`/exit`, EOF ou Ctrl+C ferme seulement la connexion du CLI. Le daemon reste
actif ; une demande déjà commencée peut continuer et être enregistrée, même
si sa réponse n'est pas reçue. Une nouvelle session repart avec un contexte
vide et peut consulter l'historique persistant.

Pour une action `CONFIRM`, le daemon envoie une trame intermédiaire :

```json
{"event":"confirmation","id":"0123456789abcdef0123456789abcdef","tool":"systemd.restart","arguments":{"service":"demo.service"}}
```

Le CLI présente ces arguments validés et recueille l'accord explicite habituel.
Il répond `{"method":"confirm","id":"...","accepted":true}` ou `false`, avec
l'identifiant reçu. Cet identifiant imprévisible est neuf pour chaque action et
n'est valable que pour la demande en attente sur cette connexion. Le serveur
accepte uniquement un booléen exact et les trois champs attendus. Une réponse
malformée, périmée ou perdue refuse l'action et ferme la connexion après le
traitement en cours. Aucun argument d'exécution n'est repris de cette réponse.
Le diagnostic READ ne demande jamais de confirmation. Le client refuse aussi
les invites invalides, répétées ou dépassant cinq confirmations par requête.

## Historique des tâches

Le daemon utilise `sqlite3`, fourni par Python, pour créer ou ouvrir
`<data_dir>/history.sqlite3`. Par défaut :
`~/.local/share/simple-aios/history.sqlite3`. Chaque demande conversationnelle
et chaque `/diagnose` crée une ligne dans la table `tasks` avant tout appel au
provider ou aux outils. Les entrées vides, commandes inconnues, `/help`, `/version`,
`/history` et `/exit` ne créent aucune tâche.

La table contient `id` (identifiant entier), `task` (demande sans espaces autour),
`timestamp` (début en UTC au format ISO 8601) et `status`. La ligne est validée
immédiatement dans SQLite, puis seul son statut est mis à jour :

| Statut | Signification |
| --- | --- |
| `running` | Traitement commencé, sans statut final enregistré. |
| `completed` | Traitement terminé et réponse finale prête à être affichée. |
| `failed` | Erreur du provider ou erreur inattendue pendant le traitement. |
| `interrupted` | Interruption du Core dans le daemon, notamment SIGINT ou SIGTERM. |

`completed` décrit la fin du traitement par le Core, pas la réussite de toutes
les actions demandées ni l'exactitude du texte du modèle. Une réponse expliquant
un refus, une erreur d'outil, un diagnostic partiel ou la limite de cinq appels
termine aussi le traitement. Un diagnostic entier ou plusieurs appels d'outils
restent une seule tâche. Une erreur Ollama après un outil donne `failed`, même
si cet outil a déjà eu un effet ; aucune action n'est relancée automatiquement.

Les tâches restent disponibles entre sessions sans être réinjectées dans le
contexte du modèle. Un arrêt brutal ou l'impossibilité d'écrire le statut final
peut laisser `running` : la réouverture ne suppose pas que la tâche a réussi
et ne la reprend pas. Si SQLite ne peut pas être initialisé ou écrit, le daemon
s'arrête avec le code 1 et son message d'erreur générique habituel. Une erreur
sur l'insertion initiale empêche tout traitement de cette demande. Les connexions
sont fermées à la sortie ; les requêtes SQL utilisent des paramètres liés.

Le nouveau fichier de base est créé avec les permissions `0600`. Avant toute
écriture, une demande contenant des marqueurs sensibles usuels (`password`,
`token`, `secret`, `api_key`, « mot de passe », clé privée, identifiants dans
une URL ou certains préfixes de tokens) est remplacée intégralement par
`[contenu sensible masqué]`. Ce filtre conservateur peut masquer une demande
anodine et ne détecte pas tous les secrets possibles : ne saisissez pas de secrets
dans les demandes. Le message envoyé au provider reste celui saisi par
l'utilisateur. Les réponses textuelles du modèle, saisies de confirmation,
configuration de l'application et détails des exceptions ne sont pas copiés
dans cette base. Les appels d'outils sont conservés comme décrit ci-dessous.
Le journal applicatif reste sans contenu des échanges.

## Historique des outils

L'étape 8.2 ajoute la table `tool_calls` dans la même base SQLite. Les bases de
l'étape 8.1 sont complétées à l'ouverture, en conservant leurs tâches existantes.
Chaque tentative traitée dans la conversation ou par `/diagnose` possède :

- `id` : identifiant entier de l'appel, utilisable pour conserver son ordre.
- `task_id` : référence à la tâche en cours, contrôlée par SQLite.
- `tool` : nom de l'outil demandé, filtré s'il contient un marqueur sensible.
- `arguments` : arguments demandés au format JSON, après filtrage ; les valeurs
  par défaut ajoutées par le validateur ne sont pas recopiées dans ce champ.
- `timestamp` : début de la tentative en UTC, au format ISO 8601.
- `result` : JSON avec `success`, `data` et `error`, filtré avant écriture.
- `status` : `running`, `succeeded`, `failed` ou `interrupted`.

La tentative `running` est enregistrée avant validation, policy, confirmation
et exécution. Le statut final et le résultat sont enregistrés avant le prochain
appel au modèle. `succeeded` correspond à un `ToolResult.success` vrai ; `failed`
couvre aussi les appels invalides, inconnus ou refusés. Un résultat non
sérialisable est conservé comme l'échec `Invalid tool result` transmis au modèle.
Une interruption propagée dans le Core donne `interrupted`, avec `result` nul :
l'historique n'affirme pas qu'une action commencée a été annulée.

Un JSON d'appel mal formé est enregistré avec `tool` et `arguments` nuls, sans
recopier le texte brut. Le texte ordinaire du modèle ne crée pas d'appel. Les
cinq tentatives du diagnostic ou de la boucle sont liées à leur tâche ; un
sixième appel bloqué par la limite n'est pas traité ni enregistré. Les règles
de validation et de confirmation restent appliquées à chaque tentative.

Les dictionnaires et listes d'arguments et de résultats sont copiés, puis filtrés
récursivement. Les clés sensibles (mots de passe, tokens, clés API, cookies,
identifiants d'authentification, etc.) et leurs valeurs sont remplacées par
`[contenu sensible masqué]`. Plusieurs clés masquées peuvent être regroupées
sous ce marqueur. Les chaînes contenant les marqueurs usuels, une URL avec
identifiants ou une valeur d'authentification `Bearer`/`Basic` sont aussi masquées.
Ce filtre reste heuristique et ne garantit pas la détection de tout secret.
Il ne modifie ni les arguments exécutés ni le résultat envoyé au modèle.

Une erreur du provider après l'outil laisse son résultat enregistré. Un arrêt
brutal ou un échec d'écriture du résultat peut laisser l'appel `running`, avec
une issue inconnue ; aucune reprise ni réexécution automatique n'est effectuée.
Un échec de l'insertion initiale empêche le traitement de cet appel. Comme pour
les tâches, une erreur de stockage termine le daemon et le CLI avec le code 1,
sans enregistrer le détail de l'exception dans les logs. Les appels Python
directs aux outils restent indépendants de cette persistance gérée par le Core.

## Consulter l'historique

Saisissez `/history` sans argument dans le CLI. La commande consulte la base
du `data_dir` du daemon, y compris les sessions précédentes. Elle affiche les
20 dernières tâches, par identifiant décroissant, avec leurs appels d'outils
par identifiant croissant sous chaque tâche. Chaque consultation relit la base.
Si aucune tâche n'est enregistrée, elle affiche `Historique vide.`.

Une ligne `Tâche :` contient l'identifiant, la demande enregistrée, l'horodatage
UTC et le statut. Les lignes `Outil :` associées contiennent l'identifiant de
l'appel, le nom de l'outil, les arguments filtrés, l'horodatage, le résultat
filtré et le statut. Ces lignes sont au format JSON ; les caractères Unicode
et de contrôle sont échappés, pour qu'un texte enregistré ne puisse pas effacer
le terminal ou imiter une nouvelle invite. Les valeurs nulles et les statuts
`running` ou `interrupted` sont affichés tels qu'enregistrés, sans supposer une
réussite. Les données déjà masquées restent masquées.

La consultation passe par le socket local et reste en lecture seule : elle ne crée aucune tâche
ni tentative d'outil, n'exécute aucun outil et ne sollicite pas Ollama. Elle
n'ajoute pas les données consultées au contexte conversationnel. Leur contenu
n'est pas écrit dans les logs applicatifs. Une erreur de lecture SQLite ou
un JSON stocké invalide termine le CLI avec son message générique et le code 1,
sans exposer le détail de l'exception ; les connexions sont fermées.

## Diagnostic général

Saisissez `/diagnose` sans argument dans le CLI. L'application collecte les
cinq lectures suivantes, dans cet ordre, avec les validateurs et le Policy Engine
habituels. Elle n'autorise que la décision `ALLOW` correspondant aux outils READ ;
`CONFIRM`, `DENY` ou une décision inattendue refusent la lecture, sans invite de
confirmation ni exécution.

| Outil | Arguments fixes | Informations consultées |
| --- | --- | --- |
| `system.info` | `{}` | Hôte, OS, noyau, architecture et uptime. |
| `system.memory` | `{}` | RAM disponible, utilisée et pourcentage. |
| `system.disk` | `{"path":"/"}` | Capacité et occupation du système de fichiers de `/`. |
| `process.list` | `{"limit":20}` | Au plus 20 PID et noms courts, triés par PID. |
| `systemd.list` | `{"limit":20}` | Au plus 20 services connus, triés par nom, avec leurs états. |

Chaque contrôle produit un `tool_result`, y compris en cas de refus ou d'erreur.
Un échec n'empêche pas les contrôles suivants : l'absence de systemd, par exemple,
laisse les autres observations disponibles. Les cinq résultats sont transmis
ensemble au provider pour un seul appel de synthèse, après la commande
`/diagnose` dans l'historique. Ils utilisent le même format et le même rôle `user`
que les retours d'outils de la conversation.

Le prompt demande un bilan textuel fondé sur les mesures, distinguant observations,
points à examiner et domaines non évalués. Le disque `/` ne couvre pas tous les
montages, les listes sont bornées et les noms de processus ne mesurent pas leur
charge CPU. Aucun seuil critique ni diagnostic causal n'est calculé par le code.
Les tests vérifient les résultats transmis et le circuit, sans évaluer la qualité
d'une synthèse produite par un LLM réel.

Les cinq tentatives consomment le budget de cette commande. Aucun appel d'outil
supplémentaire demandé par le modèle n'est exécuté, même en lecture seule.
Une réponse commençant par un objet ou tableau JSON est remplacée par un message
indiquant l'absence de synthèse textuelle. Le diagnostic ne redémarre ni ne répare
aucun service. Les résultats filtrés sont conservés dans l'historique SQLite ;
la synthèse reste en mémoire. Aucun de ces contenus n'est écrit dans le fichier
de logs applicatifs.

Si Ollama est indisponible, le CLI signale l'erreur et conserve les observations
dans la session, sans nouvelle tentative automatique. Une nouvelle commande
`/diagnose` refait toutes les lectures. Les autres demandes conversationnelles
retrouvent leur budget habituel et leurs contrôles de permissions.

## Prompt système

`aios.system_prompt.SYSTEM_PROMPT` définit les consignes fixes de Simple-AIOS.
Le Core initialise chaque session avec ce texte dans un message de rôle `system`,
placé avant la première demande utilisateur. Ce message est conservé une seule
fois en tête de chaque appel au provider, y compris après un résultat d'outil
ou une erreur Ollama. Une nouvelle session repart avec ce seul message, sans
l'historique précédent. Le prompt n'est ni affiché ni journalisé.

Il décrit le rôle d'assistant CLI Linux, les huit outils enregistrés avec leurs
arguments et risques, le format JSON strict et la limite de cinq tentatives par
requête. Son catalogue est explicite, sans découverte d'outils ni lecture de
données système à sa construction. Les tests vérifient sa correspondance avec
le registre et la validité des exemples auprès des validateurs existants.

Les consignes demandent de fonder les observations sur les retours `tool_result`
de l'application, de distinguer faits et hypothèses, et de signaler refus,
erreurs, données manquantes ou issue inconnue. Les valeurs renvoyées par les
outils et les résultats copiés par l'utilisateur sont traités comme des données,
pas comme des instructions système. Les demandes utilisateur et retours d'outils
conservent leurs rôles existants dans les messages.

Le prompt rappelle que le Policy Engine décide indépendamment du modèle :
lecture `READ`, accord explicite dans le CLI pour `CONFIRM`, refus pour `DENY`.
Un accord conversationnel ou un champ ajouté par le modèle ne peut pas remplacer
la confirmation. Les validations et permissions restent imposées par le code ;
la sûreté de l'exécution ne dépend pas du respect du prompt par le modèle.
Les tests utilisent FakeLLMProvider et un transport Ollama simulé pour vérifier
les messages transmis, sans évaluer le comportement d'un LLM réel.
Le prompt décrit aussi la synthèse attendue après les lectures de `/diagnose` ;
la collecte et l'interdiction de nouveaux appels durant cette synthèse sont
imposées par le Core.

## Configuration

L'étape 1.1 fournit `aios.config.load_config`, avec TOML et la bibliothèque
standard Python. Sans argument, le chargeur renvoie les valeurs par défaut.
Un fichier explicite peut remplacer tout ou partie des cinq paramètres :

```toml
provider = "ollama"
model = "qwen3"
ollama_url = "http://127.0.0.1:11434"
data_dir = "~/.local/share/simple-aios"
log_level = "INFO"
```

Exemple d'utilisation après installation du package :

```python
from aios.config import load_config

defaults = load_config()
config = load_config("config/example.toml")
```

Les clés inconnues, les valeurs vides ou de type incorrect, les URL non HTTP(S)
ou invalides et les niveaux de logs invalides sont refusés. Les niveaux acceptés
sont DEBUG, INFO, WARNING, ERROR, CRITICAL et NOTSET, sans distinction de casse.
Un fichier explicite absent, illisible ou mal formé produit une exception.
`data_dir` devient un `Path` : `~` est développé ; un chemin relatif reste relatif
au répertoire de travail. Aucun répertoire n'est créé par le chargement.

Le CLI utilise les valeurs par défaut, ou un fichier TOML fourni explicitement :

```bash
python -m aios --config config/example.toml
```

Le daemon charge son fichier avec `aiosd --config config/example.toml` et prend
actuellement en charge uniquement `provider = "ollama"`. Il utilise les paramètres
`model` et `ollama_url`. Une autre valeur de `provider` termine le daemon avec
un message d'erreur et le code 1. Le CLI ne transmet pas sa configuration au daemon.

## Logs

La bibliothèque standard `logging` écrit en UTF-8, en ajout à
`<data_dir>/logs/simple-aios.log`. Le répertoire est créé à l'initialisation du
logger. Par défaut : `~/.local/share/simple-aios/logs/simple-aios.log`.
Chaque ligne contient la date, l'heure, le niveau et l'événement.

Le démarrage et l'arrêt sont journalisés au niveau INFO ; les erreurs inattendues
et les erreurs du provider au niveau ERROR avec leur type. `/exit`, Ctrl+D et
Ctrl+C ferment proprement le journal. `log_level` filtre les événements : ERROR
masque notamment les événements INFO ; NOTSET inclut tous les niveaux standard.

Le fichier de logs ne contient ni les saisies, ni la configuration, ni le texte
des exceptions ou leurs tracebacks, afin de ne pas recopier de mots de passe ou
tokens. Une erreur inattendue termine le CLI avec le code 1. Si la configuration
ou le journal ne peut pas être initialisé, le CLI affiche un message sur stderr
et termine également avec le code 1.

## Interface LLM

`aios.llm.LLMProvider` définit `chat(messages) -> str`. Chaque message est un
dictionnaire avec `role` (`system`, `user` ou `assistant`) et `content` (texte).
Le provider renvoie le texte de l'assistant sans modifier les messages reçus.

`FakeLLMProvider` renvoie une réponse prédéfinie par appel, dans l'ordre :

```python
from aios.llm import FakeLLMProvider, LLMProvider

provider: LLMProvider = FakeLLMProvider(["Bonjour !"])
reply = provider.chat([{"role": "user", "content": "Bonjour"}])
```

Le faux provider conserve une copie de chaque appel dans `calls`, uniquement en
mémoire, et lève `RuntimeError` si ses réponses sont épuisées. Il fonctionne sans
réseau ni modèle installé.

## Provider Ollama

`aios.ollama.OllamaProvider` implémente la même interface avec `urllib` et `json`
de la bibliothèque standard. Il utilise `model` et `ollama_url` de la configuration
pour envoyer un POST à [`/api/chat`](https://docs.ollama.com/api/chat), avec
`stream: false`, puis renvoie le texte `message.content` de la réponse.

```python
from aios.config import load_config
from aios.ollama import OllamaProvider

provider = OllamaProvider(load_config(), timeout=60.0)
reply = provider.chat([{"role": "user", "content": "Bonjour"}])
print(reply)
```

Cet appel nécessite un serveur Ollama accessible et le modèle configuré déjà
installé. La construction du provider n'effectue aucun appel réseau.
Le timeout, positif et fini, vaut 60 secondes par défaut et borne chaque
opération réseau bloquante de connexion ou de lecture.

Les erreurs HTTP, réseau, les dépassements du timeout et les réponses invalides
produisent une `OllamaError`. Les messages d'erreur indiquent la catégorie et,
pour HTTP, le code de statut, sans recopier le corps de réponse ni le détail des
exceptions réseau. Le provider ne journalise pas les échanges et ne réessaie
pas automatiquement les requêtes.

## Contrats d'outils

Le module `aios.tools` fournit quatre éléments indépendants du CLI et du LLM :

- `RiskLevel` : énumération des niveaux `READ`, `CONFIRM` et `DENY`, décrits
  dans la section « Modèle de risque » ci-dessous.
- `Tool` : classe abstraite avec `name`, `description`, `risk_level`,
  `validate_arguments(arguments)` et `_execute(arguments)`. Chaque outil doit
  contrôler les clés obligatoires ou inconnues, les types et les valeurs de ses
  arguments. Le validateur lève une exception en cas d'entrée invalide.
- `ToolResult` : résultat avec `success`, `data` et `error`. Un succès contient
  un dictionnaire de données à clés textuelles et aucune erreur. Un échec
  contient un message d'erreur non vide et aucune donnée. Les combinaisons
  incohérentes sont refusées à la construction.
- `ToolRegistry` : registre vide à la création, avec `register(tool)`,
  `get(name)`, `list_tools()` et `execute(name, arguments)`. Il refuse les noms
  en double, vides ou contenant des espaces, les descriptions vides et les
  niveaux de risque qui ne sont pas des membres de `RiskLevel`.
  La liste conserve l'ordre d'enregistrement ; `get` lève `KeyError` si le nom
  est inconnu.

Les appels passent par `execute`, qui exige un dictionnaire à clés textuelles
et en réalise une copie indépendante avant validation. Le validateur peut
normaliser cette copie, ensuite transmise à `_execute`. Une validation échouée
empêche l'exécution. Un outil inconnu, une exception ordinaire ou un retour de
type incorrect produit un `ToolResult` d'échec avec un message générique.
Les détails des exceptions et les arguments ne sont pas journalisés ;
`KeyboardInterrupt` et `SystemExit` continuent de se propager.

`Tool.execute` et `ToolRegistry.execute` acceptent aussi le paramètre nommé
`authorize`, une fonction recevant une copie des arguments validés. Elle est
appelée après une seule validation et avant l'exécution ; seul un retour
exactement égal au booléen `True` autorise l'action. Un refus produit
`Tool execution denied`, une exception ordinaire `Tool authorization failed`.
Un nom inconnu ou des arguments invalides ne déclenchent pas cette fonction.
La copie présentée à l'autorisation inclut les valeurs normalisées ou par
défaut ; la modifier ne change pas les arguments exécutés.

Les appels Python de confiance peuvent généralement omettre ce paramètre.
`systemd.restart` exige toutefois une fonction d'autorisation, même hors du CLI ;
son absence produit `Tool execution denied`. Le Core fournit systématiquement
cette fonction pour appliquer le Policy Engine et la confirmation utilisateur
à chaque appel du modèle. Le registre lui-même reste indépendant du CLI.

## Modèle de risque

Chaque outil expose un attribut `risk_level`, défini dans son code avec
`aios.tools.RiskLevel`. Cette classification est indépendante des arguments
fournis à l'outil et des réponses du LLM :

| Niveau | Signification |
| --- | --- |
| `RiskLevel.READ` | Consultation en lecture seule. |
| `RiskLevel.CONFIRM` | Action nécessitant une confirmation explicite de l'utilisateur. |
| `RiskLevel.DENY` | Action à refuser. |

Un outil sans déclaration explicite hérite de `RiskLevel.DENY`. Les sept
outils de lecture, `system.info`, `system.memory`, `system.disk`, `process.list`,
`systemd.status`, `systemd.list` et `filesystem.list`, déclarent `RiskLevel.READ`.
`systemd.restart` déclare `RiskLevel.CONFIRM`.
Le registre valide le type du niveau à l'enregistrement : une simple chaîne
comme `"READ"` est refusée. `get` et `list_tools` rendent ce niveau accessible
sans exécuter l'outil.

Le niveau de risque est une métadonnée utilisée par le Policy Engine pour
produire une décision d'autorisation.

## Policy Engine

`aios.policy.PolicyEngine(registry)` reçoit un `ToolRegistry` de confiance.
Sa méthode `evaluate(tool_name)` renvoie un membre de `PolicyDecision` :

| Risque de l'outil enregistré | Décision |
| --- | --- |
| `RiskLevel.READ` | `PolicyDecision.ALLOW` |
| `RiskLevel.CONFIRM` | `PolicyDecision.CONFIRM` |
| `RiskLevel.DENY` | `PolicyDecision.DENY` |
| Outil inconnu, nom de type incorrect ou niveau invalide | `PolicyDecision.DENY` |

Le moteur relit le niveau dans le registre à chaque évaluation. Il n'accepte
pas de niveau de risque ni d'accord utilisateur fournis dans un appel d'outil
ou une réponse du LLM. Les chaînes comme `"READ"` ne remplacent pas les membres
de `RiskLevel` et produisent `DENY` si elles sont introduites après
l'enregistrement.

```python
from aios.policy import PolicyEngine
from aios.system_info import SystemInfoTool
from aios.tools import ToolRegistry

registry = ToolRegistry()
registry.register(SystemInfoTool())
policy = PolicyEngine(registry)
decision = policy.evaluate("system.info")
print(decision.value)  # ALLOW, sans exécuter l'outil
```

Le moteur produit uniquement une décision : il n'exécute aucun outil, ne valide
pas leurs arguments, ne sollicite pas le LLM et ne recueille aucune confirmation.
`CONFIRM` indique qu'un accord explicite reste nécessaire ; cette décision ne
vaut pas accord. Le composant de confirmation CLI est décrit ci-dessous.
Le Core relie validation des arguments, décision de policy,
éventuelle confirmation et exécution, avant de transmettre le résultat au modèle.

## Confirmation dans le CLI

`aios.__main__.authorize_tool_call(decision, tool_name, arguments)` présente la
décision déjà calculée par le Core et renvoie un booléen pour l'appel présenté :

| Décision | Comportement |
| --- | --- |
| `ALLOW` | Renvoie `True` sans demander de saisie. |
| `CONFIRM` | Affiche l'outil et ses arguments, puis demande un accord explicite. |
| `DENY` ou décision inattendue | Affiche « Action refusée. » et renvoie `False` sans saisie. |

Exemple d'invite pour `systemd.restart`, classé `CONFIRM` :

```text
Action à confirmer : {"outil": "systemd.restart", "arguments": {"service": "demo.service"}}
Confirmer cette action ? Tapez oui [oui/NON] :
```

Seule la réponse `oui` est acceptée, sans distinction de casse et après retrait
des espaces autour. Entrée vide, autre réponse, EOF, Ctrl+C ou erreur de lecture
renvoient `False`. Une entrée non interactive, notamment un pipe ou un fichier,
ne peut pas accorder la confirmation. Un appel impossible à représenter pour
l'affichage est également refusé avant toute saisie.

Les caractères de contrôle des noms et arguments sont échappés à l'affichage.
Les arguments et réponses de confirmation ne sont pas écrits dans les logs
applicatifs. Les arguments filtrés figurent dans l'historique des outils. La saisie
de confirmation reste dans le terminal ; seul le booléen d'accord et son
identifiant sont transmis au daemon. Le modèle reçoit uniquement le résultat structuré
de l'appel, y compris son éventuel refus. Chaque appel réévalue la policy et,
si nécessaire, redemande un accord ; aucun accord n'est mémorisé pour un autre appel.

Ce composant ne valide pas le schéma d'arguments de l'outil et n'exécute aucune
action. Les sept outils de lecture sont classés `READ` et `systemd.restart`
exige une confirmation. Le daemon transmet au CLI les arguments déjà validés
et normalisés, puis renvoie son accord au Core juste avant l'exécution de l'outil.

## Format JSON des appels d'outils

`aios.tool_calls.parse_tool_call(text)` valide un appel unique et renvoie un
`ToolCall` avec les attributs `tool` et `arguments`. Le texte doit contenir
exactement un objet JSON de cette forme :

```json
{"tool": "system.disk", "arguments": {"path": "/"}}
```

| Champ obligatoire | Valeur acceptée |
| --- | --- |
| `tool` | Chaîne non vide, imprimable, sans aucun espace ni caractère de contrôle. |
| `arguments` | Objet JSON, éventuellement vide, avec des valeurs JSON usuelles. |

Les deux champs sont obligatoires ; aucun autre champ n'est accepté à la racine,
y compris `risk_level` ou `confirmed`. L'ordre des clés et les espaces JSON
autour de l'objet sont libres. Le nom de l'outil n'est ni corrigé ni normalisé.

La validation s'appuie sur le module
[`json` de Python](https://docs.python.org/3.12/library/json.html). Elle refuse
les clés dupliquées à tous les niveaux, `NaN`, les infinis et les débordements
lors de la conversion en flottant. Un tableau d'appels, du texte autour du
JSON, un bloc Markdown ou plusieurs objets successifs sont refusés : le parseur
ne tente pas d'extraire ou de réparer un appel.

Le texte est limité à 65 536 caractères avant décodage. La profondeur maximale
est de 32 niveaux d'objets ou de tableaux ; l'objet racine et `arguments`
occupent déjà deux niveaux. Une entrée invalide produit une `ToolCallError`
(sous-classe de `ValueError`) avec le message générique `Invalid tool call`,
sans recopier le texte reçu ni le journaliser.

```python
from aios.tool_calls import parse_tool_call

call = parse_tool_call('{"tool":"process.list","arguments":{"limit":10}}')
print(call.tool)       # process.list
print(call.arguments)  # {'limit': 10}
```

Ce parseur valide le format de l'appel. Il ne recherche pas l'outil dans le
registre et ne valide pas ses arguments spécifiques : un nom inconnu ou des
arguments inadaptés à un outil peuvent donc passer cette validation de format.
Il n'accorde aucune autorisation, ne demande aucune confirmation et n'exécute
rien. Le Core enchaîne les vérifications décrites ci-dessous.

## Exécution d'un appel dans la conversation

Le Core enregistre `system.info`, `system.memory`, `system.disk`, `process.list`
ainsi que `systemd.status`, `systemd.list`, `systemd.restart` et `filesystem.list`
au début de chaque session, sans les exécuter. Lorsqu'une réponse du modèle est un appel JSON
valide, il suit cet ordre :

1. Enregistrer la tentative et ses arguments filtrés dans l'historique SQLite.
2. Rechercher l'outil enregistré et valider ses arguments spécifiques.
3. Appliquer la décision du Policy Engine et demander la confirmation si nécessaire.
4. Exécuter uniquement l'appel autorisé et recueillir son `ToolResult`.
5. Enregistrer le résultat filtré et le statut de l'appel dans SQLite.
6. Ajouter l'appel de l'assistant et le résultat à la conversation, puis interroger
   le modèle à nouveau. Une réponse textuelle est affichée ; un nouvel appel JSON
   reprend ces vérifications dans la limite décrite ci-dessous.

Le résultat est un message JSON généré par l'application, avec le rôle `user`
pour conserver le contrat textuel de `LLMProvider`. Il contient `tool_result`
avec le nom de l'outil et les trois champs `success`, `data` et `error`. Exemple
de retour pour un outil inconnu :

```json
{"tool_result":{"tool":"unknown.tool","success":false,"data":null,"error":"Unknown tool"}}
```

Un appel inconnu, des arguments invalides, un refus ou une erreur d'exécution
produisent également un retour au modèle, sans données partielles ni détails
d'exception. Un résultat impossible à sérialiser en JSON produit
`Invalid tool result`, sans réexécuter l'outil.

Après les espaces initiaux, une réponse commençant par `{` ou `[` est traitée
comme une tentative d'appel structuré. Si son format est invalide, le modèle
reçoit `Invalid tool call` avec `tool: null`, sans consultation du registre ni
exécution. Le texte ordinaire et les exemples JSON dans du texte ou des blocs
Markdown restent affichés tels quels ; aucun appel n'en est extrait.

La boucle traite au plus **cinq appels d'outils par requête utilisateur**. Les
tentatives au format invalide, les outils inconnus, les arguments invalides,
les refus et les erreurs comptent également dans cette limite. Chaque appel
revalide les arguments et réévalue la policy ; une confirmation précédente
n'autorise jamais l'appel suivant. Le compteur repart à zéro pour chaque nouveau
message saisi à `ai>`.

Après le cinquième résultat, un dernier appel au modèle permet d'obtenir une
réponse textuelle. Une nouvelle tentative d'appel structuré n'est ni validée,
ni confirmée, ni exécutée : le CLI affiche « Limite de 5 appels d'outils atteinte
pour cette requête. » et rend l'invite disponible. Ce message remplace l'appel
bloqué dans l'historique, qui conserve les cinq appels traités et leurs résultats.
Une requête entraîne donc au plus six appels au provider. Une réponse textuelle
ou une erreur du provider arrête la boucle plus tôt.

Le prompt système fournit désormais le catalogue et des exemples d'appels au
modèle. Celui-ci doit respecter le format strict, vérifié par l'application.
Les tests automatisés utilisent `FakeLLMProvider`, sans vrai LLM.

## Premier outil : system.info

`aios.system_info.SystemInfoTool` lit les informations de base du système Linux.
Il accepte uniquement un dictionnaire d'arguments vide (`{}`) et utilise
[os.uname()](https://docs.python.org/3.12/library/os.html#os.uname) ainsi que
[/proc/uptime](https://docs.kernel.org/filesystems/proc.html), en lecture seule,
sans commande shell ni dépendance supplémentaire.

Le `ToolResult` réussi contient ces champs dans `data` :

| Champ | Valeur |
| --- | --- |
| `hostname` | Nom de la machine fourni par le système. |
| `os` | Nom du système d'exploitation, par exemple `Linux`. |
| `kernel` | Version du noyau (`release` de `os.uname()`). |
| `architecture` | Identifiant matériel, par exemple `x86_64` ou `aarch64`. |
| `uptime_seconds` | Durée depuis le démarrage, en secondes, sous forme de flottant. |

Utilisation depuis Python, après installation du package :

```python
from aios.system_info import SystemInfoTool
from aios.tools import ToolRegistry

registry = ToolRegistry()
registry.register(SystemInfoTool())
result = registry.execute("system.info", {})
print(result)
```

Les informations sont relues à chaque appel. Les arguments inattendus sont
refusés avant toute lecture. Si les données sont inaccessibles ou si l'uptime
est invalide (notamment négatif ou non fini), l'outil renvoie un échec générique
sans données partielles ni détails d'exception. Il reste indépendant du CLI
et du LLM.

## Outil mémoire : system.memory

`aios.system_memory.SystemMemoryTool` lit la RAM exposée par
[/proc/meminfo](https://docs.kernel.org/filesystems/proc.html#meminfo), en lecture
seule et sans commande externe. Il accepte uniquement `{}`. Les tailles sont
des entiers en octets : les valeurs `kB` du noyau sont multipliées par 1024.

Le `ToolResult` réussi contient ces champs dans `data` :

| Champ | Valeur |
| --- | --- |
| `total_bytes` | RAM utilisable totale (`MemTotal`). |
| `free_bytes` | RAM libre (`MemFree`). |
| `available_bytes` | Estimation de la RAM disponible pour de nouvelles applications sans swap (`MemAvailable`). |
| `used_bytes` | Utilisation estimée : `total_bytes - available_bytes`. |
| `used_percent` | `used_bytes / total_bytes × 100`, arrondi à deux décimales. |

La mémoire disponible tient notamment compte de mémoire récupérable dans les
caches. Le calcul de l'utilisation s'appuie donc sur `MemAvailable`.

```python
from aios.system_memory import SystemMemoryTool
from aios.tools import ToolRegistry

registry = ToolRegistry()
registry.register(SystemMemoryTool())
result = registry.execute("system.memory", {})
print(result)
```

Chaque appel relit les données. Les trois champs du noyau sont obligatoires ;
une valeur manquante, dupliquée, mal formée ou incohérente, ou une lecture
impossible, produit un échec générique sans données partielles. Les arguments
sont refusés avant toute lecture. L'outil reste indépendant du CLI et du LLM.

## Outil disque : system.disk

`aios.system_disk.SystemDiskTool` consulte la capacité du système de fichiers
contenant un chemin, avec
[shutil.disk_usage](https://docs.python.org/3.12/library/shutil.html#shutil.disk_usage).
La consultation est en lecture seule, sans commande externe ni dépendance
supplémentaire.

L'argument optionnel `path` vaut `/` par défaut. Il doit être une chaîne
représentant un chemin absolu, sans caractère nul, vers un fichier ou dossier
existant. Les autres arguments sont refusés avant toute consultation.

Le `ToolResult` réussi contient ces champs dans `data` :

| Champ | Valeur |
| --- | --- |
| `path` | Chemin interrogé. |
| `total_bytes` | Capacité totale du système de fichiers, en octets. |
| `used_bytes` | Espace utilisé, en octets. |
| `free_bytes` | Espace disponible pour un utilisateur non privilégié sous Linux, en octets. |
| `used_percent` | `used_bytes / total_bytes × 100`, arrondi à deux décimales. |

Les blocs réservés peuvent expliquer que `used_bytes + free_bytes` soit inférieur
à `total_bytes`. Si la capacité signalée est nulle, le pourcentage vaut `0.0`.

```python
from aios.system_disk import SystemDiskTool
from aios.tools import ToolRegistry

registry = ToolRegistry()
registry.register(SystemDiskTool())
result = registry.execute("system.disk", {})
print(result)
```

Pour cibler un autre volume, passez par exemple `{"path": "/mnt/data"}`.
Chaque appel relit les statistiques. Un chemin inaccessible ou des statistiques
invalides produisent un échec générique, sans données partielles ni détails
d'exception. L'outil reste indépendant du CLI et du LLM.

## Outil processus : process.list

`aios.process_list.ProcessListTool` liste les processus Linux visibles dans
`/proc`, en lecture seule et sans commande externe ni dépendance supplémentaire.
L'argument optionnel `limit` vaut 20 par défaut : il doit être un entier de 1 à
100, sans accepter les booléens. Les autres arguments sont refusés avant toute
lecture.

Le `ToolResult` réussi contient `data["processes"]`, une liste triée par PID
croissant, avec au plus `limit` éléments. Chaque élément contient :

| Champ | Valeur |
| --- | --- |
| `pid` | Identifiant entier du processus. |
| `name` | Nom court fourni par `/proc/<pid>/comm`. |

Le [nom court du noyau](https://man7.org/linux/man-pages/man5/proc_pid_comm.5.html)
peut être tronqué. Les octets non valides en UTF-8 sont remplacés lors du décodage.
Les arguments de commande et les variables d'environnement ne sont pas lus.

```python
from aios.process_list import ProcessListTool
from aios.tools import ToolRegistry

registry = ToolRegistry()
registry.register(ProcessListTool())
result = registry.execute("process.list", {"limit": 10})
print(result)
```

Chaque appel relit les processus. Ceux qui disparaissent ou dont la lecture est
refusée sont ignorés sans consommer la limite ; la lecture des noms s'arrête dès
que celle-ci est atteinte. La liste peut être vide et ne constitue pas un
instantané atomique. Si `/proc` ne peut pas être énuméré, ou si une autre erreur
de lecture survient, l'outil renvoie un échec générique sans données partielles.
Il reste indépendant du CLI et du LLM.

## Outil systemd : systemd.status

`aios.systemd_status.SystemdStatusTool` consulte l'état d'un service du
gestionnaire systemd système local. Il est classé `READ` et enregistré dans
le Core, avec validation et policy avant chaque consultation.

Son seul argument, obligatoire, est `service` : un nom complet avec le suffixe
`.service`, limité à 255 caractères ASCII. Le nom commence par une lettre ou
un chiffre, puis accepte les lettres, chiffres, points, tirets, underscores et
deux-points. Une instance explicite après un unique `@` est acceptée avec les
mêmes règles, par exemple `openvpn-server@server.service`. Les noms abrégés,
templates sans instance, chemins, motifs glob, caractères échappés et arguments
supplémentaires sont refusés avant de lancer un processus.

Exemple d'appel JSON dans une réponse du modèle :

```json
{"tool":"systemd.status","arguments":{"service":"ssh.service"}}
```

Le `ToolResult` réussi contient ces champs dans `data` :

| Champ | Valeur |
| --- | --- |
| `service` | Nom complet demandé, inchangé. |
| `load_state` | État de chargement, par exemple `loaded` ou `masked`. |
| `active_state` | État d'activité, par exemple `active`, `inactive` ou `failed`. |
| `sub_state` | État détaillé, par exemple `running`, `dead` ou `start-pre`. |

Un service inactif, en échec ou masqué reste une consultation réussie : son état
est décrit dans les données. Chaque appel interroge à nouveau systemd.

L'outil utilise
[`systemctl show`](https://github.com/systemd/systemd/blob/main/man/systemctl.xml)
avec seulement les propriétés `LoadState`, `ActiveState` et `SubState`. La
commande est fixe, transmise à `subprocess.run` sous forme de liste avec
`shell=False`. Elle cible le gestionnaire système, désactive le pager et les
demandes de mot de passe, ferme l'entrée standard et impose un timeout de cinq
secondes. Aucun journal, environnement ou contenu de commande de service n'est
demandé ; la sortie d'erreur de `systemctl` est écartée.

Un service introuvable, l'absence de `systemctl` ou de systemd, un accès refusé,
un timeout, un code de sortie non nul ou des propriétés invalides produisent
`ToolResult(success=False, error="Tool execution failed")`, sans données
partielles ni détails d'exception. Les erreurs ne déclenchent pas de commande
de remplacement. L'outil utilise les droits du processus courant, sans `sudo`.

## Outil systemd : systemd.list

`aios.systemd_list.SystemdListTool` liste les unités `.service` connues du
gestionnaire systemd système local, y compris celles inactives ou en échec.
Il utilise
[`systemctl list-units --type=service --all`](https://github.com/systemd/systemd/blob/main/man/systemctl.xml).
Cette liste concerne les unités présentes en mémoire ; elle ne constitue pas
un inventaire de tous les fichiers de services installés.

L'argument optionnel `limit` vaut 20 par défaut et accepte un entier de 1 à 100,
sans booléen. Tout autre argument est refusé avant de lancer un processus.
L'outil est classé `READ` et disponible dans la conversation :

```json
{"tool":"systemd.list","arguments":{"limit":10}}
```

Le résultat contient `data["services"]`, une liste triée par nom, avec au plus
`limit` entrées. Chaque entrée contient `service`, `load_state`, `active_state`
et `sub_state`, comme le résultat de `systemd.status`. Les noms sont conservés
tels que signalés par systemd, y compris les instances et les séquences échappées
`\xHH`. Ces dernières restent hors du format d'entrée accepté par
`systemd.status` et `systemd.restart`.
Le booléen `data["truncated"]` indique si d'autres services ont été omis à cause
de la limite. Une liste vide est un succès, avec `truncated` à `false`.

Chaque appel relit les données avec une commande fixe sans shell, sans pager
ni demande de mot de passe et avec un timeout de cinq secondes. L'affichage
est sans en-têtes, puces ou troncature des noms ; la locale est fixée à `C`,
les couleurs et liens de terminal sont désactivés pour ce processus uniquement.
Seules les quatre premières colonnes sont conservées ; les descriptions et
éventuelles informations de jobs ne sont pas renvoyées au modèle ni journalisées.

Toutes les lignes sont validées avant de limiter le résultat. Des lignes
mal formées ou dupliquées, un binaire absent, un accès refusé, un timeout ou
un code de sortie non nul produisent un échec générique `Tool execution failed`,
sans liste partielle, détail d'exception, nouvelle tentative ou commande de
remplacement. Les tests utilisent un `systemctl` simulé et FakeLLMProvider.

## Outil systemd : systemd.restart

`aios.systemd_restart.SystemdRestartTool` redémarre un seul service du
gestionnaire systemd système local. Il est classé `CONFIRM` et enregistré dans
le CLI. Selon le comportement de
[`systemctl restart`](https://github.com/systemd/systemd/blob/main/man/systemctl.xml),
un service arrêté sera démarré.

Le seul argument autorisé, obligatoire, est `service`. Il suit le même format
strict que `systemd.status` : nom ASCII explicite terminé par `.service`, au
plus 255 caractères, instance nommée facultative. Noms abrégés, templates sans
instance, chemins, motifs glob, espaces, caractères échappés, options et
arguments supplémentaires sont refusés avant la confirmation et l'exécution.

```json
{"tool":"systemd.restart","arguments":{"service":"demo.service"}}
```

Le CLI affiche l'outil et le service, puis exige `oui` dans un terminal
interactif. Une réponse vide, négative, ambiguë, EOF ou Ctrl+C refuse l'action.
L'accord reste propre à cet appel, même si le modèle redemande le même service.
Un champ `confirmed` fourni par le modèle est invalide et ne vaut jamais accord.
Les appels Python directs doivent aussi fournir `authorize`, dont le retour
doit être exactement `True` ; cette fonction reste du code de confiance chargé
de recueillir l'accord.

Après autorisation, une seule commande fixe est lancée sous forme de liste :
`systemctl --system --no-pager --no-ask-password restart -- SERVICE`.
Elle utilise `shell=False`, les droits du processus courant, sans `sudo`, et
des entrées/sorties reliées à `DEVNULL`. Elle attend la fin du job, avec un
timeout de 30 secondes. Un succès renvoie
`{"service": "demo.service", "restarted": true}` dans `data` : `systemctl` a
terminé avec le code zéro. Ce résultat ne constitue pas un contrôle de santé
du service ; son état peut être consulté séparément avec `systemd.status`.

Un binaire absent, un refus de permission ou un code de sortie non nul produit
`Tool execution failed`, sans détail sensible. Un timeout produit
`Service restart timed out; outcome unknown` : l'arrêt du client `systemctl`
ne permet pas de conclure à l'annulation du job côté systemd. L'outil ne réessaie
pas et ne lance aucune commande de remplacement. Les tests simulent tous les
redémarrages et utilisent FakeLLMProvider ; aucun service réel n'est redémarré.

## Outil fichiers : filesystem.list

`aios.filesystem_list.FilesystemListTool` liste uniquement le contenu immédiat
d'un dossier du workspace fixe `~/AIOS-Workspace`, sous le compte exécutant
`aiosd`. Il est enregistré dans le Core et décrit au modèle. Son niveau est
`READ` ; le Policy Engine doit autoriser chaque appel avant tout accès au disque.

Le workspace doit déjà exister : l'outil ne crée ni dossier ni fichier. Pour le
préparer manuellement avec le compte du daemon :

```bash
mkdir -p "$HOME/AIOS-Workspace"
```

`path` est facultatif, avec `"."` par défaut. Il désigne le workspace ou un
sous-dossier, toujours relativement à ce workspace, indépendamment du répertoire
courant du CLI. Exemple pour un sous-dossier `documents` existant :

```json
{"tool":"filesystem.list","arguments":{"path":"documents"}}
```

Seul `path` est accepté. Le chemin doit être une chaîne UTF-8 non vide d'au plus
4096 octets, sans caractère de contrôle, antislash ni composant `..`, vide ou
`.` (sauf le chemin `"."` lui-même). Les chemins absolus sont refusés. Il n'y a
ni expansion du tilde, ni glob, ni shell.

La racine, ses ancêtres et les sous-dossiers doivent être de vrais dossiers,
sans lien symbolique. Chaque composant est ouvert relativement au descripteur
de son parent, sans suivre les liens ; les métadonnées sont également lues
relativement au dossier ouvert. Les liens présents dans une liste sont signalés
comme tels, sans consulter leur cible. L'outil ne lit pas le contenu des fichiers,
ne parcourt pas les sous-dossiers et n'exécute aucune commande externe.

Le résultat `data` contient :

- `path` : le chemin relatif demandé, ou `"."` ;
- `entries` : une liste de `name`, `type` et `size_bytes` ;
- `truncated` : vrai lorsqu'il reste des entrées au-delà de la limite.

`type` vaut `file`, `directory`, `symlink` ou `other` pour les fichiers spéciaux.
`size_bytes` est la taille en octets d'un fichier ordinaire, et `null` sinon.
Les noms cachés sont inclus. L'outil examine au plus 101 entrées et renvoie les
100 premières, triées entre elles par nom ; le sous-ensemble sélectionné dépend
de l'ordre du système de fichiers. Il ne constitue pas un instantané atomique.
Un dossier vide renvoie une liste vide et `truncated=false`.

Un workspace absent, un chemin inexistant, un fichier utilisé comme dossier,
un lien dans le chemin ou une erreur d'accès produit un échec structuré sans
données partielles ni détails sensibles dans les erreurs ou les logs.
La racine et la limite sont fixes à cette étape ; leur configuration reste
prévue en phase 12. La commande `/diagnose` conserve ses cinq contrôles existants.

## Tests

```bash
python -m pytest -q
```

Les tests fonctionnent sans LLM et simulent `systemctl`, sans exiger systemd.
Le package n'a aucune dépendance Python d'exécution ; pytest est réservé aux
tests. L'utilisation réelle des trois outils `systemd` nécessite `systemctl`
dans le `PATH` et un gestionnaire systemd système local accessible.
`systemd.restart` exige en plus les permissions système de redémarrer le service.

Consulter [ROADMAP.md](ROADMAP.md) pour la progression et [AGENTS.md](AGENTS.md)
pour les règles de contribution. Licence : [MIT](LICENSE).
