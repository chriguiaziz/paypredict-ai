# Documentation du modèle de prédiction de retard de paiement

PayPredict AI, phase 2. Les chiffres ci-dessous sont ceux d'une exécution sur les données synthétiques de la phase 1 (graine 42). Les tiens seront proches, pas forcément identiques : remplace-les par ceux de ton propre `metadata.json`.

> **Avertissement :** toutes les métriques sont calculées sur des **données synthétiques**. Elles démontrent une méthode (pipeline sans fuite, évaluation honnête, traçabilité), pas une performance sur des factures réelles.

## 1. La question posée au modèle

« À la date où cette facture est émise, sera-t-elle soldée après son échéance ? »

- **Date de prédiction** : la date d'émission de la facture.
- **Cible** : `will_be_late` (1 = soldée en retard, 0 = soldée à temps).
- Tout ce que le modèle voit doit avoir été connu **avant** cette date.

## 2. Définition de la cible et règle de labellisation

On étiquette à la date de coupure T = 31/12/2025.

| Situation observée à T | will_be_late | Issue connue à partir du |
| --- | --- | --- |
| Soldée à temps (au plus tard à l'échéance) | 0 | date du dernier paiement |
| Soldée en retard | 1 | lendemain de l'échéance |
| Non soldée et échéance déjà dépassée | 1 | lendemain de l'échéance |
| Émise après T moins 60 jours | **exclue** (censurée) | jamais dans ce jeu |
| Annulée, brouillon ou en litige | **exclue** | jamais dans ce jeu |

**Pourquoi exclure les 60 derniers jours, même les factures déjà payées ?** Garder seulement celles déjà payées reviendrait à ne garder que les bonnes payeuses : le taux de retard des dernières semaines serait artificiellement bas. 60 jours est le délai de paiement maximum du jeu de données : au-delà, toutes les échéances sont passées et l'issue est certaine.

Résultat : 17 926 factures étiquetées, dont environ 32,4 % en retard.

## 3. Les variables (19 au total)

Toutes sont calculées à la date d'émission P, avec ce qui était connu avant P.

| Groupe | Variable | Définition | Disponible à |
| --- | --- | --- | --- |
| Facture | `invoice_amount_eur` | montant converti en EUR | émission |
| Facture | `payment_terms_days` | délai de paiement accordé (15, 30 ou 60) | émission |
| Facture | `invoice_month`, `invoice_quarter` | mois et trimestre d'émission | émission |
| Facture | `amount_to_credit_limit_ratio` | montant divisé par le plafond de crédit | émission |
| Client | `customer_age_months` | ancienneté du client en mois | émission |
| Client | `customer_industry`, `customer_segment` | secteur et segment | émission |
| Historique | `previous_invoice_count` | nombre de factures précédentes | émission |
| Historique | `previous_late_payment_count` | retards passés dont l'issue est connue avant P | émission |
| Historique | `historical_late_payment_rate` | taux de retard passé | émission |
| Historique | `recent_late_rate_last5` | taux de retard sur les 5 dernières issues connues | émission |
| Historique | `average_payment_delay`, `median_payment_delay`, `maximum_payment_delay` | retard moyen, médian et maximal des factures soldées avant P | émission |
| Historique | `days_since_last_payment` | jours depuis le dernier paiement | émission |
| Historique | `has_history` | 1 si le client a au moins une issue connue | émission |
| Exposition | `outstanding_balance_eur` | solde impayé du client (paiements enregistrés avant P) | émission |
| Exposition | `customer_outstanding_invoice_count` | nombre de factures encore impayées | émission |

**Variables écartées volontairement** (elles contiennent la réponse) : `delay_days` (retard final de la facture), la date de règlement, le statut final de la facture, et le profil caché du client (`ground_truth.csv`, qui n'existe pas en production).

**Devises :** les montants sont convertis avec des taux **fixes et synthétiques** (EUR 1, USD 0,92, TND 0,30). Ce sont des hypothèses de travail, pas de vrais taux de change.

**Valeurs manquantes :** les clients sans historique ont des variables d'historique à `NaN` (environ 9 % des factures). Elles sont imputées par la médiane **dans le pipeline** (jamais avant le découpage), avec l'indicateur `has_history`.

## 4. Approche anti-fuite et preuve

**Principe :** une facture passée n'entre dans l'historique que si son issue était connue avant P. Une facture payée à temps compte à la date de règlement. Une facture en retard compte dès le lendemain de l'échéance, même si elle est payée plus tard.

**Autres garde-fous :**
- découpage chronologique (jamais aléatoire) ;
- pré-traitement dans un `Pipeline`, ajusté uniquement sur le train ;
- aucun rééquilibrage de classes avant le découpage.

**Preuve :** le test `test_features_do_not_depend_on_the_future` (fichier `tests/test_features.py`) supprime toutes les données postérieures à la date de prédiction, recalcule les variables de 20 factures tirées au hasard et vérifie qu'elles restent **identiques**. Si une variable utilisait une information du futur, le test échouerait.

**Démonstration de la fuite (notebook 01) :** avec le retard final de la facture elle-même comme variable, l'AUC vaut 1,0. Ce score parfait prouve que la variable contient la réponse, pas que le modèle est bon. Avec le seul taux historique de retard, l'AUC vaut environ 0,77.

## 5. Découpage chronologique

| Jeu | Factures émises | Taille | Rôle |
| --- | --- | --- | --- |
| Train | avant le 01/07/2024 | 9 251 | apprendre |
| Validation | du 01/07/2024 au 28/02/2025 | 3 959 | comparer les modèles, calibrer, choisir le seuil |
| Test | à partir du 01/03/2025 | 4 716 | note finale, utilisée **une seule fois** |

Taux de retard : 31,6 % en train, 33,1 % en test. Un découpage aléatoire entraînerait le modèle sur des factures de 2025 pour prédire 2024, ce qui n'arrive jamais en production.

## 6. Modèles comparés et résultats

Trois modèles, tous dans un `Pipeline` avec leur pré-traitement :
- **régression logistique** (baseline, variables mises à l'échelle) ;
- **forêt aléatoire** (300 arbres, `min_samples_leaf=20`) ;
- **XGBoost** (300 arbres, profondeur 4, taux d'apprentissage 0,05).

Pas de SMOTE ni de `class_weight` : avec environ 32 % de retards, le déséquilibre est modéré, et rééquilibrer fausserait les probabilités dont le score de risque a besoin.

**Validation** (sert à choisir) :

| Modèle | ROC-AUC | PR-AUC | Brier |
| --- | --- | --- | --- |
| Régression logistique | 0,794 | 0,693 | 0,165 |
| Forêt aléatoire | 0,802 | 0,709 | 0,160 |
| XGBoost | 0,795 | 0,701 | 0,164 |

Meilleur modèle selon la PR-AUC de validation : **forêt aléatoire**.

**Test** (estimation honnête, seuil 0,5) :

| Modèle | ROC-AUC | PR-AUC | Brier |
| --- | --- | --- | --- |
| Régression logistique | 0,788 | 0,662 | 0,171 |
| Forêt aléatoire | 0,788 | 0,664 | 0,167 |
| XGBoost | 0,784 | 0,662 | 0,169 |
| Forêt aléatoire calibrée | 0,788 | 0,664 | 0,168 |

**Lecture :**
- Les trois modèles sont très proches : l'essentiel du signal est dans quelques variables d'historique, que même une régression logistique exploite bien. Un modèle plus complexe n'est pas automatiquement meilleur.
- Les scores de validation sont un peu plus élevés que ceux du test, ce qui est attendu puisque le modèle y a été choisi. Seul le test est honnête.
- La PR-AUC se compare au taux de base de 33 % : c'est la métrique la plus parlante quand la classe positive est la minorité. L'accuracy seule ne prouve rien (répondre « jamais en retard » donnerait déjà environ 68 %).

## 7. Calibration et seuil métier

**Calibration :** le meilleur modèle est calibré par régression sigmoïde (`CalibratedClassifierCV` avec `FrozenEstimator`) sur la **validation**, sans ré-entraîner le modèle. L'effet est quasi nul (Brier 0,168 contre 0,167) : la forêt était déjà bien calibrée. On garde la version calibrée pour la garantie.

**Seuil d'alerte métier : 0,16.** Hypothèse de coût : manquer un retard (faux négatif) coûte **5 fois plus** qu'une relance inutile (faux positif). Cette hypothèse est paramétrable et à discuter avec un financier. Le seuil minimise le coût total sur la validation.

Résultat sur le test avec ce seuil :

| | Valeur |
| --- | --- |
| Rappel | 0,93 (1 446 retards détectés sur 1 562) |
| Précision | 0,43 |
| Retards manqués (faux négatifs) | 116 |
| Relances inutiles (faux positifs) | 1 936 |

Conséquence directe de l'hypothèse de coût : on rate très peu de retards, au prix de nombreuses relances inutiles. Avec un coût de 1 pour 1, le seuil monterait vers 0,5.

**Niveaux de risque affichés** (`Low` < 30 %, `Medium` 30 à 70 %, `High` ≥ 70 %). Taux de retard observés sur le test : environ 17 % pour `Low`, 43 % pour `Medium` et 83 % pour `High`. Les niveaux sont bien ordonnés. Ils servent à **afficher** le risque ; le seuil d'alerte de 0,16 sert à **déclencher** une action.

## 8. Explicabilité (SHAP)

Pour chaque facture, SHAP donne les variables qui poussent le score vers le haut ou vers le bas (`app/…/explain.py`). Les explications sont stockées dans `predictions.explanation_data`.

Sur la facture au risque le plus élevé (score d'environ 0,92), les cinq premières explications augmentent toutes le risque : retard moyen de paiement, taux historique de retard, retard médian, taux sur les 5 dernières factures, retard maximal. L'importance globale est dominée par ces mêmes variables d'historique.

## 9. Distinction entre attribution et causalité

SHAP décrit **comment le modèle utilise les variables**, pas ce qui cause le retard. « Le retard moyen passé de 18 jours augmente le risque de cette facture » signifie que le modèle a appris cette association. Cela ne prouve pas que ce retard passé **provoque** le retard futur : c'est de la corrélation, pas de la causalité.

## 10. Versionnage et traçabilité

Chaque entraînement crée un dossier `backend/ml/artifacts/v1-<modèle>-<date>/` contenant :
- `model.joblib` : le modèle calibré, son pipeline de base et la liste des variables ;
- `metadata.json` : version, algorithme, date, version du jeu de données, découpage, variables, métriques de validation et de test, seuil, hypothèse de coût et avertissement « données synthétiques ».

Le fichier `active.json` indique à l'API quel modèle utiliser. La table `model_versions` garde l'historique, avec un seul modèle actif à la fois.

## 11. Limites

- **Données synthétiques** : les profils suivent des règles simples. Les performances ne prouvent rien sur des factures réelles.
- **Taux de change fictifs** (EUR, USD, TND) : les montants en EUR sont une approximation de travail.
- **Factures en litige exclues** de l'apprentissage et de la prédiction : le modèle ne sait pas les traiter.
- **Clients sans historique mal prédits** : sans passé de paiement, le modèle s'appuie surtout sur le montant, le délai et la saison, qui sont peu informatifs.
- **Aucun événement externe** (faillite, litige commercial, crise, jours fériés locaux) n'est modélisé.
- **Hypothèse de coût 5 pour 1** arbitraire : à valider avec un financier.
- **Dérive** : le modèle n'est pas surveillé dans le temps. Un comportement de paiement qui change dégraderait les performances sans alerte automatique.