# Simple-AIOS

Prototype minimal d'une couche intelligente au-dessus de Linux, uniquement en
ligne de commande. Linux reste responsable du système et du matériel.

Le projet fournit un CLI conversationnel avec Ollama, un chargeur de
configuration, des logs applicatifs et un faux provider pour les tests.

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
Le tour échoué n'est pas ajouté à l'historique ; les échanges précédents sont
conservés. Vous pouvez réessayer en saisissant un nouveau message.

Les réponses du modèle sont affichées comme texte. Aucun outil ni commande
système n'est exécuté.

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

## Tests

```bash
python -m pytest -q
```

Les tests fonctionnent sans LLM. Le package n'a aucune dépendance d'exécution ;
pytest est réservé aux tests.

Consulter [ROADMAP.md](ROADMAP.md) pour la progression et [AGENTS.md](AGENTS.md)
pour les règles de contribution. Licence : [MIT](LICENSE).
