# Runtime Content-only : compatibilité sans rechargement

Constat BC-250 : le TranslateGemma 12B Q4_K_M résident sur llama-server Vulkan utilise le port loopback 52365, contexte 4096, sans clé native, et expose un template Content-only sans champs de langues.

La version V2 rend donc localement le template de référence TranslateGemma conservé dans llama.cpp lorsque les champs attendus sont absents. Source : `ggml-org/llama.cpp/models/templates/google-translategemma-4b-it.jinja`, blob `d571968f9770221512d29627697012202451983c`. Il s’agit du cadrage textuel TranslateGemma partagé, appliqué au couple en/fr ; sa compatibilité effective avec le 12B présent doit passer le test réel.

Aucun redémarrage, rechargement ni modification du GGUF. Les tokens sont produits par `/tokenize` sur le serveur réel, avec les marqueurs explicites et sans ajout d’un deuxième BOS. `/completion` reçoit la liste de tokens. Source, template/hash et mode local sont tracés. Les documents contenant des marqueurs de conversation réservés sont bloqués pour révision.

`scripts/probe-bc250.py` est autonome et ne requiert que Python standard : une phrase technique publique, température zéro, 256 tokens de sortie, puis manifeste des fichiers réellement présents. Il ne contacte pas Studio et ne publie aucune clé. Les timings d’inférence excluent le calcul des SHA et ne constituent pas un benchmark global.

Le serveur natif reste loopback et son cycle de vie reste celui de son gestionnaire actuel. La correction du template ne crée pas encore un endpoint LAN protégé et ne prétend pas rendre le processus indépendant du gestionnaire. La connexion LAN est l’étape suivante après ce test.
