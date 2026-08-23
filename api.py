"""API da trilha de auditoria.

Quatro operações, que correspondem às quatro perguntas que uma empresa precisa
saber responder quando alguém questiona uma decisão apoiada por IA:

    POST /registros          o que foi decidido, por qual modelo, com qual fonte
    GET  /registros/{id}     me mostre esta decisão inteira
    GET  /revisoes           o que está esperando olho humano
    POST /registros/{id}/revisao   quem revisou, quando e por quê

Mais duas de operação: /relatorio (números agregados) e /expurgo (retenção).
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from trilha import Auditor, Politica, Trilha
from trilha.auditor import LIMIAR_PADRAO

app = FastAPI(
    title="trilha-ia",
    version="0.1.0",
    description=(
        "Registra, verifica e audita decisões apoiadas por modelos de linguagem. "
        "Cada resposta vira uma linha rastreável: modelo, versão, fontes, custo, "
        "ancoragem e revisão humana."
    ),
)

_trilha: Trilha | None = None
_auditor: Auditor | None = None


def obter_auditor() -> Auditor:
    global _trilha, _auditor
    if _auditor is None:
        _trilha = Trilha(
            caminho=os.environ.get("TRILHA_BANCO", "trilha.db"),
            dias_retencao=int(os.environ.get("TRILHA_DIAS_RETENCAO", "365")),
        )
        _auditor = Auditor(
            _trilha,
            Politica(
                limiar_ancoragem=float(
                    os.environ.get("TRILHA_LIMIAR", str(LIMIAR_PADRAO))
                )
            ),
        )
    return _auditor


class EntradaRegistro(BaseModel):
    modelo: str = Field(..., examples=["claude-sonnet-4"])
    versao_modelo: str = Field(..., examples=["2025-02-19"])
    prompt: str
    resposta: str
    fontes: list[str] = Field(default_factory=list)
    identificadores_fontes: list[str] | None = None
    tokens_entrada: int = 0
    tokens_saida: int = 0
    custo_estimado: float = 0.0
    decisao_automatica: bool = Field(
        False,
        description=(
            "Marque como verdadeiro quando a saída define ou influencia decisão "
            "sobre uma pessoa — crédito, seleção, disciplina, preço. É o gatilho "
            "do art. 20 da LGPD."
        ),
    )


class SaidaRegistro(BaseModel):
    id: str
    ancoragem_score: float
    ancorada: bool
    frases_sem_ancora: list[str]
    citacoes_inventadas: list[str]
    exige_revisao: bool
    status_revisao: str


class EntradaRevisao(BaseModel):
    revisor: str = Field(..., min_length=2)
    aprovada: bool
    justificativa: str = Field(
        ...,
        min_length=10,
        description="Revisão sem justificativa é carimbo. O campo é obrigatório.",
    )


@app.post("/registros", response_model=SaidaRegistro, status_code=201)
def criar_registro(
    entrada: EntradaRegistro, auditor: Auditor = Depends(obter_auditor)
) -> SaidaRegistro:
    resultado = auditor.registrar(**entrada.model_dump())
    return SaidaRegistro(
        id=resultado.id_registro,
        ancoragem_score=resultado.veredito.score,
        ancorada=resultado.veredito.ancorada,
        frases_sem_ancora=resultado.veredito.frases_sem_ancora,
        citacoes_inventadas=resultado.veredito.citacoes_inventadas,
        exige_revisao=resultado.exige_revisao,
        status_revisao="pendente" if resultado.exige_revisao else "nao_requerida",
    )


@app.get("/registros/{id_registro}")
def ler_registro(
    id_registro: str, auditor: Auditor = Depends(obter_auditor)
) -> dict[str, Any]:
    registro = auditor.trilha.ler(id_registro)
    if registro is None:
        raise HTTPException(404, "registro não encontrado")
    return registro.__dict__


@app.get("/revisoes")
def fila_de_revisao(
    limite: int = Query(50, ge=1, le=500), auditor: Auditor = Depends(obter_auditor)
) -> dict[str, Any]:
    pendentes = auditor.trilha.pendentes_de_revisao(limite)
    return {
        "total": len(pendentes),
        "registros": [
            {
                "id": r.id,
                "momento": r.momento,
                "modelo": r.modelo,
                "ancoragem_score": r.ancoragem_score,
                "frases_sem_ancora": r.frases_sem_ancora,
                "decisao_automatica": r.decisao_automatica,
            }
            for r in pendentes
        ],
    }


@app.post("/registros/{id_registro}/revisao")
def revisar(
    id_registro: str,
    entrada: EntradaRevisao,
    auditor: Auditor = Depends(obter_auditor),
) -> dict[str, Any]:
    try:
        registro = auditor.trilha.revisar(
            id_registro,
            revisor=entrada.revisor,
            aprovada=entrada.aprovada,
            justificativa=entrada.justificativa,
        )
    except KeyError:
        raise HTTPException(404, "registro não encontrado")
    except ValueError as erro:
        raise HTTPException(409, str(erro))
    return {
        "id": registro.id,
        "status_revisao": registro.status_revisao,
        "revisor": registro.revisor,
        "momento_revisao": registro.momento_revisao,
    }


@app.get("/relatorio")
def relatorio(auditor: Auditor = Depends(obter_auditor)) -> dict[str, Any]:
    return auditor.trilha.relatorio()


@app.post("/expurgo")
def expurgo(auditor: Auditor = Depends(obter_auditor)) -> dict[str, int]:
    """Apaga registros fora do prazo de retenção (art. 16 da LGPD)."""
    return {"apagados": auditor.trilha.expurgar()}


@app.get("/saude")
def saude() -> dict[str, str]:
    return {"status": "ok"}
