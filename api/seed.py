"""Cadastra serviços de exemplo se a tabela estiver vazia.

Uso (dentro de api/):  python seed.py
Os nomes e preços abaixo são só para demonstração; troque pelos do seu ateliê.
"""
from database import Base, SessionLocal, engine
from models import Servico

EXEMPLOS = [
    # categoria, nome, preço, duração em minutos
    ("Mãos", "Manicure simples", 35.00, 45),
    ("Mãos", "Esmaltação em gel", 70.00, 90),
    ("Mãos", "Alongamento em fibra", 150.00, 150),
    ("Pés", "Pedicure simples", 40.00, 60),
    ("Pés", "Esmaltação em gel nos pés", 80.00, 90),
]

if __name__ == "__main__":
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        if db.query(Servico).count():
            print("Já existem serviços cadastrados, nada a fazer.")
        else:
            for categoria, nome, preco, duracao in EXEMPLOS:
                db.add(Servico(categoria=categoria, nome=nome, preco=preco, duracao_min=duracao))
            db.commit()
            print(f"{len(EXEMPLOS)} serviços de exemplo cadastrados.")
    finally:
        db.close()
