# Unlimited-OCR : profil expérimental BC250

Profil effectivement exécuté sur la BC250. Ce document ne déclare pas le moteur intégré à l'interface DocTrad2.

## Moteur et paramètres retenus

- llama.cpp R-SWA : source figée 1725dcab4baac46c4eb197afc96af7b57a81882a, compilation Vulkan.
- Unlimited-OCR BF16 sahilchachra, révision 0dc781d8a23f52963918ebd5b2d1b9fe61504661.
- Projecteur mmproj-Unlimited-OCR-F16.gguf de la même révision.
- Prompt document parsing., template deepseek-ocr, no-jinja.
- Vulkan0, 99 couches GPU, flash-attn off, cache V f32, contexte 8192.
- Override deepseek2-ocr.attention.sliding_window=int:128.
- Température 0, repeat-penalty 1.0, batch 512, microbatch 128.
- DRY multiplier 0.8, base 1.75, allowed-length 35, penalty-last-n 128, sequence-breaker none.
- Image : grand côté minimum 1200 pixels. Budget 2400 tokens, 5500 pour pages denses.
- Une sortie doit contenir du texte et finir par EOG. Un code processus 0 seul ne suffit pas.

## Résultats conservés

Exécution 39515898862 : trois images, dont une page technique publique, tous les mots et nombres de référence conservés après nettoyage des marqueurs de localisation. Environ 19 secondes par image synthétique lisible et 21 secondes pour la page technique. Le projecteur BF16 alternatif était environ trois fois plus lent sur cette page.

Exécution 39516533060 : OCR puis véritable adaptateur technique TranslateGemma de production, sept blocs, traduction 29,56 secondes après OCR 21,244 secondes. Aucun signalement des contrôles automatiques, valeurs et URL conservées. Cela ne remplace pas une relecture linguistique.

Exécution 39516672666 : fiche AN/PRC deux pages à 144 dpi. Les deux générations terminent normalement (31,805 et 51,854 secondes), mais le contrôle strict échoue. Une petite mention dans une photographie et un tampon tourné sont omis. La deuxième page produit des tableaux HTML. Les scores bruts sont affectés par ces balises, l'ordre de lecture, les césures de la référence PDF et des textes d'images absents de sa couche native.

Exécution 39517254256 : comparaison à 288 dpi avec extraction du texte des cellules HTML. Résultat à consulter dans les journaux de cette exécution ; ne pas présumer sa réussite.

## Utilisation et limites

Le script scripts/benchmark-unlimited-ocr.py permet de reproduire ces tests avec les fichiers publics dont le SHA256 est vérifié. Les réponses brutes, journaux et résultats JSON restent dans le répertoire de benchmark de chaque exécution sur la BC250.

L'OCR et TranslateGemma utilisent la même mémoire GPU : les essais sont sérialisés et le service de traduction est restauré après l'OCR. Ne pas lancer deux moteurs simultanément.

L'interface de production utilise encore l'extraction native ou Tesseract. Le profil ci-dessus est utilisable par la CLI expérimentale ; le transport OCR, les coordonnées des blocs et l'intégration au pipeline restent à qualifier avant activation dans l'interface.
