from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ServicoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    categoria: str
    nome: str
    preco: float
    duracao_min: int


class ClienteCreate(BaseModel):
    nome: str
    telefone: str


class ClienteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    telefone: str


class AgendamentoCreate(BaseModel):
    telefone: str
    servico_id: int
    data_hora: datetime


class AgendamentoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cliente: ClienteOut
    servico: ServicoOut
    data_hora: datetime
    status: str


class LoginIn(BaseModel):
    senha: str


class EdicaoIn(BaseModel):
    data_hora: datetime
