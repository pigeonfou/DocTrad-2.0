import argparse
import getpass
import json
from argon2 import PasswordHasher
from .config import Settings
from .db import Database, User
from .pipeline import Pipeline
from .inference import LlamaTranslator


def main():
    p = argparse.ArgumentParser(prog="doctrad2")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    user = sub.add_parser("create-user")
    user.add_argument("username")
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    sub.add_parser("diagnose")
    sub.add_parser("serve")
    args = p.parse_args()
    settings = Settings.load()
    settings.root.mkdir(parents=True, exist_ok=True)
    db = Database(settings.database_url)
    db.migrate()
    if args.command == "create-user":
        password = getpass.getpass("Mot de passe : ")
        if len(password) < 12:
            p.error("12 caractères minimum")
        with db.session() as s:
            if s.get(User, args.username):
                p.error("Utilisateur déjà existant")
            s.add(User(name=args.username, password=PasswordHasher().hash(password)))
    elif args.command == "worker":
        Pipeline(settings, db).work(once=args.once)
    elif args.command == "diagnose":
        translator = LlamaTranslator(settings)
        try:
            print(json.dumps(translator.validate(), ensure_ascii=False))
        finally:
            translator.close()
    elif args.command == "serve":
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(settings, db), host="127.0.0.1", port=8097)


if __name__ == "__main__":
    main()
