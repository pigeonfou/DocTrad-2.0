# Unlimited-OCR-GGUF — expérimentation locale

Le catalogue authentifié `/v2/models` distingue traduction et OCR. Unlimited-OCR
lit des pages ; TranslateGemma reste le traducteur. Le profil OCR est enregistré
mais **pas activé dans le pipeline de traduction**. Son installation et sa
compatibilité avec le binaire BC-250 n'ont pas été vérifiées sur la machine.

Modèle : https://huggingface.co/sahilchachra/Unlimited-OCR-GGUF

Fichiers nécessaires, du même dépôt : `Unlimited-OCR-Q5_K_M.gguf` et
`mmproj-Unlimited-OCR-F16.gguf`. Q5_K_M est le profil d'essai retenu.
Le projecteur visuel est obligatoire. Installer les fichiers séparément en
conservant la révision et les sommes SHA-256 du fournisseur ; aucun téléchargement
n'a lieu pendant l'inférence.

Le runtime existant doit contenir un `llama-mtmd-cli` compatible `deepseek2-ocr`
et Vulkan. Le script ne compile ni n'installe de moteur. La conversion
Unlimited-OCR a été intégrée par llama.cpp PR 24969 ; le support R-SWA de la
PR 24975 reste expérimental. Ne pas déduire la compatibilité de la seule présence
du binaire : vérifier sa version puis exécuter un essai d'une page.

Sur la BC-250, après avoir libéré explicitement le runtime résident :

```bash
python3 scripts/test-unlimited-ocr.py \
  --binary /chemin/existant/llama-mtmd-cli \
  --model /chemin/Unlimited-OCR-Q5_K_M.gguf \
  --projector /chemin/mmproj-Unlimited-OCR-F16.gguf \
  --image /chemin/page.png \
  --output /chemin/nouveau-dossier-resultats
```

Le test refuse de remplacer un dossier existant et refuse un runtime llama
détecté. Ce contrôle n'est pas un ordonnanceur GPU entre applications : réserver
la BC-250 pendant l'essai. Il ne stoppe ni ne redémarre aucun service.
Il produit `ocr.txt` (sortie CLI brute), `runtime.log` et `manifest.json`
(commandes, empreintes, durée, code retour). Un code zéro indique seulement
l'exécution du runtime ; relire le texte extrait et la structure, notamment
les tableaux, les nombres et les unités. Aucune traduction ni validation de
fidélité documentaire n'est revendiquée par ce test.

L'intégration de l'OCR à la reconstruction nécessite ensuite un contrat vérifié
pour les régions, coordonnées et tableaux. La passerelle DocTrad actuelle
n'expose ni images ni commande de chargement de modèle ; la modification de ce
contrat et un essai matériel sont nécessaires avant d'activer un sélecteur de job.
