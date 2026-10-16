# Validation de la première implémentation

## Tests automatisés

Les tests locaux couvrent : parcours import → traduction simulée → export → correction → recomposition → approbation, invariants numériques et références, association valeur/unité, normalisation décimale, refus des endpoints externes, template/tokenizer natifs, troncature, absence de retry sur authentification, segmentation, conservation de graphiques/liens/signets, rotations de pages, maintien des styles OOXML, cache, leases et séparation des utilisateurs. Les régressions comprennent aussi le décodage contraint après une écriture inattendue, les marqueurs de libellés et de sigles omis, les unités source ambiguës, le contexte de tableaux et l’alignement facultatif d’un bloc français déjà ajusté.

Le moteur d’inférence est simulé **uniquement dans les tests**. Aucun résultat de vitesse/qualité réelle de traduction BC-250 ne découle de ces tests. Lint et syntaxe shell sont également vérifiés. CI exécute 3.12 et 3.14 sur Ubuntu 24.04 ; compatibilité réelle Ubuntu 26 à confirmer sur l’hôte.

## Protocole reproductible

`scripts/benchmark.py SOURCE OUTPUT` fait un parcours à texte source identique. `--translate` active le moteur BC-250 réel, avec configuration locale obligatoire, hashes et timings. `--tessdata PATH` active l’OCR des scans. Chaque sortie comprend original hashé dans le manifeste, IR, artefact et rapport. Ne jamais comparer les durées d’un mode identity à une traduction réelle.

Corpus : TSM-WAVEFORM scanné et sa référence ChatGPT validée humainement ; AN/PRC-167 ; puis au moins 20 documents supplémentaires, natifs/scans/mixte/tableaux/multicolonnes/OOXML et plusieurs centaines de pages. Comparer séparément extraction, traduction sur IR commun et reconstruction sur cible commune. Aucun réglage ne doit dépendre du nom de TSM ou d’une liste fixe de références AN/PRC.

Gates : aucune référence/valeur critique corrompue, aucune cellule déplacée, aucun débordement non résolu, aucune altération graphique hors zones, navigation préservée, reprise sans double publication. Les annotations humaines MQM et les différences documentaires sont prioritaires sur un score textuel global. La traduction ChatGPT sert de comparateur, pas de preuve parfaite.

## Expériences locales disponibles

Les essais à texte identique sur AN/PRC-167 et TSM-WAVEFORM servent à éprouver extraction et refus sûrs. AN/PRC comporte une zone inclinée non orthogonale qui reste signalée. TSM sans OCR est bloqué ; avec Tesseract local, des unités sont extraites et les régions exigent une révision. Ils ne constituent pas une nouvelle traduction. Voir le fichier `validation-local.json` pour les seuls comptages et paramètres mesurés.

## Limites de validation

La comparaison visuelle échantillonnée hors masques ne prouve pas toute la fidélité et ne remplace pas une inspection des cellules et schémas. Comptages de graphismes/liens complètent ce contrôle sans certifier chaque objet. Le contrôle chiffres/unités n’interprète pas encore toutes les notations mathématiques ou conversions ; les transformations d’unités ne sont pas autorisées automatiquement. Le glossaire est un contrôle littéral initial : ambiguïtés et flexions nécessitent révision.

