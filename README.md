# trilha-ia

Camada de auditoria para decisões apoiadas por modelos de linguagem. Verifica se a resposta está sustentada pelas fontes, registra tudo de forma rastreável e manda para revisão humana o que precisa de olho humano.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)
![Licença MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-green?style=flat-square)

---

## O problema

Uma empresa coloca um modelo de linguagem para responder dúvidas de RH, triar currículo, sugerir enquadramento de contrato ou pontuar risco de fornecedor. Seis meses depois alguém questiona uma dessas decisões — um candidato, um empregado, um cliente, a ANPD.

E aí a empresa descobre que não sabe responder três perguntas básicas:

1. **Qual modelo respondeu?** Ninguém anotou a versão. O provedor já trocou o modelo duas vezes desde então.
2. **Com base em qual fonte?** A resposta citou um artigo de lei. Ninguém sabe se aquele artigo estava mesmo no material que o modelo recebeu, ou se ele inventou.
3. **Quem revisou?** Ninguém. Ou alguém, mas não ficou registrado — o que dá no mesmo perante um auditor.

Esse é o buraco. Não é falta de IA. É falta de trilha.

O **art. 20 da LGPD** dá ao titular o direito de solicitar revisão de decisões tomadas unicamente com base em tratamento automatizado, e obriga o controlador a fornecer informações claras sobre os critérios e procedimentos usados. Sem registro, esse direito não é atendível — não por má-fé, mas porque a informação simplesmente não existe.

---

## A solução

Toda chamada de modelo vira uma linha auditável:

```
     aplicação                 trilha-ia                       banco
         │                         │                             │
   pergunta + fontes ──────────────▶                             │
   resposta do modelo ─────────────▶                             │
                                   │                             │
                          verifica ancoragem                     │
                          frase a frase                          │
                                   │                             │
                          decide se precisa                      │
                          de revisão humana                      │
                                   │                             │
                                   ├──── grava (conteúdo cifrado)▶│
                                   │                             │
   ◀───── id + veredito ───────────┤                             │
                                   │                             │
   revisor ────── justificativa ───▶ grava quem, quando, por quê ▶│
```

O `trilha-ia` **não chama modelo nenhum**. Ele recebe o que entrou e o que saiu. Isso é decisão de projeto, não limitação: funciona com qualquer provedor — inclusive um que ainda não existe — e qualquer pessoa consegue rodar este repositório e conferir os números sem ter chave de API.

---

## O número

A pergunta que a medição responde: **quando o detector diz que uma resposta tem trecho sem lastro na fonte, ele está certo com que frequência — e quantas invenções deixa passar?**

Conjunto de avaliação: **36 respostas rotuladas à mão** sobre 9 artigos reais da LGPD, baixados do Planalto. 19 fiéis (paráfrases, não cópias) e 17 com invenção do tipo que modelo realmente comete.

| Método | Limiar | Acurácia | Precisão | Recall | F1 |
|---|---|---|---|---|---|
| **cobertura lexical** | **0,70** | **0,972** | **0,944** | **1,000** | **0,971** |
| cobertura lexical | 0,50 | 0,944 | 1,000 | 0,882 | 0,938 |
| TF-IDF (cosseno) | 0,40 | 0,889 | 0,809 | 1,000 | 0,895 |
| linha de base: acusar tudo | — | 0,472 | 0,472 | 1,000 | 0,641 |
| linha de base: acusar nada | — | 0,528 | 0,000 | 0,000 | 0,000 |

A classe positiva é "a resposta contém invenção". Reproduza com `python avaliar.py`.

**Por que a linha de base importa.** "Acusar tudo" também tem recall 1,000 — e é inútil, porque manda o revisor ler cada resposta. É contra o F1 de 0,641 que o detector precisa valer a pena, não contra zero. Ele vale: 0,971.

**Por que recall pesa mais que precisão aqui.** Precisão baixa custa tempo de revisor. Recall baixo custa credibilidade da empresa — uma trilha que deixa passar alucinação é pior que nenhuma trilha, porque produz falsa segurança. Por isso o limiar recomendado é 0,70 (recall 1,000, 1 falso alarme) e não 0,50 (precisão 1,000, 2 invenções escapam).

