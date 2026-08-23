"""Monta o conjunto de avaliação do detector de ancoragem.

As fontes são artigos reais da LGPD, baixados do Planalto. As respostas foram
escritas à mão, metade fiel à fonte e metade contendo invenção — do tipo que
um modelo de linguagem realmente comete: prazo do RGPD europeu aplicado à
LGPD, teto de multa arredondado para cima, artigo trocado, obrigação que
soa razoável e não existe.

Duas decisões importam para a honestidade da medição:

1. **As respostas fiéis são paráfrases, não cópias.** Se fossem cópias
   literais do artigo, qualquer detector acertaria 100% e o número não
   significaria nada.
2. **As invenções são plausíveis.** Alucinação fácil de pegar não mede
   detector nenhum. O caso do "prazo de 72 horas" é o melhor exemplo: é a
   regra do RGPD, não da LGPD, e é o erro mais comum em resposta gerada.

Uso:
    python preparar_casos.py                 # baixa e grava dados/casos.json
    python preparar_casos.py --sem-rede      # usa o JSON já gravado
"""

from __future__ import annotations

import argparse
import html as libhtml
import json
import re
import sys
import urllib.request
from pathlib import Path

URL_LGPD = "https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm"
NAVEGADOR = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
DESTINO = Path("dados/casos.json")

# Artigos usados como fonte. Trechos longos são cortados para simular o
# tamanho de um chunk recuperado por um RAG real.
#
# Cada limite foi ajustado para que o texto contenha tudo o que as respostas
# rotuladas como fiéis afirmam. Na primeira rodada o art. 6 estava cortado em
# 1.400 caracteres, o que deixava de fora os incisos IX e X — e o detector
# acusou corretamente uma resposta que eu havia rotulado como ancorada. O erro
# era do gabarito, não do detector. conferir_gabarito.py existe por causa
# disso: um gabarito não conferido mede o autor, não o método.
ARTIGOS = {6: 2100, 7: 2200, 18: 2100, 20: 950, 37: 200, 38: 650, 46: 850, 48: 900, 52: 2400}

