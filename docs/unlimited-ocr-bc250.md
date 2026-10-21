# Essai Unlimited-OCR sur la BC250

Le script `scripts/test-unlimited-ocr.py` exécute un OCR hors ligne sur une image et conserve la réponse brute, le journal du moteur et un manifeste avec les empreintes des fichiers. Ce moteur reste expérimental ; il ne remplace pas encore Tesseract dans l'interface DocTrad2 et n'effectue pas la traduction.

## Profil retenu

Utiliser le binaire llama-mtmd-cli issu de llama.cpp R-SWA, source 1725dcab4baac46c4eb197afc96af7b57a81882a, et le modèle Unlimited-OCR-BF16.gguf avec mmproj-Unlimited-OCR-F16.gguf, révision sahilchachra 0dc781d8a23f52963918ebd5b2d1b9fe61504661.

Le script configure Vulkan0, contexte 8192, R-SWA 128, cache V f32, flash attention désactivée, template deepseek-ocr sans Jinja, température 0 et DRY. Le contexte précédent de 16384 ne correspondait pas au profil effectivement mesuré.

Le grand côté de l'image doit atteindre au moins 1200 pixels. Le script prend une image déjà préparée : il ne modifie pas le document source et ne télécharge rien.

## Exécution

La BC250 doit être libre : le script refuse de lancer un deuxième moteur. L'orchestrateur doit arrêter le runtime de traduction avant l'OCR, puis le restaurer, y compris si l'OCR échoue.

```bash
python3 scripts/test-unlimited-ocr.py \
  --binary /chemin/vers/llama-mtmd-cli \
  --model /chemin/vers/Unlimited-OCR-BF16.gguf \
  --projector /chemin/vers/mmproj-Unlimited-OCR-F16.gguf \
  --image /chemin/vers/page.png \
  --output /chemin/vers/nouveau-repertoire-resultat
```

Le répertoire de sortie doit être nouveau. Un code 65 indique notamment une réponse vide ou une génération observée comme interrompue. Un code 0 conserve le statut `completed_requires_review` : il ne certifie pas la fidélité du texte.

Le champ `completion_verified` est vrai uniquement si le binaire instrumenté émet le marqueur DOCTRAD_OCR_FINISH avec EOG. Si le marqueur est absent, la fin de génération reste non vérifiée. Une fin EOG ne permet pas de détecter les omissions ni les ajouts.

## Qualification et limites

Les essais publics sur BC250 sont conservés dans la branche diagnostic/autonomous-bc250-20261021, notamment docs/unlimited-ocr-bc250-tested-profile.md et benchmarks/results/unlimited-ocr-sparse-regions-20261021.json.

Une page technique simple a conservé les mots et les nombres contrôlés ; sa chaîne OCR puis adaptateur technique TranslateGemma a été exécutée. Sur la fiche dense de deux pages, des mentions sont encore omises. L'augmentation à 288 dpi, la grille fixe, le projecteur BF16 et l'encodage visuel CPU n'ont pas résolu tous les défauts. La petite mention sur une photographie peut être récupérée exactement sur une région agrandie avec le prompt localisé ; le tampon reste non fiable.

Ces régions de diagnostic utilisent les coordonnées natives du PDF pour sélectionner des pixels, sans transmettre le texte attendu au modèle. Ce résultat ne constitue pas un détecteur de régions pour documents scannés. Aucun texte produit par un essai rejeté ne doit être ajouté automatiquement à une traduction.