### O que o detector ainda erra

Um falso alarme em 36 casos, e ele é instrutivo:

> **Fonte:** *"O controlador e o operador devem manter registro das operações de tratamento de dados pessoais que realizarem."*
> **Resposta:** *"A obrigação de manter registro das operações alcança tanto o controlador quanto o operador."*

Fiel ao sentido. Mas "obrigação", "alcança" e "tanto/quanto" não aparecem no texto original, e a cobertura lexical cai para 0,56. **Paráfrase legítima é o limite conhecido do método.** Está documentado aqui em vez de escondido porque quem for usar isso precisa saber onde ele quebra.

### O que a checagem de citações acrescenta

Citação normativa que a resposta faz e a fonte não contém é apontada separadamente. Com o limiar bem calibrado ela **não muda nada** — a cobertura lexical já pega esses casos. Com limiar mal calibrado ela salva o resultado:

| Limiar | F1 com checagem | F1 sem checagem |
|---|---|---|
| 0,30 | 0,692 | 0,583 |
| 0,70 | 0,971 | 0,971 |

Ou seja: é rede de segurança, não é o motor. Publicar isso é mais útil que vender a funcionalidade como se fosse decisiva.

### O erro que quase entrou no número

Na primeira rodada o detector acusou uma resposta que eu havia rotulado como fiel. Fui conferir achando que era falso alarme. **Era o gabarito que estava errado:** eu tinha cortado o art. 6 em 1.400 caracteres e o inciso citado ficou de fora — a resposta realmente não estava sustentada pelo trecho fornecido.

O `conferir_gabarito.py` existe por causa disso, e roda antes dos testes na integração contínua. Gabarito não conferido mede o autor, não o método.

---

## O que fica registrado

| Campo | Por que existe |
|---|---|
| modelo e versão | Provedor troca modelo sem avisar. Sem versão, a resposta não é reproduzível |
| prompt e resposta | Cifrados em repouso |
| fontes usadas | O que o modelo tinha em mãos quando respondeu |
| tokens e custo | Governança de IA sem custo por decisão é meia governança |
| score de ancoragem | Quanto da resposta está sustentado pelas fontes |
| frases sem âncora | **Quais** frases. A média serve para relatório; as frases servem para o revisor |
| citações inventadas | Artigos citados que não estão na fonte |
| decisão automatizada | O gatilho do art. 20 |
| revisor, momento, justificativa | Sem os três, não houve revisão — houve carimbo |
| prazo de retenção | Art. 16: dado não pode ser guardado além do necessário |

---

## Conformidade no desenho, não depois

Três decisões que não são detalhe de implementação:

**Cifra em repouso (art. 46).** Prompt, resposta e trechos das fontes são cifrados com Fernet antes de tocar o disco. A chave vem de variável de ambiente e **o serviço não sobe sem ela** — deliberadamente. Subir sem cifra e "arrumar depois" é como dado vaza na prática. Existe teste que abre o arquivo do banco e procura o texto em claro:

```python
def test_conteudo_sensivel_nao_aparece_em_claro_no_banco(...):
    bruto = caminho.read_bytes()
    assert segredo.encode("utf-8") not in bruto
```

**Revisão com justificativa obrigatória (art. 20).** O campo não é opcional e tem tamanho mínimo. E a revisão é irreversível: uma vez registrada, não pode ser sobrescrita. Trilha que aceita reescrita de veredito não é trilha.

**Retenção com prazo (art. 16).** Todo registro nasce com data de validade. `POST /expurgo` apaga o que venceu. Guardar trilha para sempre não é diligência — é passivo.

> Sobre o art. 20, uma precisão que costuma passar batido: o dispositivo que **exigia revisão por pessoa natural foi vetado**. A lei garante o direito à revisão, não que ela seja humana. Este projeto exige olho humano por escolha de política, não por obrigação legal — e a política é configurável justamente por isso.

---

## Como executar

```bash
git clone https://github.com/thiagolopes-ai/trilha-ia.git
cd trilha-ia
pip install -r requirements.txt

cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# cole a chave em TRILHA_CHAVE no .env

python conferir_gabarito.py   # confere o gabarito
python avaliar.py             # reproduz a tabela acima
python -m pytest testes/ -q   # 32 testes
```

Com Docker:

```bash
echo "TRILHA_CHAVE=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" > .env
docker compose up --build
# documentação interativa em http://localhost:8000/docs
```

### Usando como biblioteca

```python
from trilha import Auditor, Trilha

auditor = Auditor(Trilha("trilha.db"))

resultado = auditor.registrar(
    modelo="claude-sonnet-4",
    versao_modelo="2025-02-19",
    prompt="O que o art. 46 da LGPD exige?",
    resposta=resposta_do_modelo,
    fontes=trechos_recuperados,
    tokens_entrada=1_240,
    tokens_saida=180,
    custo_estimado=0.0043,
    decisao_automatica=False,
)

if resultado.exige_revisao:
    notificar_revisor(resultado.id_registro, resultado.veredito.frases_sem_ancora)
```

---

## API

| Rota | O que responde |
|---|---|
| `POST /registros` | O que foi decidido, por qual modelo, com qual fonte |
| `GET /registros/{id}` | Esta decisão, inteira |
| `GET /revisoes` | O que está esperando olho humano |
| `POST /registros/{id}/revisao` | Quem revisou, quando e por quê |
| `GET /relatorio` | Números agregados: custo, ancoragem média, fila por status |
| `POST /expurgo` | Apaga o que passou do prazo de retenção |

---

## Decisões técnicas

| Decisão | Alternativa considerada | Por quê |
|---|---|---|
| Cobertura lexical | Similaridade TF-IDF | Mediu melhor: F1 0,971 contra 0,895. O TF-IDF penaliza frase curta e dilui em trecho longo |
| Cobertura lexical | Juiz LLM | Auditor não pode depender de outro modelo para dizer se o primeiro alucinou. Além disso: sem chave de API, sem custo por checagem, e roda determinístico na integração contínua |
| Verificação frase a frase | Score único da resposta | O revisor precisa saber **qual** frase abrir, não a média |
| SQLite | Postgres | O objetivo é a trilha, não a escala. Arquivo único roda em qualquer lugar e o esquema migra sem drama |
| Cifra simétrica (Fernet) | Hash irreversível | Auditoria exige ler o conteúdo original depois. Hash não volta |
| Hash do prompt em claro | Tudo cifrado | Permite buscar e deduplicar sem descriptografar nada |
| Não chamar o modelo | Cliente embutido de um provedor | Funciona com qualquer provedor e o repositório é executável por qualquer pessoa |

---

## Limitações

- **Paráfrase com vocabulário diferente da fonte gera falso alarme.** Mostrado acima, com o caso concreto. Um modelo de embeddings resolveria em parte, ao custo de dependência pesada e de perder o determinismo na integração contínua.
- **O detector não julga verdade, julga rastreabilidade.** Uma resposta certa por acaso, sem lastro na fonte, é reprovada — e para auditoria isso está correto, mas não é o mesmo que checagem de fatos.
- **36 casos é pouco.** Suficiente para calibrar o limiar e mostrar a direção; insuficiente para prometer o mesmo número em outro domínio. Fora de texto jurídico, recalibre.
- **A checagem de citações é específica de norma brasileira** (`art. X, § Y, inciso Z`). Outro domínio precisa de outro padrão.
- **Cifra protege o disco, não o acesso.** Quem tem a chave lê tudo. Controle de acesso por perfil e trilha de quem consultou a trilha ainda não existem — é o próximo passo.

---

## Próximos passos

- [ ] Autenticação e perfis de acesso na API
- [ ] Registro de quem consultou a trilha (auditar o auditor)
- [ ] Painel web da fila de revisão
- [ ] Detector opcional por embeddings, para comparar contra a cobertura lexical
- [ ] Acoplar ao [rag-juridico](https://github.com/thiagolopes-ai/rag-juridico), que hoje responde sem registrar nada

---

## Stack

Python 3.11 · FastAPI · Pydantic · SQLite · cryptography (Fernet) · scikit-learn · pytest · Docker

## Licença

MIT — veja [LICENSE](LICENSE).
