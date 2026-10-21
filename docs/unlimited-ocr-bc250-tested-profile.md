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

Exécution 39517254256 : comparaison à 288 dpi avec extraction du texte des cellules HTML. Les deux générations terminent (31,993 et 51,250 secondes), mais le contrôle strict échoue encore : les petites mentions omises ne réapparaissent pas. Après extraction des cellules, la deuxième page atteint 97,13 % de rappel lexical et 97,31 % de précision par rapport à la couche PDF native ; ce comparatif reste partiel et affecté par les césures et les textes d'images. Le service de traduction est revenu actif et son endpoint /health répond ok.

Exécution 39517568840 : quatre zones en grille 2×2, chevauchement de 10 %, première page à 288 dpi. Les quatre générations terminent en environ 20 à 23 secondes chacune, mais les mentions recherchées restent absentes et les zones coupent des lignes de texte. Ce mode est rejeté pour une activation automatique ; les résultats partiels ne doivent pas remplacer la page entière. Traduction restaurée et santé ok.

## Essais supplémentaires du 21 octobre 2026

Les régions de diagnostic sont choisies par taille de police (≤8 points) ou inclinaison (>0,02 sur la composante verticale de la direction). Seuls leurs pixels sont transmis au modèle ; la référence native sert ensuite à la mesure.

| Exécution | Modification | Résultat |
|---|---|---|
| 39564476046 | Régions entières, document parsing. | Deux sorties vides |
| 39564708205 | Free OCR. | Mentions récupérées avec du texte ajouté : rejet |
| 39564918618 | Free OCR. + consigne générique de transcription seule | Deux sorties vides |
| 39565177383 | <\|grounding\|>OCR this image. | Petite mention photographique exacte en 17,25 s ; tampon vide |
| 39565426708 | Même prompt, redressement géométrique | Petite mention exacte ; tampon répétitif, 5500 tokens sans EOG : rejet |
| 39565818333 | Projecteur BF16, redressement, budget 512 | Tampon avec caractères ajoutés ; petite mention vide : rejet |
| 39566220878 | Vision CPU BC250, F16, décodage Vulkan | Petite mention exacte en 27,12 s ; tampon vide |
| 39566532510 | Prompt localisé sur les deux pages entières | Pas de récupération des petites mentions ; contrôle strict toujours en échec |
| 39567006674 | Script CLI réutilisable avec profil corrigé, page technique simple | Réussite : 238 tokens, EOG vérifié, rappel/précision lexicaux 100 %, nombres contrôlés conservés |

Le projecteur F16 sur GPU demeure le profil retenu. Le succès de la petite mention sur une région ne qualifie pas le document entier. Le recours à des coordonnées natives pour ce diagnostic ne constitue pas une détection de régions sur des scans.

La correction du script CLI est isolée dans la PR #2. Les 119 tests locaux passent, dont les régressions sur génération vide et génération non vide interrompue. Le dernier essai matériel du CLI a restauré le runtime TranslateGemma et obtenu /health=ok. Les comparaisons détaillées sont dans benchmarks/results/unlimited-ocr-sparse-regions-20261021.json.

## Utilisation et limites

Le script scripts/benchmark-unlimited-ocr.py permet de reproduire ces tests avec les fichiers publics dont le SHA256 est vérifié. Les réponses brutes, journaux et résultats JSON restent dans le répertoire de benchmark de chaque exécution sur la BC250.

L'OCR et TranslateGemma utilisent la même mémoire GPU : les essais sont sérialisés et le service de traduction est restauré après l'OCR. Ne pas lancer deux moteurs simultanément.

L'interface de production utilise encore l'extraction native ou Tesseract. Le profil ci-dessus est utilisable par la CLI expérimentale ; le transport OCR, les coordonnées des blocs et l'intégration au pipeline restent à qualifier avant activation dans l'interface.

## Reprise du 21 octobre au soir

La BC250 héberge Qwen3.5-4B-UD-Q4_K_XL sur le port 41991 ; le runtime DocTrad2 est initialement arrêté. Aucun nouvel essai d'inférence Unlimited-OCR n'a été lancé pendant cette reprise. La PR #3 ajoute l'analyse technique des réponses enregistrées et un lanceur préservant cet état initial : 134 tests locaux passent et les contrôles GitHub réussissent sous Python 3.12 et 3.14 (exécution 39663687266).

Le test matériel 39663635203 confirme un refus code 75 avant exécution de la commande témoin, avec PID Qwen 3048725 inchangé et runtime DocTrad2 toujours arrêté. Les résultats sont dans benchmarks/results/bc250-lifecycle-check-20261021.json. L'analyse de 16 réponses existantes est enregistrée dans benchmarks/results/unlimited-ocr-technical-analysis-20261021.json ; elle ne certifie aucune traduction ni ne remplace les verdicts antérieurs. Les nouvelles mesures de modèle et le déploiement restent en attente de disponibilité de la BC250.
