from flask import Flask
from app import create_app
from extensions import db
from sqlalchemy import text

app: Flask = create_app()
with app.app_context():
    import models  # ← wichtig, damit Tabellen registriert sind
    db.create_all()
    db.session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    db.session.execute(text("CREATE INDEX IF NOT EXISTS gin_templates_summary ON chatai_templates USING GIN (summary)"))
    db.session.execute(text("CREATE INDEX IF NOT EXISTS gin_templates_tags ON chatai_templates USING GIN (tags)"))
    db.session.execute(text("CREATE INDEX IF NOT EXISTS trigram_templates_title ON chatai_templates USING GIN (title gin_trgm_ops)"))
    db.session.commit()
print("Data DB init: OK")
