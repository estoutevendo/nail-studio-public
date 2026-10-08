import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Defina DATABASE_URL no .env (veja o .env.example)")

# pool_pre_ping: o Postgres hospedado derruba conexões ociosas, e sem isso a
# primeira requisição depois de um tempo parado falha
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass
