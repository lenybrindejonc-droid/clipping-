"""Met le site en ligne sur Hugging Face Spaces (privé), en une commande : ./deploy_hf.sh"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parent
SPACE_NAME = "clipping"


def read_env() -> dict[str, str]:
    env = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _memoriser_env(valeurs: dict) -> None:
    """Note l'adresse du site (et son mot de passe) dans .env, pour les scripts locaux."""
    fichier = ROOT / ".env"
    lignes = fichier.read_text().splitlines() if fichier.exists() else []
    for cle, valeur in valeurs.items():
        lignes = [l for l in lignes if not l.startswith(f"{cle}=")]
        lignes.append(f"{cle}={valeur}")
    fichier.write_text("\n".join(lignes) + "\n")
    fichier.chmod(0o600)


def main() -> None:
    env = read_env()
    print("\n🔑 Il faut un « token » Hugging Face avec le droit d'écriture :")
    print("   https://huggingface.co/settings/tokens → Create new token → type « Write »\n")
    token = input("Colle ton token Hugging Face (clic droit) puis Entrée : ").strip()
    if not token.startswith("hf_"):
        sys.exit("❌ Ce n'est pas un token Hugging Face (il doit commencer par hf_).")

    api = HfApi(token=token)
    user = api.whoami()["name"]
    repo_id = f"{user}/{SPACE_NAME}"
    print(f"\n👤 Connecté en tant que {user}")

    # 1. Space : privé à la création, puis on respecte ton choix
    existait = True
    try:
        api.repo_info(repo_id, repo_type="space")
    except Exception:
        existait = False
    try:
        api.create_repo(repo_id, repo_type="space", space_sdk="docker", private=True, exist_ok=True)
    except Exception as exc:
        if "402" in str(exc) or "Payment Required" in str(exc):
            sys.exit(
                "\n❌ Hugging Face demande un abonnement PRO (~9 $/mois) pour héberger ce type de site.\n"
                "   Les Spaces gratuits ne permettent que des pages statiques.\n"
                "   → S'abonner : https://huggingface.co/pro\n"
                "   → Ou garder le site sur ton PC avec ./start.sh"
            )
        raise
    prive = api.repo_info(repo_id, repo_type="space").private
    if existait:
        etat = "privé" if prive else "public (protégé par ton mot de passe)"
        print(f"📦 Space existant, laissé {etat} : {repo_id}")
        if prive:
            print("   ⚠️  Un Space privé ne s'ouvre pas depuis Safari iOS ni depuis programmer.sh.")
            print("      Pour le rendre public : Settings → Change visibility sur huggingface.co")
    else:
        print("🔒 Space privé créé :", repo_id)

    # 2. Secrets (chiffrés chez Hugging Face, jamais dans le code)
    secrets = {k: env.get(k, "") for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY")}
    if not secrets["ANTHROPIC_API_KEY"].startswith("sk-ant-"):
        print("⚠️  Pas de clé Claude dans .env : les moments seront choisis en mode basique.")
    if not secrets["GROQ_API_KEY"].startswith("gsk_"):
        print("⚠️  Pas de clé Groq dans .env : la transcription sera lente.")
    pw = input("\nChoisis un mot de passe pour ton site (Entrée = pas de mot de passe) : ").strip()
    if pw:
        secrets["APP_PASSWORD"] = pw
    cookies = ROOT / "cookies.txt"
    if cookies.exists():
        secrets["YT_COOKIES"] = cookies.read_text()
        print("🍪 Cookies YouTube trouvés : ajoutés en secret.")
    for k, v in secrets.items():
        if v:
            api.add_space_secret(repo_id, k, v)
    for k in ("CLAUDE_MODEL", "YT_PLAYER_CLIENTS"):
        if env.get(k):
            api.add_space_variable(repo_id, k, env[k])
    api.add_space_variable(repo_id, "TRANSCRIBE_FALLBACK", "1")  # serveur plus puissant : repli local OK
    print("🔐 Clés enregistrées dans les Secrets du Space.")

    # 3. Code
    api.upload_folder(
        repo_id=repo_id, repo_type="space", folder_path=ROOT,
        allow_patterns=["app/*.py", "static/*", "requirements.txt", "Dockerfile"],
        delete_patterns=["app/*", "static/*"], commit_message="Mise à jour du site",
    )
    api.upload_file(path_or_fileobj=ROOT / "hf" / "README.md", path_in_repo="README.md",
                    repo_id=repo_id, repo_type="space", commit_message="Configuration du Space")

    sub = re.sub(r"[^a-z0-9-]", "-", f"{user}-{SPACE_NAME}".lower())
    _memoriser_env({"SITE_URL": f"https://{sub}.hf.space", **({"APP_PASSWORD": pw} if pw else {})})

    print("\n✅ C'est en ligne ! La construction prend ~5 minutes la première fois.")
    print(f"   Suivi :      https://huggingface.co/spaces/{repo_id}")
    print(f"   Ton site :   https://{sub}.hf.space  (connecte-toi d'abord à huggingface.co)")


if __name__ == "__main__":
    main()