# (artigo_fonte, resposta, ancorada?, o_que_esta_errado)
CASOS: list[tuple[int, str, bool, str]] = [
    # ---------------------------------------------------------------- art. 6
    (6, "O tratamento de dados pessoais deve seguir a boa-fé e observar princípios como "
        "finalidade, adequação e necessidade, além de garantir livre acesso do titular "
        "e transparência sobre o tratamento.", True, ""),
    (6, "Entre os princípios previstos está o da não discriminação, que veda o tratamento "
        "para fins discriminatórios ilícitos ou abusivos, e o da responsabilização e "
        "prestação de contas.", True, ""),
    (6, "A lei exige que todo tratamento de dados seja precedido de parecer jurídico "
        "assinado por advogado inscrito na OAB.", False, "obrigação inexistente"),
    (6, "O princípio da necessidade obriga a empresa a apagar todos os dados a cada 90 dias, "
        "independentemente da finalidade.", False, "prazo inventado"),

    # ---------------------------------------------------------------- art. 7
    (7, "O tratamento pode ocorrer mediante consentimento do titular, mas também para o "
        "cumprimento de obrigação legal pelo controlador e para a execução de contrato do "
        "qual o titular seja parte.", True, ""),
    (7, "O legítimo interesse do controlador é uma das hipóteses que autorizam o tratamento, "
        "assim como a proteção da vida ou da incolumidade física do titular ou de terceiro.", True, ""),
    (7, "Fora da hipótese de consentimento expresso e por escrito, nenhum tratamento de dados "
        "pessoais é permitido no Brasil.", False, "contradiz a fonte"),
    (7, "O art. 9º autoriza o tratamento sempre que a empresa comprovar finalidade comercial "
        "legítima perante a autoridade nacional.", False, "artigo trocado e regra inventada"),

    # --------------------------------------------------------------- art. 18
    (18, "O titular pode obter do controlador a confirmação da existência de tratamento e o "
         "acesso aos seus dados, além da correção de dados incompletos, inexatos ou "
         "desatualizados.", True, ""),
    (18, "Também é direito do titular pedir a portabilidade dos dados a outro fornecedor de "
         "serviço e a eliminação dos dados tratados com base no consentimento.", True, ""),
    (18, "O controlador tem prazo máximo de 15 dias corridos para responder a qualquer "
         "requisição do titular, sob pena de multa automática.", False, "prazo e sanção inventados"),
    (18, "O direito de acesso só pode ser exercido por titulares que tenham contrato vigente "
         "com a empresa há pelo menos seis meses.", False, "restrição inexistente"),

    # --------------------------------------------------------------- art. 20
    (20, "O titular tem direito de solicitar a revisão de decisões tomadas unicamente com base "
         "em tratamento automatizado que afetem seus interesses, incluindo decisões sobre seu "
         "perfil pessoal, profissional, de consumo e de crédito.", True, ""),
    (20, "O controlador deve fornecer, sempre que solicitado, informações claras e adequadas "
         "sobre os critérios e procedimentos usados na decisão automatizada, observados os "
         "segredos comercial e industrial.", True, ""),
    (20, "A revisão de decisão automatizada precisa obrigatoriamente ser feita por uma pessoa "
         "natural, conforme exige o texto vigente do artigo.", False,
         "o dispositivo que previa revisão humana foi vetado"),
    (20, "O art. 22 assegura ao titular o direito de exigir a exclusão do algoritmo utilizado "
         "pela empresa.", False, "artigo trocado e direito inventado"),

    # --------------------------------------------------------------- art. 37
    (37, "Controlador e operador devem manter registro das operações de tratamento que "
         "realizarem, especialmente quando o tratamento tem por base o legítimo interesse.", True, ""),
    (37, "A obrigação de manter registro das operações alcança tanto o controlador quanto o "
         "operador.", True, ""),
    (37, "O registro das operações deve ser enviado mensalmente à autoridade nacional em "
         "formato XML.", False, "obrigação e formato inventados"),

    # --------------------------------------------------------------- art. 38
    (38, "A autoridade nacional pode determinar ao controlador que elabore relatório de impacto "
         "à proteção de dados pessoais, inclusive quanto a dados sensíveis, respeitados os "
         "segredos comercial e industrial.", True, ""),
    (38, "O relatório de impacto deve conter, no mínimo, a descrição dos tipos de dados "
         "coletados, a metodologia utilizada para a coleta e as medidas e mecanismos de "
         "mitigação de risco adotados.", True, ""),
    (38, "O relatório de impacto é obrigatório para toda empresa com mais de cem funcionários, "
         "independentemente de determinação da autoridade.", False, "critério inventado"),

    # --------------------------------------------------------------- art. 46
    (46, "Os agentes de tratamento devem adotar medidas de segurança, técnicas e "
         "administrativas, capazes de proteger os dados pessoais de acessos não autorizados e "
         "de situações acidentais ou ilícitas de destruição, perda ou alteração.", True, ""),
    (46, "A autoridade nacional pode dispor sobre padrões técnicos mínimos, considerando a "
         "natureza das informações, as características do tratamento e o estado atual da "
         "tecnologia, especialmente no caso de dados sensíveis.", True, ""),
    (46, "O artigo exige criptografia AES-256 em repouso e em trânsito para todo dado pessoal "
         "armazenado por empresa brasileira.", False, "especificação técnica inventada"),
    (46, "As medidas de segurança só passam a ser exigíveis depois que a autoridade nacional "
         "publicar os padrões técnicos mínimos.", False, "condiciona obrigação que já é vigente"),

    # --------------------------------------------------------------- art. 48
    (48, "O controlador deve comunicar à autoridade nacional e ao titular a ocorrência de "
         "incidente de segurança que possa acarretar risco ou dano relevante aos titulares.", True, ""),
    (48, "A comunicação do incidente deve mencionar, entre outros pontos, a natureza dos dados "
         "afetados, as informações sobre os titulares envolvidos e as medidas técnicas de "
         "segurança utilizadas para a proteção dos dados.", True, ""),
    (48, "O incidente de segurança deve ser comunicado à autoridade nacional em até 72 horas "
         "contadas do conhecimento do fato.", False,
         "prazo do RGPD europeu; a LGPD fala em prazo razoável"),
    (48, "A comunicação de incidente é dispensada quando a empresa contrata seguro cibernético.", False,
         "dispensa inventada"),

    # --------------------------------------------------------------- art. 52
    (52, "As sanções previstas incluem advertência com indicação de prazo para adoção de "
         "medidas corretivas e multa simples de até dois por cento do faturamento no Brasil no "
         "último exercício, limitada a cinquenta milhões de reais por infração.", True, ""),
    (52, "Além da multa, a lei prevê a publicização da infração, o bloqueio dos dados pessoais "
         "a que se refere a infração e a eliminação desses dados.", True, ""),
    (52, "A lei prevê suspensão parcial do funcionamento do banco de dados por até seis meses, "
         "prorrogável por igual período.", True, ""),
    (52, "A multa por infração à LGPD pode chegar a cem milhões de reais por ocorrência.", False,
         "teto arredondado para cima; o real é cinquenta milhões"),
    (52, "Descumprimento reiterado da lei acarreta prisão dos administradores da empresa por "
         "até dois anos.", False, "sanção penal inexistente na lei"),
    (52, "As sanções são aplicadas pelo Ministério Público Federal após denúncia formal.", False,
         "competência trocada"),
]


