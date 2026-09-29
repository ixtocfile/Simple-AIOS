# Simple-AIOS

Prototype minimal d'une couche intelligente au-dessus de Linux, uniquement en
ligne de commande. Linux reste responsable du système et du matériel.

L'étape 0.2 fournit un shell interactif minimal, sans LLM.

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

## Tests

```bash
python -m pytest -q
```

Les tests fonctionnent sans LLM. Le package n'a aucune dépendance d'exécution ;
pytest est réservé aux tests.

Consulter [ROADMAP.md](ROADMAP.md) pour la progression et [AGENTS.md](AGENTS.md)
pour les règles de contribution. Licence : [MIT](LICENSE).
