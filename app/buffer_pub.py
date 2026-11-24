"""Envoi des clips dans la file Buffer (TikTok + YouTube Shorts), sans rien faire à la main.

Buffer ne reçoit pas de fichier : il lui faut un lien public vers chaque vidéo, valable
jusqu'au jour de la publication. Le site efface ses fichiers quand Hugging Face redémarre,
donc chaque clip est d'abord rangé sur Cloudinary (gratuit, conseillé par Buffer), puis
envoyé à Buffer avec ce lien.

Réglages (secrets du Space, jamais dans le code) :
  BUFFER_API_KEY   clé personnelle : publish.buffer.com/settings/api
  CLOUDINARY_URL   cloudinary://CLE:SECRET@NOM_DU_CLOUD (tableau de bord Cloudinary)
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path

import httpx

BUFFER_URL = "https://api.buffer.com"
DOSSIER = "clipping"          # dossier des clips sur Cloudinary
GARDER_JOURS = 21             # au-delà, la vidéo a été publiée : on libère la place
CATEGORIE_YOUTUBE = os.getenv("YOUTUBE_CATEGORIE", "24")   # 24 = Divertissement
SERVICES = ("tiktok", "youtube")


class ErreurEnvoi(RuntimeError):
    """Erreur expliquée en français, affichée telle quelle sur le site."""


# ------------------------------------------------------------------ réglages
def _cloudinary() -> tuple[str, str, str] | None:
    url = os.getenv("CLOUDINARY_URL", "").strip()
    m = re.fullmatch(r"cloudinary://([^:]+):([^@]+)@(.+)", url)
    return (m.group(3), m.group(1), m.group(2)) if m else None


def configure() -> dict:
    """Ce qui manque pour envoyer (vide = tout est prêt)."""
    manque = []
    if not os.getenv("BUFFER_API_KEY", "").strip():
        manque.append("BUFFER_API_KEY")
    if not _cloudinary():
        manque.append("CLOUDINARY_URL")
    return {"pret": not manque, "manque": manque}


# ------------------------------------------------------------------ Buffer
def _graphql(requete: str, variables: dict | None = None) -> dict:
    cle = os.getenv("BUFFER_API_KEY", "").strip()
    try:
        r = httpx.post(BUFFER_URL, json={"query": requete, "variables": variables or {}},
                       headers={"Authorization": f"Bearer {cle}"}, timeout=60)
    except httpx.HTTPError as exc:
        raise ErreurEnvoi(f"Buffer injoignable ({exc.__class__.__name__})") from exc
    if r.status_code == 401:
        raise ErreurEnvoi("clé Buffer refusée : recrée-la sur publish.buffer.com/settings/api")
    if r.status_code == 429:
        raise ErreurEnvoi("trop de demandes à Buffer : réessaie dans 15 minutes")
    if r.status_code >= 400:
        raise ErreurEnvoi(f"Buffer a répondu {r.status_code} : {r.text[:200]}")
    data = r.json()
    if data.get("errors"):
        raise ErreurEnvoi("Buffer : " + "; ".join(e.get("message", "?") for e in data["errors"])[:300])
    return data["data"]


def chaines() -> list[dict]:
    """Chaînes TikTok et YouTube connectées à Buffer."""
    orgs = _graphql("query { account { organizations { id name } } }")["account"]["organizations"]
    sortie = []
    for org in orgs:
        liste = _graphql(
            "query($org: OrganizationId!) { channels(input: {organizationId: $org}) "
            "{ id name displayName service isQueuePaused } }", {"org": org["id"]})["channels"]
        sortie += [{"id": c["id"], "nom": c.get("displayName") or c["name"], "service": c["service"],
                    "en_pause": c.get("isQueuePaused", False)}
                   for c in liste if c["service"] in SERVICES]
    return sortie


CREER = """
mutation($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id dueAt } }
    ... on MutationError { message }
  }
}"""


def _sans_chevrons(texte: str) -> str:
    return texte.replace("<", "‹").replace(">", "›")   # YouTube refuse < et >


def textes_du_clip(clip: dict) -> dict:
    """Légende TikTok, titre et description YouTube, depuis ce que le site a déjà écrit."""
    caps = clip.get("captions") or {}
    hashtags = " ".join(h if h.startswith("#") else f"#{h}" for h in clip.get("hashtags") or [])
    defaut = f"{clip.get('description') or clip.get('title') or ''}\n\n{hashtags}".strip()
    youtube = (caps.get("youtube") or "").strip()
    lignes = [l for l in youtube.splitlines() if l.strip()]
    titre = lignes[0] if lignes else (clip.get("title") or "Clip")
    description = "\n".join(lignes[1:]) if len(lignes) > 1 else defaut
    if "#shorts" not in description.lower():
        description += "\n#Shorts"
    return {
        "tiktok": (caps.get("tiktok") or defaut)[:2200],
        "youtube_titre": _sans_chevrons(re.sub(r"\s+", " ", titre).strip())[:100],
        "youtube_description": _sans_chevrons(description)[:5000],
    }


def creer_publication(chaine: dict, url_video: str, textes: dict, brouillon: bool = False) -> dict:
    """Ajoute le clip à la file de la chaîne (publication automatique au prochain créneau)."""
    entree: dict = {
        "channelId": chaine["id"],
        "schedulingType": "automatic",
        "mode": "addToQueue",
        "assets": [{"video": {"url": url_video}}],
        "saveToDraft": brouillon,
    }
    if chaine["service"] == "youtube":
        entree["text"] = textes["youtube_description"]
        entree["metadata"] = {"youtube": {"title": textes["youtube_titre"],
                                          "categoryId": CATEGORIE_YOUTUBE,
                                          "privacy": "public", "madeForKids": False}}
    else:
        entree["text"] = textes["tiktok"]
    res = _graphql(CREER, {"input": entree})["createPost"]
    if "message" in res and "post" not in res:
        raise ErreurEnvoi(f"{chaine['nom']} : {res['message']}")
    return res["post"]


# ------------------------------------------------------------------ Cloudinary
def _signature(params: dict, secret: str) -> str:
    chaine = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hashlib.sha1((chaine + secret).encode()).hexdigest()


def heberger(fichier: Path, nom: str) -> str:
    """Range la vidéo sur Cloudinary et renvoie son lien public, direct et durable."""
    conf = _cloudinary()
    if not conf:
        raise ErreurEnvoi("CLOUDINARY_URL manquant dans les réglages du site")
    cloud, cle, secret = conf
    params = {"folder": DOSSIER, "public_id": re.sub(r"[^\w-]", "_", nom)[:80],
              "overwrite": "true", "timestamp": str(int(time.time()))}
    params["signature"] = _signature(params, secret)
    params["api_key"] = cle
    try:
        with fichier.open("rb") as f:
            r = httpx.post(f"https://api.cloudinary.com/v1_1/{cloud}/video/upload",
                           data=params, files={"file": (fichier.name, f, "video/mp4")}, timeout=300)
    except httpx.HTTPError as exc:
        raise ErreurEnvoi(f"Cloudinary injoignable ({exc.__class__.__name__})") from exc
    if r.status_code in (401, 403):
        raise ErreurEnvoi("clés Cloudinary refusées : recopie CLOUDINARY_URL depuis ton tableau de bord")
    if r.status_code >= 400:
        detail = r.json().get("error", {}).get("message", r.text[:200]) if r.headers.get(
            "content-type", "").startswith("application/json") else r.text[:200]
        raise ErreurEnvoi(f"Cloudinary : {detail}")
    return r.json()["secure_url"]


def menage() -> int:
    """Supprime de Cloudinary les clips envoyés il y a plus de 3 semaines (déjà publiés),
    pour rester dans l'offre gratuite. Renvoie le nombre de vidéos supprimées."""
    conf = _cloudinary()
    if not conf:
        return 0
    cloud, cle, secret = conf
    base = f"https://api.cloudinary.com/v1_1/{cloud}/resources/video/upload"
    try:
        r = httpx.get(base, params={"prefix": f"{DOSSIER}/", "max_results": 500},
                      auth=(cle, secret), timeout=60)
        r.raise_for_status()
        limite = time.time() - GARDER_JOURS * 86400
        vieux = [res["public_id"] for res in r.json().get("resources", [])
                 if time.mktime(time.strptime(res["created_at"][:19], "%Y-%m-%dT%H:%M:%S")) < limite]
        if vieux:
            httpx.request("DELETE", base, params=[("public_ids[]", p) for p in vieux[:100]],
                          auth=(cle, secret), timeout=60).raise_for_status()
        return len(vieux[:100])
    except Exception as exc:                 # le ménage ne doit jamais bloquer un envoi
        print(f"[buffer] ménage Cloudinary impossible ({exc})", flush=True)
        return 0


def envoyer(fichier: Path, nom: str, clip: dict, ids_chaines: list[str] | None = None,
            brouillon: bool = False) -> list[dict]:
    """Héberge le clip puis l'ajoute à la file de chaque chaîne. Renvoie un résultat par chaîne."""
    toutes = chaines()
    cibles = [c for c in toutes if not ids_chaines or c["id"] in ids_chaines]
    if not cibles:
        raise ErreurEnvoi("aucune chaîne TikTok ou YouTube connectée à Buffer")
    url = heberger(fichier, nom)
    textes = textes_du_clip(clip)
    resultats = []
    for c in cibles:
        try:
            post = creer_publication(c, url, textes, brouillon)
            resultats.append({"chaine": c["nom"], "service": c["service"], "ok": True,
                              "prevu": post.get("dueAt")})
        except ErreurEnvoi as exc:
            resultats.append({"chaine": c["nom"], "service": c["service"], "ok": False,
                              "erreur": str(exc)})
    return resultats
