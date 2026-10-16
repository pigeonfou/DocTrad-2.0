# Politique générale — technical-flow-3.2

Cette politique ne contient aucun nom de document, identifiant de produit ou remplacement lexical propre à une référence. Les textes et empreintes des documents d’essai sont confinés aux benchmarks.

## Traduction

Les retours à la ligne de mise en page sont normalisés sans supprimer les tirets. Les phrases complètes sont traduites séparément. Les puces sont séparées du contenu puis rétablies.

Le profil technique direct utilise une consigne identique pour tous les fichiers : français concis, fidélité du sens, du degré des qualificatifs, des quantités, unités, négations et libellés formels ; aucune conversion, expansion d’acronyme ou explication ajoutée. Il est rendu côté client et envoyé à `/completion` avec les tokens réels. Son empreinte est inscrite dans le contrat. Ce profil manuel a été comparé au template initial et à une variante de celui-ci sur six contrôles publics indépendants. Il ne constitue pas une garantie de fidélité sémantique.

Les exemples terminologiques produits par le modèle ne sont pas réinjectés : les essais ont montré qu’ils pouvaient renforcer une mauvaise traduction. Aucun dictionnaire thématique de remplacement n’est appliqué. Les fragments courts d’un tableau reçoivent ses titres et les passages voisins déjà extraits, distincts du texte à traduire. Ce contexte est borné et compte dans le budget réel de tokens.

## Reprises et littéraux

Un essai alternatif borné traite les candidats qui violent les invariants. Une écriture étrangère ajoutée déclenche une contrainte de décodage autorisant le français, les symboles techniques et les caractères déjà présents dans la source. Aucun caractère n’est supprimé après génération. Un dernier essai peut isoler les mesures, dimensions, références, libellés de plusieurs mots en capitales dans la prose et sigles omis avec des marqueurs dérivés de la source. Chaque marqueur doit revenir exactement une fois ; sinon le résultat est rejeté. Aucune liste de libellés métier n’existe dans le moteur. Le budget réel de tokens est contrôlé pour chaque génération. Les URL et champs entièrement constitués de littéraux restent intacts. À qualité égale, le premier candidat est conservé : la brièveté ne prouve pas la fidélité.

Une restauration d’unité n’est permise que si les nombres sont inchangés et que la valeur concernée possède une seule unité source. Le résultat doit retrouver toutes les mesures source. Les conversions et ambiguïtés ne sont jamais réparées par supposition. Les candidats bruts, choix, rejets et restaurations sont tracés.

## Contrôles

Les contrôles distinguent les intervalles, signes, versions, descriptions numériques, références, puissances d’unités et unités partagées des dimensions. Ils prennent en compte les annotations d’axes. Une écriture étrangère ajoutée, un sigle omis dans la prose ou un libellé formel remplacé sont critiques. La ponctuation ajoutée entre mots d’un libellé ne constitue pas à elle seule un changement de sens. Les contrôles numériques ne certifient pas le sens d’un texte.

Une graphie d’unité inconnue ne peut être rapprochée d’une graphie source connue que si elles diffèrent d’une seule lettre, ont la même longueur et accompagnent la même valeur dans le même passage. Une correspondance unique est nécessaire. La source reste intacte et le rapprochement produit une alerte de révision humaine ; une mesure différente reste bloquante. La conservation de la graphie source ambiguë reste possible avec cette même alerte. Sans preuve locale, aucun rapprochement n’est effectué.

Les erreurs de transport temporaires disposent d’une reprise bornée laissant le temps au service BC250 de redémarrer. Les erreurs d’authentification ou de protocole ne sont pas assimilées à ces indisponibilités. Les unités déjà enregistrées sont conservées.

## Composition

Le style dominant est pondéré par le texte : une puce ne colore pas le paragraphe et un exposant ne réduit pas tout le bloc. Les colonnes gardent une marge, les extensions sont bornées par les textes, images et séparateurs. Une cellule artificielle ne peut être plus étroite que la ligne source qu’elle contient. Les lignes de base sont conservées lorsque la géométrie le permet : un ajustement facultatif ne peut pas invalider un bloc français qui tient déjà. Les textes inclinés sont recomposés vectoriellement dans leur repère propre.

Si le texte ne tient pas, la source est conservée et une erreur critique est produite. Un candidat ne devient pas correct parce que la composition réussit. Les liens sont préservés et vérifiés après réouverture du PDF.

## Versions et essais

La politique et l’empreinte de prompt font partie du contrat et des clés de référence. Les versions de composition et de qualité figurent dans le rapport. Une recomposition peut réévaluer les candidats conservés sans nouvelle inférence lorsque leur contrat de traduction est identique.

Les tests couvrent des cas variés indépendants. Les essais de déploiement utilisent une fiche existante et un guide d’équipement synthétique distinct, tous deux traités par le vrai worker et la BC250. Un résultat `quality_blocked` n’est jamais déclaré approuvé.