def baixar_lei(url: str = URL_LGPD) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": NAVEGADOR})
    bruto = urllib.request.urlopen(req, timeout=90).read()
    for codificacao in ("utf-8", "latin-1"):
        try:
            texto = bruto.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise RuntimeError("não foi possível decodificar a página")

    texto = libhtml.unescape(re.sub(r"<[^>]+>", " ", texto))
    texto = re.sub(r"\s+", " ", texto)
    inicio = texto.find("Art. 1º")
    return texto[inicio:] if inicio > 0 else texto


def separar_artigos(texto: str) -> dict[int, str]:
    artigos: dict[int, str] = {}
    for pedaco in re.split(r"(?=\bArt\.\s*\d+)", texto):
        achado = re.match(r"Art\.\s*(\d+)", pedaco)
        if not achado:
            continue
        numero = int(achado.group(1))
        pedaco = pedaco.strip()
        if len(pedaco) > len(artigos.get(numero, "")):
            artigos[numero] = pedaco
    return artigos


def montar(artigos: dict[int, str]) -> dict:
    """Monta o arquivo no formato normalizado.

    As fontes ficam num dicionário à parte e cada caso aponta para o artigo.
    A primeira versão repetia o texto do artigo dentro de cada caso — três ou
    quatro cópias do mesmo trecho — e o arquivo ficou com 66 KB. Normalizado,
    caiu para menos de um terço, e passou a existir um único lugar onde o
    texto da fonte pode ser corrigido.
    """
    faltando = sorted(set(ARTIGOS) - set(artigos))
    if faltando:
        raise RuntimeError(f"artigos não encontrados na fonte: {faltando}")

    fontes = {str(n): artigos[n][:limite].strip() for n, limite in ARTIGOS.items()}
    casos = [
        {
            "id": f"caso-{indice:03d}",
            "artigo_fonte": artigo,
            "resposta": " ".join(resposta.split()),
            "ancorada": ancorada,
            "problema": problema,
        }
        for indice, (artigo, resposta, ancorada, problema) in enumerate(CASOS, start=1)
    ]
    return {"lei": "Lei 13.709/2018 (LGPD)", "origem": URL_LGPD, "fontes": fontes, "casos": casos}


