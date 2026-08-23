"""Testes da API — o contrato que a aplicação cliente enxerga."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import api
from trilha import Auditor, Cofre, Trilha

FONTE = (
    "Art. 46. Os agentes de tratamento devem adotar medidas de segurança, "
    "técnicas e administrativas aptas a proteger os dados pessoais de acessos "
    "não autorizados."
)
FIEL = (
    "Os agentes de tratamento devem adotar medidas de segurança técnicas e "
    "administrativas aptas a proteger os dados pessoais de acessos não autorizados."
)
INVENTADA = "O incidente deve ser comunicado em até 72 horas, conforme o art. 51 da LGPD."


@pytest.fixture()
def cliente(tmp_path, monkeypatch) -> Iterator[TestClient]:
    trilha = Trilha(tmp_path / "api.db", cofre=Cofre(Cofre.gerar_chave()))
    monkeypatch.setattr(api, "_auditor", Auditor(trilha))
    monkeypatch.setattr(api, "_trilha", trilha)
    with TestClient(api.app) as c:
        yield c
    trilha.fechar()


def _criar(cliente: TestClient, resposta: str, **extra) -> dict:
    corpo = {
        "modelo": "claude-sonnet-4",
        "versao_modelo": "2025-02-19",
        "prompt": "O que o art. 46 exige?",
        "resposta": resposta,
        "fontes": [FONTE],
        **extra,
    }
    resposta_http = cliente.post("/registros", json=corpo)
    assert resposta_http.status_code == 201, resposta_http.text
    return resposta_http.json()


def test_resposta_fiel_nao_gera_pendencia(cliente):
    corpo = _criar(cliente, FIEL)
    assert corpo["ancorada"] is True
    assert corpo["exige_revisao"] is False
    assert cliente.get("/revisoes").json()["total"] == 0


def test_resposta_inventada_cai_na_fila_com_o_trecho_apontado(cliente):
    corpo = _criar(cliente, INVENTADA)
    assert corpo["ancorada"] is False
    assert corpo["citacoes_inventadas"] == ["art.51"]
    fila = cliente.get("/revisoes").json()
    assert fila["total"] == 1
    assert fila["registros"][0]["id"] == corpo["id"]


def test_registro_inexistente_retorna_404(cliente):
    assert cliente.get("/registros/nao-existe").status_code == 404


def test_revisao_sem_justificativa_e_recusada(cliente):
    corpo = _criar(cliente, INVENTADA)
    resposta = cliente.post(
        f"/registros/{corpo['id']}/revisao",
        json={"revisor": "Tiago", "aprovada": False, "justificativa": "não"},
    )
    assert resposta.status_code == 422


def test_revisao_valida_encerra_a_pendencia(cliente):
    corpo = _criar(cliente, INVENTADA)
    resposta = cliente.post(
        f"/registros/{corpo['id']}/revisao",
        json={
            "revisor": "Tiago Lopes",
            "aprovada": False,
            "justificativa": "Prazo de 72 horas é do RGPD; a LGPD fala em prazo razoável.",
        },
    )
    assert resposta.status_code == 200
    assert resposta.json()["status_revisao"] == "reprovada"
    assert cliente.get("/revisoes").json()["total"] == 0


def test_segunda_revisao_do_mesmo_registro_e_bloqueada(cliente):
    corpo = _criar(cliente, INVENTADA)
    dados = {
        "revisor": "Tiago Lopes",
        "aprovada": False,
        "justificativa": "Prazo incorreto para a legislação brasileira.",
    }
    cliente.post(f"/registros/{corpo['id']}/revisao", json=dados)
    segunda = cliente.post(
        f"/registros/{corpo['id']}/revisao",
        json={**dados, "revisor": "Outro", "aprovada": True},
    )
    assert segunda.status_code == 409


def test_decisao_automatizada_exige_revisao_mesmo_ancorada(cliente):
    corpo = _criar(cliente, FIEL, decisao_automatica=True)
    assert corpo["ancorada"] is True
    assert corpo["exige_revisao"] is True


def test_relatorio_agrega_custo_e_tokens(cliente):
    _criar(cliente, FIEL, custo_estimado=0.01, tokens_entrada=100, tokens_saida=20)
    _criar(cliente, INVENTADA, custo_estimado=0.02, tokens_entrada=50, tokens_saida=10)
    relatorio = cliente.get("/relatorio").json()
    assert relatorio["total_registros"] == 2
    assert relatorio["custo_total"] == pytest.approx(0.03)
    assert relatorio["tokens_saida"] == 30
    assert relatorio["proporcao_com_trecho_sem_ancora"] == 0.5


def test_saude_responde(cliente):
    assert cliente.get("/saude").json() == {"status": "ok"}
