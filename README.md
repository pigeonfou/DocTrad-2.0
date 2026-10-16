# DocTrad 2.0

Application de traduction documentaire locale anglais → français, avec **BC-250 / Vulkan exclusivement pour l’inférence**. Le moteur utilisé est le `llama-server` déjà présent. **Aucune dépendance à Unsloth Studio, aucun nouveau moteur compilé, aucun téléchargement de modèle pendant les traitements.**

## Fonctionnement implémenté

- Interface web authentifiée : import PDF/DOCX/PPTX, progression actualisée, téléchargement, rapport qualité, correction de segment, recomposition et approbation.
- DocumentIR typé et versionné, repères PDF, glyphes/runs, tables/cellules, contexte section/voisinage/tableau, navigation et provenance.
- Extraction native PyMuPDF ; OCR Tesseract local pour scans ; seconde lecture Docling optionnelle avec modèles préinstallés. Les régions ambiguës sont signalées.
- Traduction directe via `/props`, `/apply-template`, `/tokenize` et `/completion`, template officiel TranslateGemma, budget réel de tokens, refus de troncature.
- Profil unique : `translategemma-12b-it.Q4_K_M.gguf`, contexte runtime 4096, entrée plafonnée à 1800 tokens, sortie 1200, une requête à la fois. Hashes du modèle et du binaire enregistrés.
- Valeurs, associations valeur/unité, références, URLs, glossaire et rapports de longueur contrôlés ; les erreurs critiques bloquent l’approbation.
- PDF natifs : conservation des objets graphiques, liens et signets, suppression sélective du texte, composition et contrôle visuel hors zones traduites. Rotations orthogonales prises en charge. Réduction typographique limitée à 15 %.
- DOCX/PPTX : paquet et relations conservés, texte réparti sur les runs existants plutôt qu’aplati dans le premier run.
- PostgreSQL en production, tâches avec leases/heartbeat, admission GPU unique, cache isolé par utilisateur, corrections et sorties précédentes conservées. SQLite sert aux tests et au profil mono-hôte de développement.
- Déploiement natif systemd/nginx, coexistence sous `/doctrad2/`, CI Python 3.12 et 3.14, releases immuables, sauvegarde et rollback.

## État et limites explicites

Il s’agit de la première implémentation fonctionnelle de la nouvelle architecture, pas d’une certification de qualité sur tous les PDF. Les tests locaux utilisent une inference simulée explicitement pour le parcours applicatif ; ils ne mesurent pas la vitesse ni la qualité réelle de la BC-250.

Le moteur doit exposer les endpoints natifs requis. Si son GGUF est Content-only, V2 rend localement le template de référence TranslateGemma, puis utilise le tokenizer réel. Le simple fait qu’un binaire existe ne valide pas cette compatibilité. Le diagnostic refuse un modèle incompatible au lieu de passer silencieusement par Unsloth. Voir [compatibilité du template](docs/TEMPLATE.md).

Le profil technique utilise le contenu source et, pour les fragments courts d’un tableau, ses titres et voisins déjà extraits. Une reprise peut contraindre l’écriture et conserver des littéraux dérivés de la source, sans dictionnaire propre à un document. Les essais et limites sont décrits dans [la politique de traduction](docs/TRANSLATION_POLICY.md). **La revue sémantique par un second modèle n’est pas activée.** Le glossaire sert au contrôle. La postédition multimodèle nécessite un benchmark et une gestion séquentielle des modèles sur la seule BC-250.

Les angles non orthogonaux, fonds de scans complexes, désaccords d’extraction et débordements sont signalés ou bloqués. Les masques de scans exigent une inspection humaine. Les fontes source sont inventoriées mais ne sont pas encore systématiquement réembarquées : le composeur utilise des fontes locales de remplacement. Le mapping de styles OOXML est proportionnel, pas un alignement sémantique parfait des mots. Pas de promesse de pagination identique sans moteur bureautique local. La validation terminée conduit à **prêt à réviser**, jamais à une approbation implicite.

## Installation et exploitation

Voir [installation](docs/INSTALLATION.md), [profil BC-250](docs/BC250.md), [architecture et écarts](docs/ARCHITECTURE.md), [validation](docs/VALIDATION.md).

Le dépôt contient les workflows automatiques. La première connexion d’un runner au nouveau dépôt et les secrets LAN doivent être établis sur les machines : ces fichiers sensibles ne sont pas dans Git. L’ancien DocTrad conserve ses services, ses données et sa route.

## Développement

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/pytest -q
.venv/bin/ruff check src tests scripts
```

Le benchmark sans `--translate` est un test d’extraction/reconstruction à texte identique ; il n’est jamais annoncé comme une traduction BC-250. Avec `--translate`, il exige le runtime réel configuré et enregistre le contrat du modèle.

## Licence

AGPL-3.0-or-later, cohérente avec l’utilisation de PyMuPDF sous AGPL. Les conditions des modèles et dépendances sont distinctes. Les GGUF, clés, documents et journaux privés ne sont jamais publiés dans ce dépôt.

