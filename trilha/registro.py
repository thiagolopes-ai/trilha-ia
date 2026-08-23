"""Registro de auditoria de decisões apoiadas por IA.

Cada resposta gerada por um modelo vira uma linha nesta tabela. É essa linha
que permite responder, meses depois, as três perguntas que uma empresa não
consegue responder hoje: qual modelo respondeu, com base em qual fonte, e
quem revisou.

Conteúdo sensível (prompt, resposta e trechos das fontes) é cifrado em
repouso — art. 46 da LGPD exige medidas técnicas de proteção. O hash do
prompt fica em claro para permitir busca e deduplicação sem descriptografar
nada.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

# Status de revisão humana. O art. 20 da LGPD garante ao titular o direito de
# pedir revisão de decisão automatizada — sem esses estados, a empresa não tem
# como comprovar que atendeu ao pedido.
NAO_REQUERIDA = "nao_requerida"
PENDENTE = "pendente"
APROVADA = "aprovada"
REPROVADA = "reprovada"

STATUS_VALIDOS = {NAO_REQUERIDA, PENDENTE, APROVADA, REPROVADA}


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_texto(texto: str) -> str:
    """SHA-256 do texto normalizado. Fica em claro no banco de propósito."""
    return hashlib.sha256(texto.strip().encode("utf-8")).hexdigest()


class Cofre:
    """Cifra e decifra o conteúdo sensível da trilha.

    A chave nunca fica no código nem no banco: vem da variável de ambiente
    TRILHA_CHAVE. Sem ela o serviço não sobe — é decisão deliberada, porque
    subir sem cifra e "arrumar depois" é como vaza dado na prática.
    """

    def __init__(self, chave: str | bytes | None = None) -> None:
        chave = chave or os.environ.get("TRILHA_CHAVE")
        if not chave:
            raise RuntimeError(
                "TRILHA_CHAVE não definida. Gere uma com: "
                "python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            )
        if isinstance(chave, str):
            chave = chave.encode()
        self._fernet = Fernet(chave)

    def cifrar(self, texto: str) -> str:
        return self._fernet.encrypt(texto.encode("utf-8")).decode("ascii")

    def decifrar(self, cifrado: str) -> str:
        return self._fernet.decrypt(cifrado.encode("ascii")).decode("utf-8")

    @staticmethod
    def gerar_chave() -> str:
        return Fernet.generate_key().decode()


@dataclass
class Registro:
    """Uma decisão apoiada por IA, do jeito que ela precisa ser auditada."""

    modelo: str
    versao_modelo: str
    prompt: str
    resposta: str
    fontes: list[dict[str, Any]] = field(default_factory=list)
    tokens_entrada: int = 0
    tokens_saida: int = 0
    custo_estimado: float = 0.0
    ancoragem_score: float | None = None
    frases_sem_ancora: list[str] = field(default_factory=list)
    decisao_automatica: bool = False
    status_revisao: str = NAO_REQUERIDA
    revisor: str | None = None
    momento_revisao: str | None = None
    justificativa_revisao: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    momento: str = field(default_factory=_agora)
    retencao_ate: str | None = None

    def __post_init__(self) -> None:
        if self.status_revisao not in STATUS_VALIDOS:
            raise ValueError(f"status_revisao inválido: {self.status_revisao}")


ESQUEMA = """
CREATE TABLE IF NOT EXISTS registros (
    id                   TEXT PRIMARY KEY,
    momento              TEXT NOT NULL,
    modelo               TEXT NOT NULL,
    versao_modelo        TEXT NOT NULL,
    prompt_hash          TEXT NOT NULL,
    prompt_cifrado       TEXT NOT NULL,
    resposta_cifrada     TEXT NOT NULL,
    fontes_cifradas      TEXT NOT NULL,
    tokens_entrada       INTEGER NOT NULL,
    tokens_saida         INTEGER NOT NULL,
    custo_estimado       REAL NOT NULL,
    ancoragem_score      REAL,
    frases_sem_ancora    TEXT NOT NULL,
    decisao_automatica   INTEGER NOT NULL,
    status_revisao       TEXT NOT NULL,
    revisor              TEXT,
    momento_revisao      TEXT,
    justificativa_revisao TEXT,
    retencao_ate         TEXT
);
CREATE INDEX IF NOT EXISTS idx_momento ON registros(momento);
CREATE INDEX IF NOT EXISTS idx_prompt_hash ON registros(prompt_hash);
CREATE INDEX IF NOT EXISTS idx_status ON registros(status_revisao);
CREATE INDEX IF NOT EXISTS idx_retencao ON registros(retencao_ate);
"""


class Trilha:
    """Armazena e consulta os registros de auditoria."""

    def __init__(
        self,
        caminho: str | Path = "trilha.db",
        cofre: Cofre | None = None,
        dias_retencao: int = 365,
    ) -> None:
        self.caminho = str(caminho)
        self.cofre = cofre or Cofre()
        self.dias_retencao = dias_retencao
        self._conexao = sqlite3.connect(self.caminho, check_same_thread=False)
        self._conexao.row_factory = sqlite3.Row
        self._conexao.executescript(ESQUEMA)
        self._conexao.commit()

    def gravar(self, registro: Registro) -> str:
        if registro.retencao_ate is None:
            limite = datetime.now(timezone.utc) + timedelta(days=self.dias_retencao)
            registro.retencao_ate = limite.date().isoformat()

        self._conexao.execute(
            """
            INSERT INTO registros VALUES (
                :id, :momento, :modelo, :versao_modelo, :prompt_hash,
                :prompt_cifrado, :resposta_cifrada, :fontes_cifradas,
                :tokens_entrada, :tokens_saida, :custo_estimado,
                :ancoragem_score, :frases_sem_ancora, :decisao_automatica,
                :status_revisao, :revisor, :momento_revisao,
                :justificativa_revisao, :retencao_ate
            )
            """,
            {
                "id": registro.id,
                "momento": registro.momento,
                "modelo": registro.modelo,
                "versao_modelo": registro.versao_modelo,
                "prompt_hash": hash_texto(registro.prompt),
                "prompt_cifrado": self.cofre.cifrar(registro.prompt),
                "resposta_cifrada": self.cofre.cifrar(registro.resposta),
                "fontes_cifradas": self.cofre.cifrar(
                    json.dumps(registro.fontes, ensure_ascii=False)
                ),
                "tokens_entrada": registro.tokens_entrada,
                "tokens_saida": registro.tokens_saida,
                "custo_estimado": registro.custo_estimado,
                "ancoragem_score": registro.ancoragem_score,
                "frases_sem_ancora": json.dumps(
                    registro.frases_sem_ancora, ensure_ascii=False
                ),
                "decisao_automatica": int(registro.decisao_automatica),
                "status_revisao": registro.status_revisao,
                "revisor": registro.revisor,
                "momento_revisao": registro.momento_revisao,
                "justificativa_revisao": registro.justificativa_revisao,
                "retencao_ate": registro.retencao_ate,
            },
        )
        self._conexao.commit()
        return registro.id

    def ler(self, id_registro: str) -> Registro | None:
        linha = self._conexao.execute(
            "SELECT * FROM registros WHERE id = ?", (id_registro,)
        ).fetchone()
        if linha is None:
            return None
        return self._para_registro(linha)

    def _para_registro(self, linha: sqlite3.Row) -> Registro:
        return Registro(
            id=linha["id"],
            momento=linha["momento"],
            modelo=linha["modelo"],
            versao_modelo=linha["versao_modelo"],
            prompt=self.cofre.decifrar(linha["prompt_cifrado"]),
            resposta=self.cofre.decifrar(linha["resposta_cifrada"]),
            fontes=json.loads(self.cofre.decifrar(linha["fontes_cifradas"])),
            tokens_entrada=linha["tokens_entrada"],
            tokens_saida=linha["tokens_saida"],
            custo_estimado=linha["custo_estimado"],
            ancoragem_score=linha["ancoragem_score"],
            frases_sem_ancora=json.loads(linha["frases_sem_ancora"]),
            decisao_automatica=bool(linha["decisao_automatica"]),
            status_revisao=linha["status_revisao"],
            revisor=linha["revisor"],
            momento_revisao=linha["momento_revisao"],
            justificativa_revisao=linha["justificativa_revisao"],
            retencao_ate=linha["retencao_ate"],
        )

    def revisar(
        self,
        id_registro: str,
        revisor: str,
        aprovada: bool,
        justificativa: str,
    ) -> Registro:
        """Registra a revisão humana de uma decisão automatizada.

        Art. 20 da LGPD: o titular tem direito a solicitar revisão de decisão
        tomada unicamente com base em tratamento automatizado. Sem justificativa
        obrigatória, a revisão vira carimbo — por isso o campo não é opcional.
        """
        if not justificativa.strip():
            raise ValueError("A revisão exige justificativa. Carimbo não é revisão.")

        atual = self.ler(id_registro)
        if atual is None:
            raise KeyError(f"registro não encontrado: {id_registro}")
        if atual.status_revisao in (APROVADA, REPROVADA):
            raise ValueError(
                f"registro {id_registro} já foi revisado por {atual.revisor}. "
                "A trilha é append-only para o resultado da revisão."
            )

        novo_status = APROVADA if aprovada else REPROVADA
        self._conexao.execute(
            """
            UPDATE registros
               SET status_revisao = ?, revisor = ?, momento_revisao = ?,
                   justificativa_revisao = ?
             WHERE id = ?
            """,
            (novo_status, revisor, _agora(), justificativa, id_registro),
        )
        self._conexao.commit()
        return self.ler(id_registro)  # type: ignore[return-value]

    def pendentes_de_revisao(self, limite: int = 100) -> list[Registro]:
        linhas = self._conexao.execute(
            "SELECT * FROM registros WHERE status_revisao = ? "
            "ORDER BY momento ASC LIMIT ?",
            (PENDENTE, limite),
        ).fetchall()
        return [self._para_registro(l) for l in linhas]

    def relatorio(self) -> dict[str, Any]:
        """Números que um auditor pede na primeira reunião."""
        cur = self._conexao.execute(
            """
            SELECT COUNT(*)                                AS total,
                   COALESCE(SUM(tokens_entrada), 0)        AS tokens_entrada,
                   COALESCE(SUM(tokens_saida), 0)          AS tokens_saida,
                   COALESCE(SUM(custo_estimado), 0.0)      AS custo_total,
                   AVG(ancoragem_score)                    AS ancoragem_media,
                   SUM(decisao_automatica)                 AS automatizadas
              FROM registros
            """
        ).fetchone()

        por_status = {
            linha["status_revisao"]: linha["quantos"]
            for linha in self._conexao.execute(
                "SELECT status_revisao, COUNT(*) AS quantos "
                "FROM registros GROUP BY status_revisao"
            )
        }
        por_modelo = {
            linha["modelo"]: linha["quantos"]
            for linha in self._conexao.execute(
                "SELECT modelo, COUNT(*) AS quantos FROM registros GROUP BY modelo"
            )
        }
        sem_ancora = self._conexao.execute(
            "SELECT COUNT(*) AS quantos FROM registros "
            "WHERE frases_sem_ancora != '[]'"
        ).fetchone()["quantos"]

        total = cur["total"] or 0
        return {
            "total_registros": total,
            "tokens_entrada": cur["tokens_entrada"],
            "tokens_saida": cur["tokens_saida"],
            "custo_total": round(cur["custo_total"], 4),
            "ancoragem_media": (
                round(cur["ancoragem_media"], 4)
                if cur["ancoragem_media"] is not None
                else None
            ),
            "decisoes_automatizadas": cur["automatizadas"] or 0,
            "respostas_com_trecho_sem_ancora": sem_ancora,
            "proporcao_com_trecho_sem_ancora": (
                round(sem_ancora / total, 4) if total else None
            ),
            "por_status_revisao": por_status,
            "por_modelo": por_modelo,
        }

    def expurgar(self, hoje: str | None = None) -> int:
        """Apaga registros vencidos.

        Art. 16 da LGPD: o dado não pode ser mantido além do necessário. Guardar
        trilha para sempre não é diligência, é passivo.
        """
        hoje = hoje or datetime.now(timezone.utc).date().isoformat()
        cur = self._conexao.execute(
            "DELETE FROM registros WHERE retencao_ate IS NOT NULL AND retencao_ate < ?",
            (hoje,),
        )
        self._conexao.commit()
        return cur.rowcount

    def fechar(self) -> None:
        self._conexao.close()

    def __enter__(self) -> "Trilha":
        return self

    def __exit__(self, *_: object) -> None:
        self.fechar()
