# Politique générale — technical-flow-3.0

Cette politique ne contient aucun nom de document, identifiant de produit ou remplacement lexical propre à une référence. Les textes et empreintes des documents d’essai sont confinés aux benchmarks.

## Traduction

Les retours à la ligne de mise en page sont normalisés sans supprimer les tirets. Les phrases complètes sont traduites séparément. Les puces sont séparées du contenu puis rétablies.

Le profil technique direct utilise une consigne identique pour tous les fichiers : français concis, fidélité du sens, du degré des qualificatifs, des quantités, unités, négations et libellés formels ; aucune conversion, expansion d’acronyme ou explication ajoutée. Il est rendu côté client et envoyé à `/completion` avec les tokens réels. Son empreinte est inscrite dans le contrat. Ce profil manuel a été comparé au template initial et à une variante de celui-ci sur six contrôles publics indépendants. Il ne constitue pas une garantie de fidélité sémantique.

Les exemples terminologiques produits par le modèle ne sont pas réinjectés : les essais ont montré qu’ils pouvaient renforcer une mauvaise traduction. Aucun dictionnaire thématique de remplacement n’est appliqué.

## Reprises et littéraux

Un essai alternatif borné traite les candidats qui violent les invariants ou développent excessivement un fragment court. Un dernier essai peut isoler les mesures, dimensions et références avec des marqueurs dérivés de la source. Chaque marqueur doit revenir exactement une fois ; sinon le résultat est rejeté. Le budget réel de tokens est contrôlé avant cet essai. Les URL et champs entièrement constitués de littéraux restent intacts.

Une restauration d’unité n’est permise que si les nombres sont inchangés et que la valeur concernée possède une seule unité source. Le résultat doit retrouver toutes les mesures source. Les conversions et ambiguïtés ne sont jamais réparées par supposition. Les candidats bruts, choix, rejets et restaurations sont tracés.

## Contrôles

Les contrôles distinguent les intervalles, signes, versions, descriptions numériques, références, puissances d’unités et unités partagées des dimensions. Ils prennent en compte les annotations d’axes. Une écriture étrangère ajoutée est critique. Les expressions en capitales traduites restent soumises à révision, sans lexique imposé. Les contrôles numériques ne certifient pas le sens d’un texte.

Les erreurs de transport temporaires disposent d’une reprise bornée laissant le temps au service BC250 de redémarrer. Les erreurs d’authentification ou de protocole ne sont pas assimilées à ces indisponibilités. Les unités déjà enregistrées sont conservées.

## Composition

Le style dominant est pondéré par le texte : une puce ne colore pas le paragraphe et un exposant ne réduit pas tout le bloc. Les colonnes gardent une marge, les extensions sont bornées par les textes, images et séparateurs. Une cellule artificielle ne peut être plus étroite que la ligne source qu’elle contient. Les lignes de base sont conservées lorsque la géométrie le permet. Les textes inclinés sont recomposés vectoriellement dans leur repère propre.

Si le texte ne tient pas, la source est conservée et une erreur critique est produite. Un candidat ne devient pas correct parce que la composition réussit. Les liens sont préservés et vérifiés après réouverture du PDF.

## Versions et essais

La politique et l’empreinte de prompt font partie du contrat et des clés de référence. Les versions de composition et de qualité figurent dans le rapport. Une recomposition peut réévaluer les candidats conservés sans nouvelle inférence lorsque leur contrat de traduction est identique.

Les tests couvrent des cas variés indépendants. Les essais de déploiement utilisent une fiche existante et un guide d’équipement synthétique distinct, tous deux traités par le vrai worker et la BC250. Un résultat `quality_blocked` n’est jamais déclaré approuvé.
