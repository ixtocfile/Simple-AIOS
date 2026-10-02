# Simple-AIOS

Prototype minimal d'une couche intelligente au-dessus de Linux, uniquement en
ligne de commande. Linux reste responsable du système et du matériel.

Le projet fournit un CLI conversationnel avec Ollama, un chargeur de
configuration, des logs applicatifs et un faux provider pour les tests.
Les six outils de lecture système sont accessibles à la conversation après
validation de l'appel et autorisation par le Policy Engine. `systemd.restart`
permet aussi de redémarrer un service après confirmation explicite dans le CLI.

## Développement

Python 3.12 ou ultérieur est requis. Depuis la racine du dépôt :

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
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
- `/exit` : quitter.

Une entrée vide affiche une nouvelle invite. Une commande inconnue commençant
par `/` affiche un message d'aide et laisse le shell ouvert. Ces commandes
restent locales et ne sont pas envoyées au modèle. Ctrl+D (fin d'entrée) ou
Ctrl+C ferment proprement le shell ; Ctrl+C fonctionne aussi pendant un appel
au provider.

## Conversation

Entrez un message à l'invite `ai>` pour l'envoyer à Ollama. Le serveur doit être
accessible et le modèle configuré déjà installé. Le CLI affiche la réponse,
puis propose une nouvelle invite.

Les échanges réussis sont conservés en mémoire pendant la session et transmis
avec chaque nouveau message pour maintenir le contexte. Ils ne sont ni
journalisés ni sauvegardés et sont oubliés à la fermeture du CLI.

Une erreur Ollama affiche un message sur stderr et rend l'invite disponible.
Si elle survient avant un appel d'outil, le tour échoué n'est pas ajouté à
l'historique. Si l'outil a déjà été traité, son appel et son résultat sont
conservés, même si une réponse suivante du modèle échoue. Les échanges précédents
restent disponibles ; après cette erreur du provider, aucun outil ni appel au
provider n'est relancé automatiquement.

Une réponse contenant un appel JSON strict passe par le circuit d'exécution
décrit ci-dessous. Les autres réponses sont affichées comme texte ; les
commandes shell proposées par le modèle ne sont jamais exécutées.

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

Le CLI prend actuellement en charge uniquement `provider = "ollama"` et utilise
les paramètres `model` et `ollama_url`. Une autre valeur de `provider` produit
un message d'erreur et un code de sortie 1.

## Logs

La bibliothèque standard `logging` écrit en UTF-8, en ajout à
`<data_dir>/logs/simple-aios.log`. Le répertoire est créé à l'initialisation du
logger. Par défaut : `~/.local/share/simple-aios/logs/simple-aios.log`.
Chaque ligne contient la date, l'heure, le niveau et l'événement.

Le démarrage et l'arrêt sont journalisés au niveau INFO ; les erreurs inattendues
et les erreurs du provider au niveau ERROR avec leur type. `/exit`, Ctrl+D et
Ctrl+C ferment proprement le journal. `log_level` filtre les événements : ERROR
masque notamment les événements INFO ; NOTSET inclut tous les niveaux standard.

Le CLI n'enregistre ni les saisies, ni la configuration, ni le texte des exceptions
ou leurs tracebacks, afin de ne pas recopier de mots de passe ou tokens dans les
logs. Une erreur inattendue termine le CLI avec le code 1. Si la configuration
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
son absence produit `Tool execution denied`. Le CLI fournit systématiquement
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

Un outil sans déclaration explicite hérite de `RiskLevel.DENY`. Les six
outils de lecture, `system.info`, `system.memory`, `system.disk`, `process.list`
ainsi que `systemd.status` et `systemd.list`, déclarent `RiskLevel.READ`.
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
La conversation CLI relie validation des arguments, décision de policy,
éventuelle confirmation et exécution, avant de transmettre le résultat au modèle.

## Confirmation dans le CLI

`aios.__main__.authorize_tool_call(policy, tool_name, arguments)` traduit une
décision du Policy Engine en un booléen pour l'appel présenté :

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
Les arguments et réponses de confirmation ne sont pas journalisés. La saisie
de confirmation reste locale ; le modèle reçoit uniquement le résultat structuré
de l'appel, y compris son éventuel refus. Chaque appel réévalue la policy et,
si nécessaire, redemande un accord ; aucun accord n'est mémorisé pour un autre appel.

Ce composant ne valide pas le schéma d'arguments de l'outil et n'exécute aucune
action. Les six outils de lecture sont classés `READ` et `systemd.restart`
exige une confirmation. Le CLI appelle ce composant avec les
arguments déjà validés et normalisés, juste avant l'exécution de l'outil.

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
rien. Le CLI enchaîne les vérifications décrites ci-dessous.

## Exécution d'un appel dans la conversation

Le CLI enregistre `system.info`, `system.memory`, `system.disk`, `process.list`
ainsi que `systemd.status`, `systemd.list` et `systemd.restart` au début de chaque
session, sans les exécuter. Lorsqu'une réponse du modèle est un appel JSON
valide, il suit cet ordre :

1. Rechercher l'outil enregistré et valider ses arguments spécifiques.
2. Appliquer la décision du Policy Engine et demander la confirmation si nécessaire.
3. Exécuter uniquement l'appel autorisé et recueillir son `ToolResult`.
4. Ajouter l'appel de l'assistant et le résultat à la conversation, puis interroger
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

Aucun catalogue ou prompt système n'est encore injecté. Pour essayer le circuit
avec Ollama, demandez par exemple au modèle de répondre uniquement par
`{"tool":"system.info","arguments":{}}`. Le modèle doit respecter ce format
strict. Les tests automatisés utilisent `FakeLLMProvider`, sans vrai LLM.

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
le CLI, avec validation et policy avant chaque consultation.

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
