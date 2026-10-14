# Architecture exécutée et prochaines gates

Le dossier initial décrit la cible complète. La contrainte matérielle a été remplacée par **BC-250 seule**, à la demande de l’utilisateur. Le texte historique est conservé pour traçabilité, pas comme une proposition d’inférence alternative active.

| Domaine | Implémenté | Limite ou gate suivante |
|---|---|---|
| IR | Python/Pydantic, JSON 2.0.0, hashes/IDs, géométrie, fontes/runs, cellules, contexte | Inventaire complet objets/xrefs et correspondances entre révisions à enrichir |
| Extraction | Native, tableaux, Tesseract, Docling secondaire local optionnel | Validation exhaustive coverage/topologie ; Docling option non exercée sur machine cible |
| Traduction | TranslateGemma 12B Q4, template natif, budget tokenizer, provenance, cache | Contexte avancé et glossaire dans la génération à benchmarker ; actuellement réservés au contrôle/révision |
| Cohérence | Glossaire au niveau du job, contrôle occurrences par unité | Termes par sens, index interdocuments et interface glossaire enrichie |
| QA | Chiffres/unités/refs/URLs, longueur, fontes/fit, navigation et pixels hors texte | MQM humain et revue sémantique indépendante non automatisée |
| Reconstruction PDF | Conservation native, rotations orthogonales, redactions sélectives, HTML shaping local | Angles arbitraires et fontes embarquées ; masques de scans nécessitent révision |
| OOXML | Runs et ressources/relations conservés | Alignement sémantique runs, tableaux complexes et rendu/pagination locale |
| Durabilité | PostgreSQL leases/heartbeat, clé de cache complète, artefacts atomiques, corrections/versionnement | Migrations ultérieures et restore automatisé à exercer sur hôte |
| Exploitation | API/UI authentifiée, CLI, services, CI, installer/rollback/offline | Enrôlement runner, accès hôte et test BC réel indispensables |

## Décisions

ADR-001 : moteur existant llama-server direct ; pas de dépendance Studio ou recompilation introduisant une nouvelle variable de performances.

ADR-002 : un modèle résident TranslateGemma 12B Q4_K_M, un consommateur GPU ; pas de double modèle resident. La revue humaine et les contrôles déterministes sont prioritaires avec cette mémoire.

ADR-003 : conserver objets PDF natifs ; refus sûr des zones non composables. Aucun traitement terminé ne devient approuvé sans révision.

ADR-004 : PostgreSQL durable, filesystem adressé par contenu, monolithe modulaire. SQLite limité au développement mono-hôte. Pas de nouvelle file externe.

ADR-005 : source immuable, révisions et contrats explicitement liés aux SHA. Une reprise sous un autre modèle doit créer un nouveau job.

ADR-006 : contextes riches stockés mais template spécialisé strict. Ne pas prétendre que TranslateGemma traite automatiquement des instructions de glossaire arbitraires.

ADR-007 : AGPL-3.0-or-later pour le projet avec PyMuPDF ; licences des poids distinctes, aucun poids ajouté au dépôt.

## États

`queued → running → ready_for_review → approved`, avec branches `runtime_failed` (reprenable) et `quality_blocked` (correction nécessaire). Lease expiré = reprise automatique ; correction = traduction préservée, recomposition de la version suivante. Une version approuvée n’est pas modifiable.

## Contrats

`extract(bytes,format) → DocumentIR`, `LlamaTranslator.translate(source) → cible,provenance`, `build(source,IR,cibles) → artefact,QualityReport`. L’application ne peut publier un candidat comme approuvé si `QualityReport.blocked` est vrai. Les objets sont écrits atomiquement avant référence en base ; des orphelins après crash peuvent être réconciliés, pas automatiquement supprimés sans inventaire.

## Validation avant remplacement de DocTrad actuel

Première gate : test réel sur le runtime BC résident. Deuxième : référence TSM et AN/PRC-167 avec revue des régions signalées, valeur/cellule/ref critique = 0. Troisième : corpus varié et long, reprise/rollback/restauration. Coexistence maintenue jusqu’à satisfaction des gates. Les tests simulés de l’application ne franchissent pas à eux seuls ces gates.
