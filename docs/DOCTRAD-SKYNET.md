# DocTrad sur le serveur actuel ; inférence seule sur SKYNET

Branche : `Doctrad-Skynet`. Cette branche ne remplace pas la production BC250.

## Répartition décidée

Le serveur DocTrad conserve l'application, l'authentification, les originaux, les aperçus,
la structure documentaire, les versions, les tâches, le contexte, les mémoires de traduction,
les contrôles et la composition des livrables. Le socle conserve ces données dans un magasin
local isolé ; l'intégration à l'interface et à la file persistante est une étape ultérieure.

SKYNET (192.168.6.44) hébergera uniquement les modèles, le moteur d'inférence et leurs dépendances.
Aucun dépôt applicatif, base documentaire, worker métier, stockage permanent de documents ni
interface DocTrad n'y sera installé. Les images/segments nécessaires transitent dans les requêtes
d'inférence et dans la mémoire du moteur. La journalisation des prompts et caches persistants
devra être vérifiée lors de la configuration du moteur.

Aucune connexion, découverte réseau ni installation sur SKYNET n'est autorisée par les workflows
de cette première étape. Une demande à l'utilisateur est requise avant cette étape.

## Socle implémenté

- Import natif CPU PDF/DOCX/PPTX, original et structure conservés, aperçus PNG pour les PDF.
- Objets adressés par SHA256, vérification à la lecture, révisions non réécrites et contrôle
  de concurrence sur la tête de traduction. Le texte source ne fait pas partie des patches.
- Plan de traduction par bloc/sous-partie avec contexte de section, voisinage et en-têtes de tableau.
- Client vers les seuls endpoints HTTPS de SKYNET, sans redirections ni proxy d'environnement.
- Adaptation au moteur llama.cpp : application du template et tokenisation exactes avant
  la génération textuelle ; rejet des dépassements de contexte, fins tronquées, mauvais modèles
  et réponses visant un autre bloc. Les entrées image demandent encore une qualification du
  budget visuel propre au moteur. Les deux rôles ne sont pas interchangeables.
- Réponses candidates avec provenance, contrôles techniques existants et révision locale.
- Export natif de référence réutilisant le moteur de composition actuel, avec blocage sur
  anomalies critiques. Toute sortie reste à relire. Ce n'est pas encore le nouveau compositeur.

Un scan sans extraction exploitable reste bloqué tant que sa lecture visuelle n'est pas résolue.
Le client de lecture d'image est préparé ; la fusion des résultats OCR avec leurs géométries,
la comparaison multi-lectures et la revue visuelle restent à implémenter/qualifier.

## Modèles candidats, pas encore qualifiés

Vision : Qwen3-VL-8B original comme référence et
HauhauCS/Qwen3VL-8B-Uncensored-HauhauCS-Aggressive comme candidat utilisateur, avec son mmproj F16.
Profil de départ envisagé : Q8_0. L'auteur conseille Balanced pour les tâches de fiabilité critique :
https://huggingface.co/HauhauCS/Qwen3VL-8B-Uncensored-HauhauCS-Aggressive
La fidélité OCR de la variante Aggressive ne sera pas supposée égale à celle de l'original.

Traduction : Qwen3-32B pour les unités contextualisées, à comparer à TranslateGemma 27B pour
des unités bornées. Les fichiers exacts, révisions, empreintes, moteurs, formats et budgets GPU
seront qualifiés avant activation. Aucun téléchargement de modèle n'est lancé par ce socle.

`deploy/skynet-inference.example.json` est un contrat préparatoire : ports et alias proposés,
empreintes non renseignées et `remote_enabled=false`. Il n'atteste aucun service installé.
Les clés restent dans des variables d'environnement sur DocTrad ; elles ne sont pas enregistrées
dans les objets de provenance. Le CA reste également local à DocTrad.

## Utilisation locale sur DocTrad

```bash
PYTHONPATH=src python -m doctrad2.skynet_cli --root /chemin/stockage-local import source.pdf
PYTHONPATH=src python -m doctrad2.skynet_cli --root /chemin/stockage-local plan SHA_DOCUMENT
PYTHONPATH=src python -m doctrad2.skynet_cli --root /chemin/stockage-local readiness \
  --config deploy/skynet-inference.example.json
```

`revise` accepte un objet JSON `{identifiant_bloc: traduction}` avec `--updates`, `--actor`,
`--reason` et la révision courante `--base` (omise pour la première révision).
`export` exige une traduction complète et sans anomalie critique. `translate` utilise le client
distant et reste bloqué avec la configuration d'exemple. Aucune activation implicite ou bascule
vers un autre moteur n'est effectuée.

## Suite du plan

1. Valider ce socle et le préparer dans un répertoire séparé sur le serveur DocTrad.
2. Demander l'autorisation de connexion à SKYNET, inventorier son moteur et les modèles présents.
3. Configurer/qualifier les endpoints stateless et leurs identités ; tester les variantes de modèles.
4. Intégrer lecture visuelle, couverture des blocs et mémoire terminologique à la file de tâches.
5. Construire l'interface de révision et les deux sorties : fidèle et recomposée.
6. Mesurer les gains sur plusieurs documents inconnus avant toute promotion en production.
