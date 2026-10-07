# Installation de Simple-AIOS sur Ubuntu et Debian

Ce guide utilise les scripts du dépôt et un service systemd **utilisateur**.
Exécutez les commandes avec le compte qui utilisera le CLI ; `sudo` sert
uniquement à préparer les paquets du système. Les exemples placent le dépôt
dans `~/Simple-AIOS`. Docker n'est pas nécessaire.

## 1. Vérifier les prérequis

Simple-AIOS requiert Python **3.12 ou ultérieur**, son module `venv`, Git et
une session Linux disposant d'un gestionnaire systemd utilisateur.

| Distribution | Python fourni par défaut | Prérequis Python du projet |
| --- | --- | --- |
| Ubuntu 24.04 LTS | 3.12 | Satisfait |
| Debian 13 « trixie » | 3.13 | Satisfait |
| Debian 12 « bookworm » | 3.11 | Non satisfait |

Cette table décrit les paquets officiels, pas une certification des tests sur
toutes ces distributions. Sur un autre système, vérifiez la version réelle.
Sur Debian 12, utilisez un environnement disposant de Python 3.12+ et de `venv`
avant de poursuivre ; ne remplacez pas le Python système pour ce projet.

Sur Ubuntu 24.04 ou Debian 13 :

```bash
sudo apt update
sudo apt install git python3 python3-venv curl ca-certificates
python3 --version
python3 -c 'import sys, venv; assert sys.version_info >= (3, 12), "Python 3.12+ requis"'
systemctl --user show-environment >/dev/null
```

Si le dernier contrôle échoue, ouvrez une session locale ou SSH normale avec
votre compte utilisateur et rétablissez l'accès au gestionnaire avant de suivre
le parcours systemd. Les scripts d'installation et de désinstallation refusent
root. Sur une machine sans `sudo`, faites installer les paquets par son
administrateur, puis reprenez avec votre compte habituel.

## 2. Télécharger et installer le projet

Pour un premier clone, avec `~/Simple-AIOS` encore inexistant :

```bash
git clone --branch main https://github.com/ixtocfile/Simple-AIOS.git "$HOME/Simple-AIOS"
cd "$HOME/Simple-AIOS"
python3 scripts/install.py
```

Le script crée ou réutilise `.venv`, y installe le package, puis prépare
`~/.config/systemd/user/simple-aios.service` avec le chemin réel du dépôt.
Si `XDG_CONFIG_HOME` est défini, l'unité se trouve sous
`$XDG_CONFIG_HOME/systemd/user/` ; conservez la même valeur pour la désinstallation.
L'installation peut télécharger les outils de construction Python via pip.
Elle n'installe pas les dépendances de test et ne démarre pas le service.

