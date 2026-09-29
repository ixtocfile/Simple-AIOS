# Consignes pour les agents

## Périmètre

- Travailler uniquement dans `ixtocfile/Simple-AIOS`.
- Lire `ROADMAP.md` et examiner l'état Git avant toute modification.
- Implémenter uniquement l'étape explicitement demandée par l'utilisateur.
  Ne pas enchaîner avec l'étape suivante.
- Préférer simplicité, lisibilité et bibliothèque standard Python 3.12+.
- La V0.1 est une couche au-dessus de Linux, exclusivement en ligne de commande.
  Ne pas créer de noyau, d'interface graphique ou Web.
- Ne pas anticiper les étapes futures : aucun dossier vide, framework agentique,
  service ou dépendance sans besoin actuel. Docker ne doit pas être obligatoire.

## Sécurité à préserver au fil des étapes

- Aucun shell root ni commande shell arbitraire à disposition du LLM.
- Les outils futurs utilisent des arguments validés et des résultats structurés.
- Le Policy Engine décide des autorisations indépendamment du modèle : READ
  peut être autorisé, CONFIRM exige l'accord explicite de l'utilisateur, DENY
  refuse l'action. Ne pas exécuter d'outil demandé par le LLM sans cette vérification.
- Ne jamais journaliser volontairement de mot de passe, token ou secret.
- Les tests ne doivent pas nécessiter de vrai LLM. Introduire FakeLLMProvider
  à l'étape 2.1, puis l'utiliser pour les tests concernés.

## Validation et commits

- Installer le projet dans un environnement virtuel :
  `python -m pip install -e '.[test]'`.
- Ajouter ou adapter les tests concernés, puis exécuter `python -m pytest -q`.
- Vérifier `python -m aios` pour l'étape 0.1.
- Mettre à jour `ROADMAP.md` et la documentation nécessaire après validation.
- Garder des commits petits, limités à une modification logique. Préserver tout
  travail existant et ne pas réécrire l'historique sans instruction explicite.
- Pour l'étape 0.1, créer un seul commit :
  `chore: initialize simple-aios project`, puis s'arrêter.
- Terminer par un bref bilan : fichiers modifiés, tests et résultats, hash et
  message du commit, prochaine étape prévue sans l'implémenter.
