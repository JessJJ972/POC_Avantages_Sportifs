# POC Avantages Sportifs — projet exécutable

## Pourquoi ce projet ?
Sport Data Solution souhaite tester deux avantages : une prime égale à **5 % du salaire annuel brut** pour les salariés utilisant majoritairement un déplacement sportif pour venir au bureau, et **5 journées bien-être** à partir de **15 activités sportives annuelles hors travail**. Le projet doit aussi vérifier les déclarations, produire des indicateurs, documenter les anomalies et préparer l'envoi de nouvelles activités sur Slack.

## Ce qui fonctionne réellement dans cette livraison
- Lecture des **fichiers RH et sportifs fournis** (XLSX), jointure par identifiant salarié.
- Génération reproductible de **12 mois d'activités fictives**, avec dates, durée, type, distance éventuellement absente, et identifiant salarié.
- Base locale **SQLite** créée automatiquement, avec tables salariés, activités, paramètres, contrôles, anomalies, notifications et historique d'exécution.
- Contrôles d'intégrité et tests unitaires, paramètres modifiables, recalcul complet des résultats à chaque lancement.
- **Six fichiers CSV** exploitables dans Power BI : éligibilité, activités, qualité, monitoring, notifications, paramètres.
- Adaptateur facultatif **Google Routes API** et webhook **Slack** (activation explicite, secrets dans variables d'environnement).

## Ce qui reste à faire pour un déploiement réel
La base utilisée par défaut est SQLite pour garantir une démonstration sans installation de serveur : **PostgreSQL n'est pas branché au pipeline**. Sans clé Google Maps, les distances domicile-bureau sont marquées **NON_VERIFIE**, et aucune prime n'est déclarée éligible sur une distance supposée. Les notifications Slack sont **simulées, non envoyées** sans activation et webhook. Les activités sont **fictives**, et non issues de Strava. Un rapport Power BI `.pbix` doit être créé dans Power BI Desktop à partir des CSV. Il faut également définir les politiques RH de confidentialité, consentement et conservation avant toute mise en production.

## Démarrage rapide
Prérequis : Python 3.10 ou supérieur. Aucun module externe n'est nécessaire pour le mode local.

```bash
python src/pipeline.py
python -m unittest discover -s tests -v
```

Les résultats se trouvent dans `data/output/` et la base dans `data/poc_sport.sqlite`.

## Recalculer les avantages
```bash
python src/pipeline.py --prime-rate 0.04 --threshold 20
```
Le pipeline recharge les activités simulées avec la même graine et **recalcule les CSV**. Il garde un historique des exécutions. Le taux de prime est appliqué uniquement aux salariés dont le trajet a été **validé via Google Maps**.

## Intégrations optionnelles

Pour Google Routes API : définir `GOOGLE_MAPS_API_KEY`, activer Routes API et la facturation sur Google Cloud, puis exécuter `python src/pipeline.py --google-maps`. Selon les modes et la couverture de l'API, certains itinéraires vélo peuvent être indisponibles : ils restent **NON_VERIFIE**. Aucune approximation silencieuse.

Pour Slack : définir `SLACK_WEBHOOK_URL`, puis `python src/pipeline.py --slack`. Par sécurité, seule **une activité de démonstration** est envoyée lors d'une exécution, et non tout l'historique. Ne pas utiliser un webhook réel pour des salariés sans validation de la politique de confidentialité.

## Créer le rapport Power BI
1. Ouvrir Power BI Desktop > Obtenir des données > Texte/CSV.
2. Importer `data/output/eligibilite.csv`, `activites.csv`, `qualite.csv`, `monitoring.csv`, `parametres.csv`.
3. Relier `eligibilite.employee_id` (côté 1) à `activites.employee_id` (côté plusieurs).
4. Créer les cartes : nombre de salariés, nombre d'activités, somme `montant_prime_eur`, somme `jours_bien_etre`.
5. Créer les graphiques : activités par sport et par mois, coût des primes par BU, anomalies et statut des exécutions.
6. Pour tester un changement de paramètres, relancer le script, puis cliquer sur **Actualiser** dans Power BI.

## Qualité, confidentialité et limites
Les adresses et salaires RH sont des données sensibles. Les fichiers fournis sont inclus **uniquement pour faciliter une démonstration locale** : **ne jamais publier le dossier `data/input/` ni la base SQLite dans un dépôt GitHub public**. Le `.gitignore` les exclut. Les fichiers CSV de sortie peuvent aussi contenir des informations nominatives et ne doivent pas être publiés. Utiliser un dépôt privé ou des données anonymisées.

## Structure
- `src/pipeline.py` : exécution du traitement complet.
- `tests/test_pipeline.py` : tests unitaires.
- `sql/001_schema_postgres.sql` : proposition de schéma PostgreSQL pour une migration ultérieure.
- `data/input/` : fichiers source locaux (ne pas publier).
- `data/output/` : résultats pour Power BI (ne pas publier).
- `docs/PLAN_SOUTENANCE.md` : scénario de démonstration et limites.

## Livrables attendus par le cahier des charges
Support PDF, rapport Power BI ou équivalent, démonstration en direct et lien GitHub avec le code. **Cette archive fournit le code et des exports ; elle ne crée ni PDF, ni PBIX, ni dépôt GitHub en ligne.**
