"""Verifica, frase a frase, se a resposta está sustentada pelas fontes.

A pergunta que este módulo responde é estreita de propósito: *o que o modelo
afirmou está nos trechos que ele recebeu?* Ele não julga se a resposta é
verdadeira no mundo — julga se é rastreável até a fonte. Para auditoria, essa
é a pergunta que importa: uma resposta certa por acaso, sem lastro na fonte,
continua sendo um problema de governança.

Duas famílias de sinal são implementadas e comparadas em avaliar.py:

1. cobertura lexical — proporção dos termos de conteúdo da frase que aparecem
   no melhor trecho recuperado;
2. similaridade TF-IDF — cosseno entre a frase e cada trecho.

Além disso, citações normativas ("art. 46 da LGPD") são conferidas uma a uma
contra as fontes. Artigo citado que não existe no material recuperado é o sinal
mais barato e mais confiável de invenção que existe em texto jurídico.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Palavras sem carga informativa. Uma frase feita só delas não é avaliável —
# tratá-la como "sem âncora" geraria alarme falso em conectivo de parágrafo.
VAZIAS = {
    "a", "à", "às", "ao", "aos", "as", "com", "como", "da", "das", "de", "do",
    "dos", "e", "em", "entre", "essa", "essas", "esse", "esses", "esta",
    "estas", "este", "estes", "eu", "isso", "já", "lhe", "mas", "me", "mesmo",
    "na", "nas", "no", "nos", "não", "num", "numa", "o", "os", "ou", "para",
    "pela", "pelas", "pelo", "pelos", "per", "por", "porque", "quando", "que",
    "quem", "se", "sem", "ser", "seu", "seus", "sua", "suas", "só", "também",
    "te", "tem", "têm", "ter", "um", "uma", "uns", "umas", "você", "é", "são",
    "foi", "foram", "está", "estão", "seja", "sejam", "sobre", "ainda", "após",
    "assim", "então", "portanto", "logo", "ademais", "outrossim", "conforme",
    "caso", "cada", "todo", "toda", "todos", "todas", "pode", "podem", "deve",
    "devem", "haverá", "há", "isto", "aquilo", "qual", "quais", "onde",
}

MINIMO_TERMOS = 3  # abaixo disso a frase não é avaliável

_RE_TOKEN = re.compile(r"[a-z0-9º°]+")

# Abreviações que terminam em ponto e NÃO encerram frase. Sem esta lista,
# "O art. 46 exige..." vira duas frases e a citação perde o contexto —
# foi exatamente o que aconteceu na primeira versão deste módulo.
ABREVIACOES = {
    "art", "arts", "inc", "incs", "par", "pars", "cf", "cc", "p", "pp",
    "n", "no", "nº", "num", "ex", "obs", "fl", "fls", "jr", "sr", "sra",
    "dr", "dra", "prof", "profa", "etc", "vs", "ltda", "s", "a",
}
_RE_CORTE = re.compile(r"([.!?;:])(\s+|$)|\n+")
_RE_CITACAO = re.compile(
    r"\bart(?:igo)?s?\.?\s*(\d+)(?:\s*[º°])?"
    r"(?:\s*,?\s*(?:§|par[áa]grafo)\s*(\d+|[úu]nico))?"
    r"(?:\s*,?\s*(?:inciso\s*)?([IVXLC]+))?",
    re.IGNORECASE,
)


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def termos(texto: str) -> set[str]:
    """Termos de conteúdo: minúsculas, sem acento, sem palavra vazia."""
    brutos = _RE_TOKEN.findall(normalizar(texto))
    vazias = {normalizar(p) for p in VAZIAS}
    return {t for t in brutos if t not in vazias and len(t) > 1}


def _encerra_frase(texto: str, pos: int) -> bool:
    """Decide se o pontuador na posição pos realmente encerra a frase."""
    if texto[pos] != ".":
        return True  # ! ? ; : sempre encerram

    anterior = _RE_TOKEN.findall(normalizar(texto[:pos]))
    if anterior and anterior[-1] in ABREVIACOES:
        return False

    resto = texto[pos + 1 :].lstrip()
    if resto and (resto[0].islower() or resto[0].isdigit()):
        return False  # "art. 46", "n. 13.709", "3.500 colaboradores"
    return True


def dividir_frases(texto: str) -> list[str]:
    partes: list[str] = []
    inicio = 0
    for achado in _RE_CORTE.finditer(texto):
        pontuador = achado.group(1)
        corte = achado.start(1) if pontuador else achado.start()
        if pontuador and not _encerra_frase(texto, corte):
            continue
        fim = corte + (1 if pontuador else 0)
        pedaco = texto[inicio:fim].strip()
        if pedaco:
            partes.append(pedaco)
        inicio = achado.end()
    resto = texto[inicio:].strip()
    if resto:
        partes.append(resto)
    return partes


def citacoes(texto: str) -> set[str]:
    """Extrai citações normativas em forma canônica (ex.: 'art.46§2.º-I')."""
    achadas = set()
    for artigo, paragrafo, inciso in _RE_CITACAO.findall(texto):
        chave = f"art.{int(artigo)}"
        if paragrafo:
            p = normalizar(paragrafo)
            chave += f"§{p}"
        if inciso:
            chave += f"-{inciso.upper()}"
        achadas.add(chave)
    return achadas


@dataclass
class Veredito:
    """Resultado da checagem de uma resposta contra suas fontes."""

    score: float
    frases_avaliadas: int
    frases_sem_ancora: list[str] = field(default_factory=list)
    citacoes_inventadas: list[str] = field(default_factory=list)
    detalhe: list[dict] = field(default_factory=list)

    @property
    def ancorada(self) -> bool:
        return not self.frases_sem_ancora and not self.citacoes_inventadas


def _cobertura(frase: str, trechos: list[str]) -> float:
    alvo = termos(frase)
    if not alvo:
        return 1.0
    melhor = 0.0
    for trecho in trechos:
        presentes = alvo & termos(trecho)
        melhor = max(melhor, len(presentes) / len(alvo))
    return melhor


def _cosseno_tfidf(frases: list[str], trechos: list[str]) -> list[float]:
    if not frases or not trechos:
        return [0.0] * len(frases)
    vetorizador = TfidfVectorizer(preprocessor=normalizar, token_pattern=r"[a-z0-9º°]+")
    try:
        matriz = vetorizador.fit_transform(trechos + frases)
    except ValueError:  # vocabulário vazio
        return [0.0] * len(frases)
    base = matriz[: len(trechos)]
    alvo = matriz[len(trechos) :]
    return cosine_similarity(alvo, base).max(axis=1).tolist()


def verificar(
    resposta: str,
    fontes: list[str],
    limiar: float = 0.55,
    metodo: str = "cobertura",
    checar_citacoes: bool = True,
) -> Veredito:
    """Confere uma resposta contra os trechos que a originaram.

    score é a média das similaridades das frases avaliáveis. Frases abaixo do
    limiar entram em frases_sem_ancora — são elas, e não a média, que um
    auditor vai querer ler.
    """
    frases = dividir_frases(resposta)
    avaliaveis = [f for f in frases if len(termos(f)) >= MINIMO_TERMOS]

    if metodo == "cobertura":
        scores = [_cobertura(f, fontes) for f in avaliaveis]
    elif metodo == "tfidf":
        scores = _cosseno_tfidf(avaliaveis, fontes)
    else:
        raise ValueError(f"método desconhecido: {metodo}")

    sem_ancora, detalhe = [], []
    for frase, score in zip(avaliaveis, scores):
        if score < limiar:
            sem_ancora.append(frase)
        detalhe.append({"frase": frase, "score": round(score, 4)})

    inventadas: list[str] = []
    if checar_citacoes:
        nas_fontes = set()
        for trecho in fontes:
            nas_fontes |= citacoes(trecho)
        inventadas = sorted(citacoes(resposta) - nas_fontes)

    media = sum(scores) / len(scores) if scores else 1.0
    return Veredito(
        score=round(media, 4),
        frases_avaliadas=len(avaliaveis),
        frases_sem_ancora=sem_ancora,
        citacoes_inventadas=inventadas,
        detalhe=detalhe,
    )
