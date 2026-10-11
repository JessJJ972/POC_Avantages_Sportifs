# Démonstration guidée (10 à 15 minutes)

1. **Contexte** : expliquer les deux avantages sportifs et les objectifs du POC.
2. **Sources** : présenter la structure des deux fichiers Excel sans divulguer de données personnelles à l'écran.
3. **Traitement** : exécuter `python src/pipeline.py` et montrer le nombre de salariés et d'activités.
4. **Qualité** : exécuter `python -m unittest discover -s tests -v`, ouvrir `qualite.csv` et expliquer les contrôles.
5. **Monitoring** : ouvrir `monitoring.csv` et montrer la trace SUCCESS des traitements.
6. **Calculs** : ouvrir `eligibilite.csv` et montrer les activités annuelles, le seuil des 15 activités et les 5 jours bien-être.
7. **Transparence** : expliquer que la prime reste à zéro sans distance vérifiée par Google Maps ; ne pas présenter ce zéro comme le coût final de la politique.
8. **Paramètres** : exécuter `python src/pipeline.py --threshold 20 --prime-rate 0.04`, puis comparer les résultats et actualiser Power BI.
9. **Slack** : montrer `notifications.csv` et le statut SIMULATION_NON_ENVOYEE, puis expliquer l'activation possible par webhook.
10. **Conclusion** : distinguer le prototype local des étapes nécessaires à la production (PostgreSQL, Google Maps, Slack, sécurité, véritable rapport Power BI).
