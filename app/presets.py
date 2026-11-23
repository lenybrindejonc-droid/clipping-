"""Réglages spécialisés par type de contenu.

Chaque type a ses propres critères de choix, sa durée idéale, son cadrage et son style de
sous-titres : ce qui fait un bon short de gaming n'a rien à voir avec un extrait de podcast.
"""
from __future__ import annotations

PRESETS: dict[str, dict] = {
    "auto": {
        "nom": "Général",
        "zoom": True,
        "n": 5, "min_d": 15, "max_d": 40, "layout": "auto",
        "sous_titres": {"mots": 3, "taille": 96, "hauteur": 0.27},
        "consignes": "",
    },

    "gaming": {
        "nom": "Gaming (stream, let's play)",
        "zoom": True,
        "n": 5, "min_d": 10, "max_d": 25, "layout": "gaming",
        "sous_titres": {"mots": 3, "taille": 96, "hauteur": 0.27},
        "consignes": """CONTENU : partie de jeu (let's play, stream).

Un pic sonore montre qu'il s'est passé quelque chose ; à toi de décider si c'est un vrai clip,
et où il commence et finit.

Ce qui fait un bon clip :
- Les 2 premières secondes donnent envie de rester. Commence SUR le moment fort (le crash,
  le cri, la police qui débarque), jamais sur la mise en place : les gens partent à 1 seconde.
- Le dénouement est DANS le clip (le crash, l'évasion, le raté, la phrase qui fait rire).
  Termine 1 à 2 secondes après la réaction, pas 20 secondes plus tard.
- Il se comprend seul : si la blague demande 10 minutes de contexte, ignore-la.
- Le joueur réagit. Du gameplay impressionnant avec un joueur silencieux vaut moins qu'une
  vraie réaction humaine.
- Aucun temps mort : silences longs, menus, chargements, carte, inventaire.
- Court : 10 à 25 secondes, 30 au grand maximum.

Ce qui marche : poursuites et évasions, crashs et chutes, braquages qui tournent mal,
comportement absurde des PNJ, cascade parfaite, le joueur qui craque, échange drôle.

À ne JAMAIS choisir : cinématiques isolées ou scènes de l'histoire seules ; émissions TV ou
radio du jeu prises seules ; triche, exploits d'argent ou d'XP, menus de mods, bugs donnant
un avantage en ligne ; moments portés par une musique tierce jouée fort (risque de
réclamation de droits) ; informations privées lues à voix haute, harcèlement.
Si un clip dévoile l'histoire ou la fin du jeu, mets "spoiler": true.

Accroche : 3 à 7 mots, elle prépare le dénouement sans le révéler
(exemple de forme : « Il pensait que les flics étaient partis »).
Titre : dit simplement ce qui se passe, sans fausse promesse.
Description : crédite le joueur et rappelle que la vidéo source est à créditer.

Sois sévère : ne propose que des passages à 60 ou plus, quitte à en rendre moins que demandé.
Mieux vaut 3 clips forts que 8 moyens.""",
    },

    "podcast": {
        "nom": "Podcast / interview",
        "zoom": False,
        "n": 6, "min_d": 25, "max_d": 60, "layout": "blur",
        "sous_titres": {"mots": 4, "taille": 86, "hauteur": 0.22},
        "consignes": """CONTENU : discussion, interview, podcast.

Ici tout repose sur la PAROLE : le niveau sonore compte moins que dans le gaming, sauf pour
repérer les rires et les moments où les voix se chevauchent (désaccord, surprise).

Ce qui fait un bon clip :
- Une idée ENTIÈRE : la question ou l'amorce, le développement, la conclusion. Un extrait qui
  commence au milieu d'un raisonnement ne marche pas.
- Une affirmation tranchée, qui prend position et qui fait réagir en commentaire.
- Une histoire personnelle courte et complète, avec sa chute.
- Un chiffre ou une révélation concrète qui surprend.
- Un désaccord franc entre deux intervenants : c'est ce qui crée le plus d'engagement.
- Un conseil applicable immédiatement, formulé simplement.

Préfère un clip de 30 à 60 secondes : une idée a besoin d'air. Mais coupe tout ce qui n'est
pas nécessaire au raisonnement : digressions, exemples répétitifs, « euh », remerciements.

À écarter : présentations et remerciements du début, promotions et sponsors,les private jokes
entre invités, passages où l'on ne comprend pas qui parle, extraits qui citent longuement une
œuvre protégée.

Accroche : la phrase la plus tranchée du clip, ou la question qu'il pose.
Titre : l'idée défendue, pas « il dit une chose incroyable ».
Si l'extrait peut être mal compris sorti de son contexte, ne le propose pas.""",
    },

    "vlog": {
        "nom": "Vlog / face caméra",
        "zoom": True,
        "n": 5, "min_d": 20, "max_d": 45, "layout": "crop",
        "sous_titres": {"mots": 3, "taille": 92, "hauteur": 0.25},
        "consignes": """CONTENU : vlog, vidéo face caméra, récit personnel.

Ce qui fait un bon clip :
- Une anecdote complète : situation, péripétie, chute. Le spectateur doit pouvoir la raconter
  à quelqu'un d'autre après l'avoir vue.
- Un moment d'émotion sincère : fatigue, joie, colère, aveu. C'est ce qui crée l'attachement.
- Un conseil concret, applicable sans rien connaître du reste de la vidéo.
- Un retournement : « je pensais que… en fait non ».

Commence sur la phrase qui pose la situation, jamais au milieu d'une explication.
Écarte : les salutations et abonnements du début, les transitions, les passages où la personne
cherche ses mots, les références à des vidéos précédentes.

Accroche : la situation de départ, en 3 à 7 mots.
Titre : ce qui arrive, sans exagération.""",
    },

    "tuto": {
        "nom": "Tuto / formation",
        "zoom": False,
        "n": 6, "min_d": 25, "max_d": 60, "layout": "auto",
        "sous_titres": {"mots": 4, "taille": 86, "hauteur": 0.22},
        "consignes": """CONTENU : tutoriel, explication, formation.

Ce qui fait un bon clip :
- UNE astuce complète par clip : le problème, la manipulation, le résultat. Jamais la moitié
  d'une procédure.
- Une erreur fréquente et sa correction : c'est le format qui marche le mieux.
- Un raccourci ou une méthode qui fait gagner du temps, énoncée clairement.
- Un avant/après visible ou chiffré.

Le spectateur doit pouvoir appliquer l'astuce sans voir le reste de la vidéo. Si une étape
dépend d'une manipulation faite plus tôt, écarte le passage.

Écarte : l'introduction, l'installation du matériel, les digressions, les passages où
l'intervenant hésite ou se reprend.

Accroche : le problème résolu, formulé comme une question ou un bénéfice.
Titre : l'astuce elle-même, concrètement.""",
    },

    "humour": {
        "nom": "Humour / sketch",
        "zoom": True,
        "n": 6, "min_d": 15, "max_d": 35, "layout": "auto",
        "sous_titres": {"mots": 3, "taille": 96, "hauteur": 0.27},
        "consignes": """CONTENU : humour, sketch, moments drôles.

Ce qui fait un bon clip :
- La CHUTE est dans le clip, et elle tombe dans les 30 dernières secondes au plus tard.
- La mise en place est la plus courte possible : juste ce qu'il faut pour comprendre.
- Les rires (niveau sonore élevé) sont un signal fiable : cherche ce qui les a déclenchés,
  puis remonte jusqu'au début de la blague.
- Un enchaînement rapide vaut mieux qu'une blague qui s'étire.

Termine 1 seconde après la chute, jamais sur un blanc.
Écarte : les blagues qui dépendent d'un épisode précédent, celles qui visent une personne
réelle de façon humiliante, et tout ce qui repose sur une musique protégée.

Accroche : la situation avant la chute, sans la révéler.
Titre : factuel, la chute ne doit pas être dans le titre.""",
    },

    "sport": {
        "nom": "Sport / performance",
        "zoom": True,
        "n": 5, "min_d": 15, "max_d": 35, "layout": "blur",
        "sous_titres": {"mots": 3, "taille": 92, "hauteur": 0.25},
        "consignes": """CONTENU : sport, performance physique, compétition.

Ce qui fait un bon clip :
- L'action décisive avec sa préparation : on doit voir venir le geste, puis son résultat.
- La réaction qui suit : commentateur, public, athlète. Sans réaction, l'action retombe.
- Un enjeu clair : si le commentaire explique ce qui se joue, le clip devient compréhensible
  par tous.
- Un échec spectaculaire fonctionne aussi bien qu'une réussite.

Commence 2 à 3 secondes avant l'action, termine sur la réaction.
Écarte : les temps morts, les analyses longues, les passages sans image d'action.

Attention : beaucoup de retransmissions sportives sont protégées. Ne propose que des passages
issus de la vidéo fournie, et signale dans la description qu'il faut créditer la source.

Accroche : l'enjeu, en 3 à 7 mots.
Titre : ce qui se passe, sans superlatif inventé.""",
    },
}


def get(content_type: str) -> dict:
    return PRESETS.get(content_type, PRESETS["auto"])


def consignes(content_type: str) -> str:
    return get(content_type)["consignes"]
