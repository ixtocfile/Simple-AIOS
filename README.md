# Simple-AIOS

Prototype minimal d'une couche intelligente au-dessus de Linux, uniquement en
ligne de commande. Linux reste responsable du système et du matériel.

Le projet fournit un shell interactif minimal, un chargeur de configuration
et des logs applicatifs, sans LLM.

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

Une entrée vide affiche une nouvelle invite. Une entrée inconnue affiche un
message d'aide et laisse le shell ouvert. Ctrl+D (fin d'entrée) ou Ctrl+C
ferment également le shell proprement.

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

## Logs

La bibliothèque standard `logging` écrit en UTF-8, en ajout à
`<data_dir>/logs/simple-aios.log`. Le répertoire est créé à l'initialisation du
logger. Par défaut : `~/.local/share/simple-aios/logs/simple-aios.log`.
Chaque ligne contient la date, l'heure, le niveau et l'événement.

Le démarrage et l'arrêt sont journalisés au niveau INFO ; les erreurs inattendues
au niveau ERROR avec leur type. `/exit`, Ctrl+D et Ctrl+C ferment proprement le
journal. `log_level` filtre les événements : ERROR masque notamment les événements
INFO ; NOTSET inclut tous les niveaux standard.

Le CLI n'enregistre ni les saisies, ni la configuration, ni le texte des exceptions
ou leurs tracebacks, afin de ne pas recopier de mots de passe ou tokens dans les
logs. Une erreur inattendue termine le CLI avec le code 1. Si la configuration
ou le journal ne peut pas être initialisé, le CLI affiche un message sur stderr
et termine également avec le code 1.

## Tests

```bash
python -m pytest -q
```

Les tests fonctionnent sans LLM. Le package n'a aucune dépendance d'exécution ;
pytest est réservé aux tests.

Consulter [ROADMAP.md](ROADMAP.md) pour la progression et [AGENTS.md](AGENTS.md)
pour les règles de contribution. Licence : [MIT](LICENSE).
