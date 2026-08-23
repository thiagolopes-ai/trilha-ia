"""Junta as duas metades: verifica a ancoragem e grava a trilha.

É aqui que a política vive. As duas regras abaixo são a razão de o projeto
existir, e ambas são configuráveis porque o apetite de risco muda de empresa
para empresa — mas nenhuma delas é opcional por omissão:

1. Resposta com trecho sem lastro na fonte entra na fila de revisão humana.
2. Decisão automatizada que afeta interesses do titular entra na fila de
   revisão humana mesmo quando bem ancorada — art. 20 da LGPD trata do
   direito à revisão, e não da qualidade da resposta.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ancoragem import Veredito, verificar
from .registro import NAO_REQUERIDA, PENDENTE, Registro, Trilha

# Calibrado em avaliar.py sobre 36 casos rotulados: F1 0,971 com recall 1,00
# na detecção de invenção. Ver README, seção "O número".
LIMIAR_PADRAO = 0.70


@dataclass
class Politica:
    """Quando exigir olho humano."""

    limiar_ancoragem: float = LIMIAR_PADRAO
    metodo: str = "cobertura"
    checar_citacoes: bool = True
    revisar_sem_ancora: bool = True
    revisar_decisao_automatica: bool = True

    def exige_revisao(self, veredito: Veredito, decisao_automatica: bool) -> bool:
        if self.revisar_decisao_automatica and decisao_automatica:
            return True
        if self.revisar_sem_ancora and not veredito.ancorada:
            return True
        return False


@dataclass
class Resultado:
    id_registro: str
    veredito: Veredito
    exige_revisao: bool


class Auditor:
    """Envolve uma chamada de modelo e devolve a trilha correspondente.

    Não chama modelo nenhum de propósito. Quem chama é a aplicação — o auditor
    só recebe o que entrou e o que saiu. Assim ele funciona com qualquer
    provedor, inclusive um que ainda não existe, e o repositório não precisa de
    chave de API para ser executado por quem quiser conferir os números.
    """

    def __init__(self, trilha: Trilha, politica: Politica | None = None) -> None:
        self.trilha = trilha
        self.politica = politica or Politica()

    def registrar(
        self,
        *,
        modelo: str,
        versao_modelo: str,
        prompt: str,
        resposta: str,
        fontes: list[str],
        identificadores_fontes: list[str] | None = None,
        tokens_entrada: int = 0,
        tokens_saida: int = 0,
        custo_estimado: float = 0.0,
        decisao_automatica: bool = False,
    ) -> Resultado:
        veredito = verificar(
            resposta,
            fontes,
            limiar=self.politica.limiar_ancoragem,
            metodo=self.politica.metodo,
            checar_citacoes=self.politica.checar_citacoes,
        )
        precisa = self.politica.exige_revisao(veredito, decisao_automatica)

        identificadores = identificadores_fontes or [
            f"fonte-{i}" for i in range(1, len(fontes) + 1)
        ]
        detalhe_fontes = [
            {"id": ident, "trecho": trecho}
            for ident, trecho in zip(identificadores, fontes)
        ]

        registro = Registro(
            modelo=modelo,
            versao_modelo=versao_modelo,
            prompt=prompt,
            resposta=resposta,
            fontes=detalhe_fontes,
            tokens_entrada=tokens_entrada,
            tokens_saida=tokens_saida,
            custo_estimado=custo_estimado,
            ancoragem_score=veredito.score,
            frases_sem_ancora=veredito.frases_sem_ancora + [
                f"[citação sem fonte] {c}" for c in veredito.citacoes_inventadas
            ],
            decisao_automatica=decisao_automatica,
            status_revisao=PENDENTE if precisa else NAO_REQUERIDA,
        )
        id_registro = self.trilha.gravar(registro)
        return Resultado(id_registro=id_registro, veredito=veredito, exige_revisao=precisa)