def carregar(caminho: str | Path = DESTINO) -> list[dict]:
    """Lê o arquivo e devolve cada caso já com o texto da sua fonte.

    Função única de leitura para avaliação, conferência e testes: se o formato
    do arquivo mudar, muda em um lugar só.
    """
    dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    fontes = dados["fontes"]
    return [
        {**caso, "fontes": [fontes[str(caso["artigo_fonte"])]]}
        for caso in dados["casos"]
    ]


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument(
        "--sem-rede",
        action="store_true",
        help="não baixa a lei; apenas confere o arquivo já gravado",
    )
    argumentos = analisador.parse_args()

    if argumentos.sem_rede:
        if not DESTINO.exists():
            print(f"{DESTINO} não existe — rode sem --sem-rede uma vez.", file=sys.stderr)
            return 1
    else:
        dados = montar(separar_artigos(baixar_lei()))
        DESTINO.parent.mkdir(parents=True, exist_ok=True)
        DESTINO.write_text(
            json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    casos = carregar()
    ancoradas = sum(1 for c in casos if c["ancorada"])
    print(f"{len(casos)} casos em {DESTINO} ({DESTINO.stat().st_size // 1024} KB)")
    print(f"  ancoradas:     {ancoradas}")
    print(f"  com invenção:  {len(casos) - ancoradas}")
    print(f"  artigos usados: {sorted({c['artigo_fonte'] for c in casos})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""Monta o conjunto de avaliação do detector de ancoragem.

As fontes são artigos reais da LGPD, baixados do Planalto. As respostas foram
escritas à mão, metade fiel à fonte e metade contendo invenção — do tipo que
um modelo de linguagem realmente comete: prazo do RGPD europeu aplicado à
LGPD, teto de multa arredondado para cima, artigo trocado, obrigação que
soa razoável e não existe.

Duas decisões importam para a honestidade da medição:

1. **As respostas fiéis são paráfrases, não cópias.** Se fossem cópias
   literais do artigo, qualquer detector acertaria 100% e o número não
   significaria nada.
2. **As invenções são plausíveis.** Alucinação fácil de pegar não mede
   detector nenhum. O caso do "prazo de 72 horas" é o melhor exemplo: é a
   regra do RGPD, não da LGPD, e é o erro mais comum em resposta gerada.

Uso:
    python preparar_casos.py                 # baixa e grava dados/casos.json
    python preparar_casos.py --sem-rede      # usa o JSON já gravado
"""

from __future__ import annotations

import argparse
import html as libhtml
import json
import re
import sys
import urllib.request
from pathlib import Path

URL_LGPD = "https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm"
NAVEGADOR = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
DESTINO = Path("dados/casos.json")

# Artigos usados como fonte. Trechos longos são cortados para simular o
# tamanho de um chunk recuperado por um RAG real.
#
# Cada limite foi ajustado para que o texto contenha tudo o que as respostas
# rotuladas como fiéis afirmam. Na primeira rodada o art. 6 estava cortado em
# 1.400 caracteres, o que deixava de fora os incisos IX e X — e o detector
# acusou corretamente uma resposta que eu havia rotulado como ancorada. O erro
# era do gabarito, não do detector. conferir_gabarito.py existe por causa
# disso: um gabarito não conferido mede o autor, não o método.
ARTIGOS = {6: 2100, 7: 2200, 18: 2100, 20: 950, 37: 200, 38: 650, 46: 850, 48: 900, 52: 2400}

# (artigo_fonte, resposta, ancorada?, o_que_esta_errado)
CASOS: list[tuple[int, str, bool, str]] = [
    # ---------------------------------------------------------------- art. 6
    (6, "O tratamento de dados pessoais deve seguir a boa-fé e observar princípios como "
        "finalidade, adequação e necessidade, além de garantir livre acesso do titular "
        "e transparência sobre o tratamento.", True, ""),
    (6, "Entre os princípios previstos está o da não discriminação, que veda o tratamento "
        "para fins discriminatórios ilícitos ou abusivos, e o da responsabilização e "
        "prestação de contas.", True, ""),
    (6, "A lei exige que todo tratamento de dados seja precedido de parecer jurídico "
        "assinado por advogado inscrito na OAB.", False, "obrigação inexistente"),
    (6, "O princípio da necessidade obriga a empresa a apagar todos os dados a cada 90 dias, "
        "independentemente da finalidade.", False, "prazo inventado"),

    # ---------------------------------------------------------------- art. 7
    (7, "O tratamento pode ocorrer mediante consentimento do titular, mas também para o "
        "cumprimento de obrigação legal pelo controlador e para a execução de contrato do "
        "qual o titular seja parte.", True, ""),
    (7, "O legítimo interesse do controlador é uma das hipóteses que autorizam o tratamento, "
        "assim como a proteção da vida ou da incolumidade física do titular ou de terceiro.", True, ""),
    (7, "Fora da hipótese de consentimento expresso e por escrito, nenhum tratamento de dados "
        "pessoais é permitido no Brasil.", False, "contradiz a fonte"),
    (7, "O art. 9º autoriza o tratamento sempre que a empresa comprovar finalidade comercial "
        "legítima perante a autoridade nacional.", False, "artigo trocado e regra inventada"),

    # --------------------------------------------------------------- art. 18
    (18, "O titular pode obter do controlador a confirmação da existência de tratamento e o "
         "acesso aos seus dados, além da correção de dados incompletos, inexatos ou "
         "desatualizados.", True, ""),
    (18, "Também é direito do titular pedir a portabilidade dos dados a outro fornecedor de "
         "serviço e a eliminação dos dados tratados com base no consentimento.", True, ""),
    (18, "O controlador tem prazo máximo de 15 dias corridos para responder a qualquer "
         "requisição do titular, sob pena de multa automática.", False, "prazo e sanção inventados"),
    (18, "O direito de acesso só pode ser exercido por titulares que tenham contrato vigente "
         "com a empresa há pelo menos seis meses.", False, "restrição inexistente"),

    # --------------------------------------------------------------- art. 20
    (20, "O titular tem direito de solicitar a revisão de decisões tomadas unicamente com base "
         "em tratamento automatizado que afetem seus interesses, incluindo decisões sobre seu "
         "perfil pessoal, profissional, de consumo e de crédito.", True, ""),
    (20, "O controlador deve fornecer, sempre que solicitado, informações claras e adequadas "
         "sobre os critérios e procedimentos usados na decisão automatizada, observados os "
         "segredos comercial e industrial.", True, ""),
    (20, "A revisão de decisão automatizada precisa obrigatoriamente ser feita por uma pessoa "
         "natural, conforme exige o texto vigente do artigo.", False,
         "o dispositivo que previa revisão humana foi vetado"),
    (20, "O art. 22 assegura ao titular o direito de exigir a exclusão do algoritmo utilizado "
         "pela empresa.", False, "artigo trocado e direito inventado"),

    # --------------------------------------------------------------- art. 37
    (37, "Controlador e operador devem manter registro das operações de tratamento que "
         "realizarem, especialmente quando o tratamento tem por base o legítimo interesse.", True, ""),
    (37, "A obrigação de manter registro das operações alcança tanto o controlador quanto o "
         "operador.", True, ""),
    (37, "O registro das operações deve ser enviado mensalmente à autoridade nacional em "
         "formato XML.", False, "obrigação e formato inventados"),

    # --------------------------------------------------------------- art. 38
    (38, "A autoridade nacional pode determinar ao controlador que elabore relatório de impacto "
         "à proteção de dados pessoais, inclusive quanto a dados sensíveis, respeitados os "
         "segredos comercial e industrial.", True, ""),
    (38, "O relatório de impacto deve conter, no mínimo, a descrição dos tipos de dados "
         "coletados, a metodologia utilizada para a coleta e as medidas e mecanismos de "
         "mitigação de risco adotados.", True, ""),
    (38, "O relatório de impacto é obrigatório para toda empresa com mais de cem funcionários, "
         "independentemente de determinação da autoridade.", False, "critério inventado"),

    # --------------------------------------------------------------- art. 46
    (46, "Os agentes de tratamento devem adotar medidas de segurança, técnicas e "
         "administrativas, capazes de proteger os dados pessoais de acessos não autorizados e "
         "de situações acidentais ou ilícitas de destruição, perda ou alteração.", True, ""),
    (46, "A autoridade nacional pode dispor sobre padrões técnicos mínimos, considerando a "
         "natureza das informações, as características do tratamento e o estado atual da "
         "tecnologia, especialmente no caso de dados sensíveis.", True, ""),
    (46, "O artigo exige criptografia AES-256 em repouso e em trânsito para todo dado pessoal "
         "armazenado por empresa brasileira.", False, "especificação técnica inventada"),
    (46, "As medidas de segurança só passam a ser exigíveis depois que a autoridade nacional "
         "publicar os padrões técnicos mínimos.", False, "condiciona obrigação que já é vigente"),

    # --------------------------------------------------------------- art. 48
    (48, "O controlador deve comunicar à autoridade nacional e ao titular a ocorrência de "
         "incidente de segurança que possa acarretar risco ou dano relevante aos titulares.", True, ""),
    (48, "A comunicação do incidente deve mencionar, entre outros pontos, a natureza dos dados "
         "afetados, as informações sobre os titulares envolvidos e as medidas técnicas de "
         "segurança utilizadas para a proteção dos dados.", True, ""),
    (48, "O incidente de segurança deve ser comunicado à autoridade nacional em até 72 horas "
         "contadas do conhecimento do fato.", False,
         "prazo do RGPD europeu; a LGPD fala em prazo razoável"),
    (48, "A comunicação de incidente é dispensada quando a empresa contrata seguro cibernético.", False,
         "dispensa inventada"),

    # --------------------------------------------------------------- art. 52
    (52, "As sanções previstas incluem advertência com indicação de prazo para adoção de "
         "medidas corretivas e multa simples de até dois por cento do faturamento no Brasil no "
         "último exercício, limitada a cinquenta milhões de reais por infração.", True, ""),
    (52, "Além da multa, a lei prevê a publicização da infração, o bloqueio dos dados pessoais "
         "a que se refere a infração e a eliminação desses dados.", True, ""),
    (52, "A lei prevê suspensão parcial do funcionamento do banco de dados por até seis meses, "
         "prorrogável por igual período.", True, ""),
    (52, "A multa por infração à LGPD pode chegar a cem milhões de reais por ocorrência.", False,
         "teto arredondado para cima; o real é cinquenta milhões"),
    (52, "Descumprimento reiterado da lei acarreta prisão dos administradores da empresa por "
         "até dois anos.", False, "sanção penal inexistente na lei"),
    (52, "As sanções são aplicadas pelo Ministério Público Federal após denúncia formal.", False,
         "competência trocada"),
]

def baixar_lei(url: str = URL_LGPD) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": NAVEGADOR})
    bruto = urllib.request.urlopen(req, timeout=90).read()
    for codificacao in ("utf-8", "latin-1"):
        try:
            texto = bruto.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise RuntimeError("não foi possível decodificar a página")

    texto = libhtml.unescape(re.sub(r"<[^>]+>", " ", texto))
    texto = re.sub(r"\s+", " ", texto)
    inicio = texto.find("Art. 1º")
    return texto[inicio:] if inicio > 0 else texto


def separar_artigos(texto: str) -> dict[int, str]:
    artigos: dict[int, str] = {}
    for pedaco in re.split(r"(?=\bArt\.\s*\d+)", texto):
        achado = re.match(r"Art\.\s*(\d+)", pedaco)
        if not achado:
            continue
        numero = int(achado.group(1))
        pedaco = pedaco.strip()
        if len(pedaco) > len(artigos.get(numero, "")):
            artigos[numero] = pedaco
    return artigos


def montar(artigos: dict[int, str]) -> dict:
    """Monta o arquivo no formato normalizado.

    As fontes ficam num dicionário à parte e cada caso aponta para o artigo.
    A primeira versão repetia o texto do artigo dentro de cada caso — três ou
    quatro cópias do mesmo trecho — e o arquivo ficou com 66 KB. Normalizado,
    caiu para menos de um terço, e passou a existir um único lugar onde o
    texto da fonte pode ser corrigido.
    """
    faltando = sorted(set(ARTIGOS) - set(artigos))
    if faltando:
        raise RuntimeError(f"artigos não encontrados na fonte: {faltando}")

    fontes = {str(n): artigos[n][:limite].strip() for n, limite in ARTIGOS.items()}
    casos = [
        {
            "id": f"caso-{indice:03d}",
            "artigo_fonte": artigo,
            "resposta": " ".join(resposta.split()),
            "ancorada": ancorada,
            "problema": problema,
        }
        for indice, (artigo, resposta, ancorada, problema) in enumerate(CASOS, start=1)
    ]
    return {"lei": "Lei 13.709/2018 (LGPD)", "origem": URL_LGPD, "fontes": fontes, "casos": casos}


def carregar(caminho: str | Path = DESTINO) -> list[dict]:
    """Lê o arquivo e devolve cada caso já com o texto da sua fonte.

    Função única de leitura para avaliação, conferência e testes: se o formato
    do arquivo mudar, muda em um lugar só.
    """
    dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    fontes = dados["fontes"]
    return [
        {**caso, "fontes": [fontes[str(caso["artigo_fonte"])]]}
        for caso in dados["casos"]
    ]


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument(
        "--sem-rede",
        action="store_true",
        help="não baixa a lei; apenas confere o arquivo já gravado",
    )
    argumentos = analisador.parse_args()

    if argumentos.sem_rede:
        if not DESTINO.exists():
            print(f"{DESTINO} não existe — rode sem --sem-rede uma vez.", file=sys.stderr)
            return 1
    else:
        dados = montar(separar_artigos(baixar_lei()))
        DESTINO.parent.mkdir(parents=True, exist_ok=True)
        DESTINO.write_text(
            json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    casos = carregar()
    ancoradas = sum(1 for c in casos if c["ancorada"])
    print(f"{len(casos)} casos em {DESTINO} ({DESTINO.stat().st_size // 1024} KB)")
    print(f"  ancoradas:     {ancoradas}")
    print(f"  com invenção:  {len(casos) - ancoradas}")
    print(f"  artigos usados: {sorted({c[chr(39)+chr(39)] if False else c['artigo_fonte'] for c in casos})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
