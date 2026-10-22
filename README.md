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
La base utilisée par défaut est SQLite pour garantir une démonstration sans installation de serveur : **PostgreSQL n'est pas branché au pipeline**. Les contrôles de distance utilisent notamment IGN et OpenStreetMap. Sur 68 trajets vérifiés, 17 sont validés et 51 restent NON_VERIFIE. NON_VERIFIE signifie distance non fiabilisée, pas une preuve de fraude. Google Maps n'est pas activé dans cette démonstration. Les notifications Slack sont **simulées, non envoyées** sans activation et webhook. Les activités sont **fictives**, et non issues de Strava. Un rapport Power BI `.pbix` doit être créé dans Power BI Desktop à partir des CSV. Il faut également définir les politiques RH de confidentialité, consentement et conservation avant toute mise en production.

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
Le pipeline recharge les activités simulées avec la même graine et **recalcule les CSV**. Il garde un historique des exécutions. Les primes sont calculées selon les règles du POC et les contrôles de distance. Les montants sont théoriques, sans versement réel.

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
Support PDF, rapport Power BI ou equivalent, demonstration en direct et lien GitHub avec le code. Le depot GitHub contient le code source du POC. Les livrables PDF et Power BI doivent etre prepares et verifies separement.

## Résultats de la simulation du POC

Les chiffres suivants proviennent d'une simulation et ne constituent pas des décisions RH réelles.

| Indicateur | Résultat |
|---|---:|
| Salariés étudiés | 161 |
| Activités sportives simulées | 2 777 |
| Salariés théoriquement éligibles aux journées bien-être | 85 |
| Journées bien-être théoriques | 425 |
| Trajets soumis à vérification de distance | 68 |
| Trajets validés | 17 |
| Trajets non fiabilisés | 51 |
| Salariés théoriquement éligibles à la prime | 17 |
| Montant total théorique des primes | 40 990 € |

### Interprétation des contrôles de distance

Parmi les 68 trajets soumis à vérification, 17 sont classés `VALIDE` (25 %) et 51 `NON_VERIFIE` (75 %).

Le statut `NON_VERIFIE` signifie que la distance n'a pas pu être fiabilisée. Il ne constitue pas une preuve de fraude ou de fausse déclaration.

Les calculs de distance s'appuient sur des travaux utilisant les services IGN et OpenStreetMap. L'intégration Google Maps n'est pas activée dans cette démonstration.

Les montants et avantages présentés sont théoriques : aucun versement de prime ni attribution réelle de journées bien-être n'est effectué par ce POC.
