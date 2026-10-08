import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import Header, HTTPException
from jose import JWTError, jwt

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    # sem valor padrão de propósito: uma chave fixa no código deixaria qualquer
    # pessoa forjar tokens
    raise RuntimeError("Defina SECRET_KEY no .env (veja o .env.example)")

# chave que o bot do WhatsApp manda no header X-API-Key
BOT_API_KEY = os.getenv("BOT_API_KEY")

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 8


def gerar_hash(senha: str) -> str:
    return hashlib.sha256(senha.encode()).hexdigest()


def verificar_senha(senha: str, hash_esperado: str) -> bool:
    # compare_digest compara em tempo constante
    return hmac.compare_digest(gerar_hash(senha), hash_esperado)


def criar_token(dados: dict) -> str:
    payload = dados.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verificar_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def exigir_acesso(
    authorization: str = Header(default=""),
    x_api_key: str = Header(default=""),
):
    """Libera a rota para o painel (JWT no Authorization) ou para o bot (X-API-Key)."""
    if BOT_API_KEY and hmac.compare_digest(x_api_key, BOT_API_KEY):
        return
    if authorization.startswith("Bearer ") and verificar_token(authorization[7:]):
        return
    raise HTTPException(status_code=401, detail="Não autorizado.")
