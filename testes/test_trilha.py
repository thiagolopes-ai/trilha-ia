"""Testes das teses do projeto — não da existência dos métodos.

Cada teste aqui corresponde a uma afirmação que o README faz. Se o README diz
que a resposta fica cifrada no banco, existe um teste que abre o arquivo do
banco e procura o texto em claro. Se diz que revisão exige justificativa,
existe um teste que tenta revisar sem ela.

Teste que só confirma que a função devolve algo não protege ninguém.
"""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from trilha import Auditor, Cofre, Politica, Registro, Trilha, verificar
from trilha.ancoragem import citacoes, dividir_frases
from trilha.registro import APROVADA, NAO_REQUERIDA, PENDENTE, REPROVADA

FONTE_46 = (
    "Art. 46. Os agentes de tratamento devem adotar medidas de segurança, "
    "técnicas e administrativas aptas a proteger os dados pessoais de acessos "
    "não autorizados e de situações acidentais ou ilícitas de destruição, "
    "perda, alteração, comunicação ou qualquer forma de tratamento inadequado."
)


@pytest.fixture()
def cofre() -> Cofre:
    return Cofre(Cofre.gerar_chave())


@pytest.fixture()
def trilha(tmp_path: Path, cofre: Cofre) -> Iterator[Trilha]:
    with Trilha(tmp_path / "t.db", cofre=cofre) as t:
        yield t


# --------------------------------------------------------------------- cifra

def test_conteudo_sensivel_nao_aparece_em_claro_no_banco(tmp_path, cofre):
    """Art. 46 da LGPD: proteção do dado em repouso. Esta é a prova."""
    segredo = "CPF 123.456.789-00 do reclamante Fulano de Tal"
    caminho = tmp_path / "t.db"
    with Trilha(caminho, cofre=cofre) as t:
        t.gravar(
            Registro(
                modelo="m", versao_modelo="1", prompt=segredo,
                resposta="resposta contendo " + segredo, fontes=[{"id": "f", "trecho": segredo}],
            )
        )

    bruto = caminho.read_bytes()
    assert segredo.encode("utf-8") not in bruto
    assert b"123.456.789-00" not in bruto


def test_trilha_devolve_o_conteudo_original(trilha):
    original = "texto com acento: proteção de dados"
    id_reg = trilha.gravar(
        Registro(modelo="m", versao_modelo="1", prompt=original, resposta=original)
    )
    assert trilha.ler(id_reg).prompt == original


def test_sem_chave_o_servico_nao_sobe(monkeypatch):
    monkeypatch.delenv("TRILHA_CHAVE", raising=False)
    with pytest.raises(RuntimeError, match="TRILHA_CHAVE"):
        Cofre()


def test_hash_do_prompt_fica_em_claro_para_busca(tmp_path, cofre):
    """O hash existe justamente para consultar sem descriptografar."""
    caminho = tmp_path / "t.db"
    with Trilha(caminho, cofre=cofre) as t:
        t.gravar(Registro(modelo="m", versao_modelo="1", prompt="pergunta", resposta="r"))
    with sqlite3.connect(caminho) as con:
        (hash_gravado,) = con.execute("SELECT prompt_hash FROM registros").fetchone()
    assert len(hash_gravado) == 64


# ---------------------------------------------------------------- ancoragem

def test_parafrase_fiel_e_considerada_ancorada():
    resposta = (
        "Os agentes de tratamento devem adotar medidas de segurança técnicas e "
        "administrativas aptas a proteger os dados pessoais de acessos não autorizados."
    )
    assert verificar(resposta, [FONTE_46]).ancorada


def test_afirmacao_inventada_e_reprovada():
    resposta = "O artigo exige criptografia AES-256 e auditoria trimestral por empresa certificada."
    veredito = verificar(resposta, [FONTE_46])
    assert not veredito.ancorada
    assert veredito.frases_sem_ancora


