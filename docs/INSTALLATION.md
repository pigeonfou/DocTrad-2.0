# Installation native et déploiement

## Préconditions

Ubuntu 24.04/26.04 pour l’application ; BC-250 existante sur le LAN ou application co-localisée si son OS supporte les dépendances. Seule la BC-250 réalise l’inférence. PostgreSQL, Python ≥3.12, nginx et Tesseract anglais. Aucune installation CUDA/Torch/GPU requise pour le profil standard. Un runner attaché à l’ancien dépôt n’est pas automatiquement attaché au nouveau.

Le premier enrôlement nécessite un accès administratif local déjà disponible. Le projet ne contient ni clé SSH, ni token GitHub, ni adresse LAN supposée vraie. Les workflows ne peuvent pas inventer cet accès.

## Co-localisation BC-250

`scripts/bootstrap.sh` prépare les paquets OS, le rôle/base PostgreSQL, réutilise le TranslateGemma résident par son endpoint direct, crée une configuration et installe la release courante. Il ne démarre pas un second moteur et ne modifie pas Studio. La configuration n’est jamais remplacée silencieusement. Le mot de passe initial `admin` est généré et conservé uniquement dans `/etc/doctrad2/initial-admin`, permissions 0600.

## Application Ubuntu séparée, même BC-250

Préparer `/etc/doctrad2/app.env` à partir de `deploy/app.env.example` avec l’adresse privée réelle du moteur direct, sa clé et les SHA mesurés localement sur la BC-250. Le nom d’utilisateur PostgreSQL doit correspondre au rôle créé ; l’URL sans mot de passe par socket fonctionne avec peer auth lorsque les services tournent sous `doctrad2`. Aucun placeholder ne doit rester. La configuration doit appartenir à root ; l’installation fixe les droits root:doctrad2 0640.

## Services et coexistence

Installer une release exacte avec `scripts/install.sh SHA`. Services `doctrad2-web` et `doctrad2-worker`, port loopback 8097, stockage `/var/lib/doctrad2`, releases `/opt/doctrad2/releases/SHA`. Rien ne remplace `/opt/docutranslate`, sa base ou ses services. Le snippet `deploy/nginx.conf` s’intègre dans le serveur nginx OneForAll existant sous `/doctrad2/`. Ne pas remplacer la configuration OneForAll générée sans intégrer ce snippet à sa source de configuration.

Cookies Secure par défaut : accès HTTPS requis. Pour un LAN HTTP explicitement choisi, `DOCTRAD2_SECURE_COOKIE=0` est possible, avec connaissance du transport non chiffré. Le tunnel Cloudflare peut exposer l’interface si autorisé, mais les documents qui y passent transitent par un tiers ; confinement documentaire strict = fichiers accessibles uniquement via LAN/VPN direct.

## Runner et CI/CD

Sur l’hôte runner, `scripts/setup-runner.sh` utilise une session gh déjà authentifiée et un runner extrait pour enregistrer `doctrad2-ubuntu`, label `doctrad2-deploy`. Installer ensuite son service comme pour les runners existants. Le checkout protégé `/usr/local/src/DocTrad-2.0` appartient à root et pointe exactement vers le nouveau dépôt. Installer `deploy/doctrad2-deploy` en `/usr/local/sbin/doctrad2-deploy`, root:root 0755 ; sudoers autorise uniquement ce helper au compte runner, jamais une commande shell arbitraire.

La variable GitHub `DOCTRAD2_DEPLOY_ENABLED=true` active les déploiements après l’enrôlement. Elle évite qu’un nouveau dépôt sans configuration lance une installation incomplète ; ce n’est pas un mécanisme de demande d’approbation utilisateur. Tests sur 3.12/3.14, puis exact SHA testé, rejet des commits dépassés. Le helper root fetch la branche main du dépôt protégé ; pas d’exécution de scripts provenant d’un dossier modifiable par le runner.

## Offline et restauration

Préparer les paquets OS et le wheelhouse avant isolement, `scripts/build-offline.sh DEST`. L’installation utilise `DOCTRAD2_WHEELHOUSE=DEST` avec `--no-index`. Vérifier `SHA256SUMS` avant usage. Wheels propres à l’ABI Python cible ; les tests CI vérifient les deux versions mais ne remplacent pas l’installation Ubuntu 26 réelle.

`scripts/backup.sh` arrête l’API et le worker pendant le snapshot, sauvegarde PostgreSQL ou SQLite et les objets, puis rétablit leurs états actifs précédents. Prévoir cette courte fenêtre de maintenance. `scripts/rollback.sh SHA` restaure une release installée validée, pas seulement le head d’une branche. La première version initialise le schéma ; migrations suivantes obligatoirement expand/contract avec tests de lecture par release précédente. Tester la restauration avant mise en production.

`doctrad2 diagnose` vérifie le protocole LLM ; `/health` vérifie l’application/base, pas la qualité d’une traduction ni la disponibilité du modèle GPU.
