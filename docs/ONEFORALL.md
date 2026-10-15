# OneForAll et référence réelle

V2 est enregistrée dans `/etc/oneforall/local-apps.json` et reste déployée par son propre dépôt et ses propres services. OneForAll connaît le port loopback 8097, les unités réelles, le contrôle de santé et le préfixe `/doctrad2/` à retirer en amont. Le portail et les reconfigurations conservent cette entrée ; les opérations de déploiement/sauvegarde propres à OneForAll refusent de prendre possession de V2. Les hooks correspondants sont également publiés dans OneForAll pour persister lors des mises à jour du gestionnaire.

L’installation applique des hooks limités et idempotents à la source locale du gestionnaire, sous son verrou, en préservant le reste du code. Une structure inconnue est refusée. Les fichiers sont sauvegardés, écrits atomiquement et nginx est testé avant rechargement ; un échec restaure la configuration. La politique publique est reprise de DocTrad existant : aucun autre service n’est ouvert. L’authentification de V2 reste obligatoire, avec reprise locale des comptes existants lorsqu’ils sont lisibles.

Si OneForAll est hébergé sur une autre machine, le script indique `not_local` plutôt que d’inventer une route. L’adresse réellement enregistrée et son état apparaissent dans le rapport de déploiement.

La référence AN/PRC-167 est un PDF public déjà utilisé dans le projet, dont le SHA autorisé est fixé dans le script. Le déploiement crée un job visible dans V2, traité par le vrai worker et le moteur BC-250. Le script attend sa fin, sans le déclarer approuvé. `quality_blocked` reste un résultat bloqué, même si l’exécution a terminé correctement.

Seuls les artefacts de ce document public sont exportés vers `/var/lib/doctrad2-reference` et dans l’artefact GitHub `doctrad2-public-reference`. Aucun document utilisateur arbitraire ni secret ne peut être sélectionné par ce script. Un job de référence déjà terminé est réutilisé pour le même contrat/version de test.