def test_citacao_de_artigo_ausente_da_fonte_e_apontada():
    """Artigo inventado é o sinal mais barato e confiável de invenção."""
    veredito = verificar("Conforme o art. 51, a empresa deve agir.", [FONTE_46])
    assert veredito.citacoes_inventadas == ["art.51"]


def test_abreviacao_nao_quebra_a_frase():
    """Regressão: 'O art. 46 exige' virava duas frases e perdia o contexto."""
    frases = dividir_frases("O art. 46 da Lei n. 13.709 exige medidas. Isso vale para todos.")
    assert len(frases) == 2
    assert frases[0].startswith("O art. 46")


def test_citacao_com_paragrafo_e_inciso_e_canonizada():
    assert "art.46§1" in citacoes("nos termos do art. 46, § 1º, desta Lei")


def test_frase_sem_conteudo_nao_gera_alarme():
    """'Portanto:' não é alucinação — é conectivo."""
    veredito = verificar("Portanto: Sim.", [FONTE_46])
    assert veredito.frases_sem_ancora == []


# ------------------------------------------------------------------ política

def test_resposta_sem_ancora_entra_na_fila_de_revisao(trilha):
    auditor = Auditor(trilha)
    resultado = auditor.registrar(
        modelo="m", versao_modelo="1", prompt="p",
        resposta="A empresa deve contratar seguro cibernético de dez milhões.",
        fontes=[FONTE_46],
    )
    assert resultado.exige_revisao
    assert trilha.ler(resultado.id_registro).status_revisao == PENDENTE


def test_decisao_automatizada_exige_revisao_mesmo_bem_ancorada(trilha):
    """Art. 20 trata do direito à revisão, não da qualidade da resposta."""
    auditor = Auditor(trilha)
    resultado = auditor.registrar(
        modelo="m", versao_modelo="1", prompt="p",
        resposta=FONTE_46, fontes=[FONTE_46], decisao_automatica=True,
    )
    assert resultado.veredito.ancorada
    assert resultado.exige_revisao


def test_resposta_ancorada_e_nao_decisoria_nao_ocupa_revisor(trilha):
    resultado = Auditor(trilha).registrar(
        modelo="m", versao_modelo="1", prompt="p", resposta=FONTE_46, fontes=[FONTE_46]
    )
    assert not resultado.exige_revisao
    assert trilha.ler(resultado.id_registro).status_revisao == NAO_REQUERIDA


def test_politica_permissiva_pode_desligar_a_fila(trilha):
    auditor = Auditor(trilha, Politica(revisar_sem_ancora=False))
    resultado = auditor.registrar(
        modelo="m", versao_modelo="1", prompt="p",
        resposta="Afirmação totalmente desconexa sobre outro assunto qualquer.",
        fontes=[FONTE_46],
    )
    assert not resultado.exige_revisao


# ------------------------------------------------------------------- revisão

def test_revisao_exige_justificativa(trilha):
    id_reg = trilha.gravar(
        Registro(modelo="m", versao_modelo="1", prompt="p", resposta="r",
                 status_revisao=PENDENTE)
    )
    with pytest.raises(ValueError, match="justificativa"):
        trilha.revisar(id_reg, revisor="Tiago", aprovada=True, justificativa="   ")


def test_revisao_registra_quem_quando_e_por_que(trilha):
    id_reg = trilha.gravar(
        Registro(modelo="m", versao_modelo="1", prompt="p", resposta="r",
                 status_revisao=PENDENTE)
    )
    revisado = trilha.revisar(
        id_reg, revisor="Tiago Lopes", aprovada=False,
        justificativa="Prazo de 72 horas é do RGPD, não da LGPD.",
    )
    assert revisado.status_revisao == REPROVADA
    assert revisado.revisor == "Tiago Lopes"
    assert revisado.momento_revisao is not None
    assert "RGPD" in revisado.justificativa_revisao


