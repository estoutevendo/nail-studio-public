from datetime import datetime
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")


def agora_br() -> datetime:
    """Hora atual de Brasília, sem informação de fuso.

    As colunas de data/hora do banco são TIMESTAMP sem timezone e guardam o
    horário local do ateliê. Comparar essas colunas com um datetime "aware"
    (ou com datetime.now() do servidor, que no Railway é UTC) dá diferença de
    algumas horas, então tudo que vai pro banco passa por aqui.
    """
    return datetime.now(FUSO).replace(tzinfo=None)
