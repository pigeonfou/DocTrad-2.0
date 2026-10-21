# Analyse des résultats OCR et état de la BC250

## Analyse hors ligne

`analyze-ocr-results.py` relit les réponses enregistrées sans charger de modèle. Il utilise les mêmes contrôles de nombres, quantités physiques et références que la traduction technique.

```bash
PYTHONPATH=src python3 scripts/analyze-ocr-results.py \
  --input resultats-enregistres.json \
  --output nouveau-rapport.json
```

Le fichier d'entrée contient une liste de cas `{case, source, recognized, ...}` ou une collection `{runs: [{results: [...]}]}`. La sortie est créée exclusivement : un rapport existant n'est pas écrasé. Les réponses dont seul un extrait est conservé ne sont pas réévaluées.

L'analyse préserve les séparations entre lignes et cellules des tableaux HTML, décode les entités et interprète uniquement les exposants carrés/cubiques TeX explicites. Elle ne répare aucun mot ni aucune valeur. Les cellules fusionnées et les structures HTML incomplètes restent signalées pour revue.

Les nombres seuls ne suffisent pas : `24 V / 3.5 A` et `24 A / 3.5 V` contiennent les mêmes valeurs, mais les couples valeur–unité diffèrent. Les références techniques sont également comparées. Les champs `technical_checks_passed` et `technical_checks_applicable` décrivent seulement ces contrôles : sans données techniques, le premier vaut null pour du texte non vide. Ils ne certifient ni les mots ordinaires, ni l'ordre de lecture, ni le rattachement d'une valeur à son libellé. Les anciens scores lexicaux et leur verdict sont conservés ; `quality_certified` reste false et une revue reste requise.

Une référence tirée de la couche native d'un PDF peut omettre les logos et inscriptions inclus dans des images. Une valeur ou un mot supplémentaire ne constitue donc pas automatiquement une hallucination : comparer les pixels source reste nécessaire.

## Exécution OCR sur une BC250 partagée

```bash
bash scripts/run-bc250-ocr.sh -- python3 scripts/test-unlimited-ocr.py [arguments]
```

Le lanceur s'exécute sur la BC250, sous le compte bc, avec les autorisations systemctl déjà prévues. Il refuse les autres processus llama-server, llama-cli, llama-mtmd-cli, sd-cli et sd-server avant de modifier un service (code 75). Un verrou sérialise les lanceurs qui l'utilisent ; il ne réserve pas la machine contre une application indépendante.

Si TranslateGemma était actif, le lanceur l'arrête puis le restaure après succès ou échec OCR, en contrôlant /health. S'il était arrêté, il le laisse arrêté. Si un autre moteur démarre pendant l'OCR, la restauration est différée avec un code 75 plutôt que de charger un second modèle. Une restauration ou une santé en échec renvoie 70. Le service web n'appelle pas encore ce lanceur automatiquement.

L'encodage et le décodage OCR restent limités à la BC250. Aucune dépendance ni aucun modèle n'est téléchargé par ces outils.
