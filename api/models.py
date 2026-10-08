from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class Servico(Base):
    __tablename__ = "servicos"

    id          = Column(Integer, primary_key=True)
    categoria   = Column(String(50),  nullable=False)
    nome        = Column(String(100), nullable=False)
    preco       = Column(Numeric(8,2),nullable=False)
    duracao_min = Column(Integer,     nullable=False)

class Cliente(Base):
    __tablename__ = "clientes"

    id         = Column(Integer, primary_key=True)
    nome       = Column(String(100), nullable=False)
    telefone   = Column(String(20),  nullable=False, unique=True)
    criado_em  = Column(TIMESTAMP,   server_default=func.now())

class Agendamento(Base):
    __tablename__ = "agendamentos"

    id         = Column(Integer, primary_key=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    servico_id = Column(Integer, ForeignKey("servicos.id"), nullable=False)
    data_hora  = Column(TIMESTAMP, nullable=False)
    status     = Column(String(20), nullable=False, default="agendado")
    criado_em  = Column(TIMESTAMP,  server_default=func.now())

    cliente    = relationship("Cliente")
    servico    = relationship("Servico")

class Sessao(Base):
    __tablename__ = "sessoes"

    telefone   = Column(String(20), primary_key=True)
    dados      = Column(String,     nullable=False)
    atualizado = Column(TIMESTAMP,  server_default=func.now(), onupdate=func.now())
