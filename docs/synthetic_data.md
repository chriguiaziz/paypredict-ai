# Données synthétiques PayPredict AI

Les données sont **entièrement inventées** par `backend/ml/data_generator.py`. Aucune donnée réelle n'est utilisée.
Le générateur est reproductible : même graine (42), mêmes données, prouvé par un hash SHA-256 identique.

## Volumes

| Fichier | Lignes |
| --- | --- |
| customers | 1 000 |
| invoices | 20 000 |
| payments | environ 19 700 |
| ground_truth | 1 000 (jamais chargé en base, jamais donné au modèle) |

Période des factures : du 01/01/2023 au 15/12/2025. Devises : EUR (60 %), USD (25 %), TND (15 %).

## Les 5 profils de clients

Chaque client a un profil caché. Il détermine sa tendance à payer en retard.

| Profil | Part des clients | Tendance au retard | Retard moyen quand en retard | Montants |
| --- | --- | --- | --- | --- |
| reliable (fiable) | 40 % | très faible | 4 jours | normaux |
| occasional (occasionnel) | 28 % | moyenne | 9 jours | normaux |
| chronic (chronique) | 12 % | très forte | 24 jours | un peu plus petits (x0,9) |
| high_value (grand compte) | 10 % | faible | 12 jours | environ 4 fois plus gros |
| new (nouveau) | 10 % | moyenne | 10 jours | plus petits (x0,8) |

Les grands comptes sont toujours du segment Enterprise. Les nouveaux clients s'inscrivent en 2025 et ont moins de factures.

## Comment le retard est décidé

Pour chaque facture, on additionne des facteurs dans un **logit** (échelle log-odds), puis on le convertit en probabilité de retard :

| Facteur | Effet |
| --- | --- |
| Profil du client | tendance de base au retard |
| Bruit propre au client | deux clients du même profil ne sont pas identiques |
| Montant de la facture | les gros montants sont un peu plus souvent en retard |
| Délai de paiement | 15 jours : plus de retards ; 60 jours : moins |
| Saison | octobre, novembre et surtout décembre : plus de retards |
| Changement de comportement | 15 % des clients (hors nouveaux) se dégradent ou s'améliorent à une date donnée |

On tire ensuite au sort le retard selon cette probabilité. Un retard suit une loi gamma (beaucoup de petits retards, quelques gros).

## Statuts et paiements

- 2 % des factures sont annulées (aucun paiement), 3 % sont en litige (rarement payées, et à moitié).
- 94 % des paiements sont en un versement, 6 % en deux versements (pour les montants d'au moins 200).
- Les montants sont calculés en **centimes entiers** : la somme des paiements ne peut jamais dépasser la facture à cause d'un arrondi.
- Le statut « Overdue » n'est jamais écrit : il est calculé par la vue SQL `v_invoice_balances`.

## Date de coupure T = 31/12/2025

Aucun paiement n'est enregistré après T, comme si on observait la base ce jour-là. Les factures dont le paiement tombe après T restent donc impayées dans les données. Ce sont des cas « censurés » : on ne sait pas encore si elles seront payées en retard. Cette règle évite toute fuite d'information du futur dans le modèle.

## Qualité des données

`python -m ml.validate_data` exécute 20 contrôles : volumes, unicité, clés étrangères, dates, montants, absence de surpaiement, cohérence statut / paiements, et plausibilité des profils.
Taux de retard observés : environ 9 % pour les clients fiables, environ 86 % pour les chroniques.
Les tests automatiques (`python -m pytest -q`) vérifient la reproductibilité et la réussite des 20 contrôles.

## Limites

- Les profils suivent des règles simples choisies par l'auteur. Un vrai portefeuille est beaucoup plus bruité.
- Aucun événement externe n'est simulé : faillite, litige commercial, jours fériés locaux, crise économique.
- Les trois devises sont simulées sans taux de change : aucune somme multi-devises n'a de sens.
- Les bonnes performances d'un modèle sur ces données **ne prouvent rien** sur sa performance réelle. Le projet démontre une méthode (pipeline, absence de fuite, traçabilité), pas un résultat métier.