def test_revisao_nao_pode_ser_sobrescrita(trilha):
    """Trilha que aceita reescrita de veredito não é trilha."""
    id_reg = trilha.gravar(
        Registro(modelo="m", versao_modelo="1", prompt="p", resposta="r",
                 status_revisao=PENDENTE)
    )
    trilha.revisar(id_reg, revisor="A", aprovada=True, justificativa="Confere com a fonte.")
    with pytest.raises(ValueError, match="já foi revisado"):
        trilha.revisar(id_reg, revisor="B", aprovada=False, justificativa="Mudei de ideia.")


def test_status_invalido_e_rejeitado_na_criacao():
    with pytest.raises(ValueError, match="status_revisao"):
        Registro(modelo="m", versao_modelo="1", prompt="p", resposta="r",
                 status_revisao="quase_aprovada")


# ------------------------------------------------------- retenção e relatório

def test_expurgo_apaga_apenas_o_que_venceu(trilha):
    vencido = trilha.gravar(
        Registro(modelo="m", versao_modelo="1", prompt="a", resposta="r",
                 retencao_ate="2020-01-01")
    )
    vigente = trilha.gravar(
        Registro(modelo="m", versao_modelo="1", prompt="b", resposta="r",
                 retencao_ate="2999-01-01")
    )
    assert trilha.expurgar(hoje="2026-08-23") == 1
    assert trilha.ler(vencido) is None
    assert trilha.ler(vigente) is not None


def test_relatorio_soma_custo_e_separa_por_status(trilha):
    auditor = Auditor(trilha)
    auditor.registrar(modelo="m", versao_modelo="1", prompt="p", resposta=FONTE_46,
                      fontes=[FONTE_46], custo_estimado=0.01, tokens_entrada=100)
    auditor.registrar(modelo="m", versao_modelo="1", prompt="p",
                      resposta="Frase inventada sobre seguro cibernético obrigatório.",
                      fontes=[FONTE_46], custo_estimado=0.02, tokens_entrada=50)
    relatorio = trilha.relatorio()
    assert relatorio["total_registros"] == 2
    assert relatorio["custo_total"] == pytest.approx(0.03)
    assert relatorio["tokens_entrada"] == 150
    assert relatorio["por_status_revisao"][PENDENTE] == 1
    assert relatorio["proporcao_com_trecho_sem_ancora"] == 0.5


# --------------------------------------------------------- gabarito e método

def _casos() -> list[dict]:
    raiz = Path(__file__).resolve().parent.parent
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))
    from preparar_casos import carregar

    return carregar(raiz / "dados" / "casos.json")


def test_gabarito_tem_as_duas_classes():
    casos = _casos()
    assert sum(1 for c in casos if c["ancorada"]) >= 15
    assert sum(1 for c in casos if not c["ancorada"]) >= 15


def test_detector_nao_deixa_passar_invencao_no_conjunto_rotulado():
    """O número que o README publica: recall 1,00 sobre invenção.

    Recall é a métrica que importa aqui. Detector de auditoria que deixa passar
    alucinação é pior que nenhum, porque produz falsa segurança.
    """
    escapou = [
        caso["id"]
        for caso in _casos()
        if not caso["ancorada"]
        and verificar(caso["resposta"], caso["fontes"], limiar=0.70).ancorada
    ]
    assert escapou == []


def test_detector_supera_a_linha_de_base_de_acusar_tudo():
    """'Acusar tudo' tem recall 1,00 e F1 0,64. O detector precisa ganhar disso."""
    casos = _casos()
    vp = fp = fn = 0
    for caso in casos:
        acusou = not verificar(caso["resposta"], caso["fontes"], limiar=0.70).ancorada
        inventou = not caso["ancorada"]
        vp += acusou and inventou
        fp += acusou and not inventou
        fn += (not acusou) and inventou
    precisao = vp / (vp + fp)
    recall = vp / (vp + fn)
    f1 = 2 * precisao * recall / (precisao + recall)
    assert f1 > 0.90
