# Connexion LAN au moteur existant

Le test réel sur la BC-250 a traduit une phrase technique en 2,252 secondes, 96 tokens d’entrée et 28 tokens générés, avec les valeurs 12 V, −20 et 55 conservées. Il s’agit d’un test court, pas d’un score de qualité documentaire. Les SHA du GGUF et du binaire ont été relevés localement.

Le moteur reste sur son port loopback géré par son gestionnaire actuel. Une passerelle Python standard transmet uniquement les endpoints d’inférence nécessaires vers ce processus ; elle ne charge, décharge ni redémarre aucun modèle. Elle retrouve le port du processus après un éventuel redémarrage identique et refuse un changement d’identité/contexte/fichiers. Elle ne rend pas le processus indépendant de son gestionnaire.

La passerelle écoute sur l’IP LAN de la BC-250, port 8098, en TLS mutuel. Le certificat client public est préparé sur le serveur DocTrad ; sa clé privée y reste. La BC-250 génère sa clé privée serveur localement et retourne seulement son certificat public. Le client exige ce certificat de confiance et vérifie l’adresse IP dans le SAN. Aucun token partagé n’est publié ou copié dans une commande.

`deploy/bc250-client.crt` est **un certificat public**, pas une clé privée. Le script d’installation vérifie son SHA avant d’inscrire l’identité du client. L’installation doit être lancée une fois sous sudo depuis le compte bc : création du seul service `doctrad2-bc250-gateway`, conservation du moteur résident et de Studio. Les routes de gestion de modèles sont exclues, les corps et sorties plafonnés, l’inférence séquentielle et les journaux sans contenu documentaire.

La sortie d’installation contient l’URL LAN, le certificat serveur public encodé et les empreintes modèle/runtime. Ces données suffisent au raccordement de DocTrad par le runner ; aucun secret n’est nécessaire dans cette sortie. La disponibilité réelle du service et ses performances avec TLS restent à mesurer sur la machine après installation. Les clés/certificats doivent être renouvelés avant leur expiration, et une rotation ne remplace jamais silencieusement l’identité déjà inscrite.

Les tests automatisés exécutent une vraie négociation TLS locale : succès avec le certificat client attendu, refus sans certificat ou sans CA serveur, refus des routes de chargement et des requêtes hors limites. Les essais de passerelle locale n’utilisent pas la BC-250 ; ils ne sont pas présentés comme un déploiement matériel.