Gardez le dépôt et son venv à cet emplacement. Une unité existante différente
ou un venv invalide provoque un refus : examinez les fichiers conservés avant
de recommencer. Les restrictions sur les caractères du chemin et les échecs
partiels sont détaillés dans le [README](../README.md#installation).

## 3. Préparer Ollama et le modèle

Ollama est nécessaire pour les conversations et la synthèse de `/diagnose`.
Le CLI local et la consultation `/history` peuvent être vérifiés sans modèle.

Si Ollama n'est pas installé, suivez son
[guide Linux officiel](https://docs.ollama.com/linux), qui couvre l'installation
et les prérequis matériels. Cette installation est distincte de Simple-AIOS.
Réutilisez un serveur Ollama existant s'il correspond à l'URL configurée.

Pour le parcours local par défaut, vérifiez l'API :

```bash
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:11434/api/tags
```

Une réponse JSON contenant `models` confirme que l'API répond. Si aucun serveur
n'est actif, démarrez Ollama suivant son installation ; pour un lancement au
premier plan, gardez `ollama serve` ouvert dans un autre terminal.

Téléchargez ensuite le modèle configuré par défaut dans Simple-AIOS :

```bash
ollama pull qwen3
ollama ls
```

Le modèle `qwen3` doit apparaître dans la liste, éventuellement avec le suffixe
`:latest`. Prévoyez les ressources indiquées sur la
[fiche du modèle](https://ollama.com/library/qwen3). Pour un autre modèle ou
une autre URL Ollama, utilisez la configuration explicite décrite plus bas.

## 4. Démarrer le daemon et vérifier le CLI

Arrêtez d'abord tout `aiosd` lancé manuellement sur le même socket, puis :

```bash
systemctl --user daemon-reload
systemctl --user start simple-aios.service
systemctl --user status simple-aios.service --no-pager
cd "$HOME/Simple-AIOS"
.venv/bin/python -m aios
```

Le service doit être actif. Le CLI affiche :

```text
Simple-AIOS
ai>
```

À l'invite `ai>`, saisissez successivement :

```text
/help
/version
/history
```

`/help` et `/version` sont locales. `/history` vérifie la communication avec le
daemon et la lecture SQLite, sans appel au modèle ; sur une installation neuve,
le résultat attendu est `Historique vide.`. Pour vérifier Ollama, envoyez ensuite
`Bonjour`, puis éventuellement `/diagnose`, qui collecte cinq contrôles READ et
demande une synthèse au modèle.

`/exit` ferme le CLI, pas le daemon. Une action CONFIRM exige de taper `oui`
dans un terminal interactif ; une entrée vide ou l'absence de confirmation
refuse l'action. L'accord ne donne pas au daemon de privilèges supplémentaires.

Pour les sessions suivantes, le CLI reste accessible avec la même commande.
L'activation automatique du daemon dans le gestionnaire utilisateur est
facultative :

```bash
systemctl --user enable simple-aios.service
```

Cela concerne le gestionnaire de votre utilisateur, généralement démarré à
l'ouverture de session. Ce guide ne configure pas son maintien après déconnexion
ni un service système global au démarrage. L'unité a `Restart=no` : un échec
nécessite un diagnostic puis un redémarrage explicite.

## 5. Configuration facultative

Sans option `--config`, le daemon et le CLI utilisent :

```toml
provider = "ollama"
model = "qwen3"
ollama_url = "http://127.0.0.1:11434"
data_dir = "~/.local/share/simple-aios"
log_level = "INFO"
filesystem_roots = ["~/AIOS-Workspace"]
```

Pour créer un fichier personnel en conservant un éventuel fichier existant :

```bash
cd "$HOME/Simple-AIOS"
install -d -m 700 "$HOME/.config/simple-aios"
if [ ! -e "$HOME/.config/simple-aios/config.toml" ] && [ ! -L "$HOME/.config/simple-aios/config.toml" ]; then
    install -m 600 config/example.toml "$HOME/.config/simple-aios/config.toml"
fi
```

Éditez ce fichier avec votre éditeur. `provider` doit rester `ollama` ; `model`
doit correspondre à un modèle disponible sur le serveur choisi. Aucun fichier
TOML n'est chargé automatiquement. Utilisez un `data_dir` absolu ou commençant
par `~/` : le service travaille depuis le répertoire personnel, alors que le
CLI utilise le répertoire courant pour les chemins relatifs.
`filesystem_roots` définit les dossiers autorisés pour les outils fichiers.
Utilisez des chemins absolus ou commençant par `~/` et préparez vous-même ces
dossiers avec les permissions voulues. La liste remplace le défaut ; `[]`
désactive les outils fichiers. Aucun dossier n'est créé par le chargement.

Pour appliquer ce fichier au service de ce guide :

```bash
systemctl --user edit simple-aios.service
```

Ajoutez ce contenu dans la zone éditable du fichier de surcharge :

```ini
[Service]
ExecStart=
ExecStart="%h/Simple-AIOS/.venv/bin/python" -m aios.daemon --config "%h/.config/simple-aios/config.toml"
```

Adaptez le chemin de l'exécutable si le dépôt est ailleurs. La ligne vide
`ExecStart=` remplace la commande d'origine. Puis :

```bash
systemctl --user daemon-reload
systemctl --user restart simple-aios.service
cd "$HOME/Simple-AIOS"
.venv/bin/python -m aios --config "$HOME/.config/simple-aios/config.toml"
```

Le daemon choisit le modèle, l'URL Ollama et les workspaces autorisés ; configurer seulement le CLI ne
reconfigure pas le daemon. Les deux doivent joindre le même socket, par défaut
`<data_dir>/aiosd.sock`. Ils acceptent aussi `--socket PATH` si un chemin explicite
est nécessaire. Une surcharge systemd constitue une personnalisation que le
script de désinstallation préservera en refusant son retrait automatique.

## 6. Fichiers et dépannage

Avec les valeurs par défaut :

| Élément | Emplacement |
| --- | --- |
| Package et Python du projet | `~/Simple-AIOS/.venv/` |
| Unité utilisateur | `~/.config/systemd/user/simple-aios.service` |
| Socket privé (`0600`) | `~/.local/share/simple-aios/aiosd.sock` |
| Historique SQLite | `~/.local/share/simple-aios/history.sqlite3` |
| Logs applicatifs | `~/.local/share/simple-aios/logs/simple-aios.log` |

Commandes de diagnostic en lecture seule :

```bash
systemctl --user status simple-aios.service --no-pager
journalctl --user -u simple-aios.service -n 50 --no-pager
tail -n 50 "$HOME/.local/share/simple-aios/logs/simple-aios.log"
```

| Symptôme | Vérification |
| --- | --- |
| `venv` ou `ensurepip` indisponible | Installer `python3-venv` pour la version utilisée ; refaire le contrôle Python. |
| Python trop ancien | Utiliser Python 3.12+ avec son module `venv` ; ne pas modifier le Python système. |
| Installation refusée sur une unité ou un venv existant | Examiner la personnalisation ou l'installation partielle ; le script préserve les fichiers. |
| Échec de connexion au bus utilisateur | Reprendre une session utilisateur normale disposant de systemd ; ne pas lancer le service avec `sudo`. |
| Impossible de communiquer avec `aiosd` | Vérifier l'état du service, le compte utilisé et le chemin du socket dans les deux programmes. |
| Impossible d'obtenir une réponse du LLM | Vérifier `/api/tags`, le modèle téléchargé et la configuration réellement chargée par le daemon. |
| Chemin du socket trop long | Choisir un chemin Unix plus court avec `--socket` dans les deux programmes. |
| Socket déjà présent après un arrêt brutal | Vérifier qu'aucun daemon ne l'utilise avant de retirer manuellement ce seul socket ; conserver la base et les logs. |

Le serveur traite un client à la fois. Fermez une ancienne session CLI si une
nouvelle semble attendre. L'arrêt normal par `systemctl --user stop` nettoie le
socket. Après correction d'un problème, démarrez explicitement le service ;
aucune demande ou action interrompue n'est rejouée automatiquement.

## 7. Mettre à jour ou désinstaller

Pour une mise à jour, fermez le CLI et arrêtez aussi les daemons manuels :

```bash
systemctl --user stop simple-aios.service
cd "$HOME/Simple-AIOS"
git status --short
```

Avec une copie de travail propre et les personnalisations examinées :

```bash
git pull --ff-only origin main
python3 scripts/install.py
systemctl --user daemon-reload
systemctl --user start simple-aios.service
```

L'installation du package n'est pas éditable : relancez le script après une
mise à jour du code. Si l'unité fournie a changé, l'installateur peut refuser de
remplacer l'unité existante ; examinez les différences avant toute adaptation.

Pour désinstaller avec le compte et l'emplacement d'origine :

```bash
cd "$HOME/Simple-AIOS"
python3 scripts/uninstall.py
```

Le script arrête et désactive le service utilisateur reconnu, retire le package
et l'unité, puis recharge systemd. Il conserve le dépôt, le venv et ses autres
paquets, les configurations, l'historique et les logs. Ollama reste indépendant.

Si vous avez créé une surcharge à l'étape 5, arrêtez d'abord le service,
archivez votre fichier de surcharge hors de `simple-aios.service.d`, puis retirez
uniquement cette personnalisation avant de relancer le script. Toute autre
unité personnalisée nécessite un examen manuel. En cas d'erreur, le script
s'arrête sans annuler les actions déjà effectuées ; les détails figurent dans
le [README](../README.md#désinstallation).

## 8. Vérifications de développement

Depuis le dépôt, pour installer les dépendances de test et lancer la suite :

```bash
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
```

Cette commande passe le package en mode éditable pour le développement. Les
tests utilisent des providers fictifs et des services simulés, avec des sockets
Unix réels pour les échanges entre processus ; un sandbox interdisant ces
sockets empêche leur exécution complète. Aucun modèle n'est requis.

## Sources et limites de validation

Sources officielles consultées le 2 octobre 2026 :

- [Versions Python disponibles sur Ubuntu](https://ubuntu.com/developers/docs/reference/availability/python/).
- [Paquet python3-venv d'Ubuntu 24.04](https://packages.ubuntu.com/noble-updates/python3-venv).
- [Python de Debian 13](https://packages.debian.org/trixie/python3) et [venv](https://packages.debian.org/trixie/python3-venv).
- [Python de Debian 12](https://packages.debian.org/bookworm/python3).
- [Installation Linux d'Ollama](https://docs.ollama.com/linux), [commandes CLI](https://docs.ollama.com/cli) et [API de liste des modèles](https://docs.ollama.com/api/tags).

Les commandes du projet sont fondées sur son code et ses tests. La rédaction de
ce guide ne vaut pas essai complet sur des machines Ubuntu et Debian neuves :
les opérations APT, l'installation d'Ollama, le téléchargement du modèle et le
démarrage sous un gestionnaire systemd actif n'ont pas été exécutés dans cet
environnement de développement.
