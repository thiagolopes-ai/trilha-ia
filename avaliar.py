"""Mede o detector de ancoragem contra o gabarito.

A pergunta que este script responde: *quando o detector diz que uma resposta
tem trecho sem lastro na fonte, ele está certo com que frequência — e quantas
invenções ele deixa passar?*

O que importa aqui é o **recall sobre invenção**. Um detector de auditoria que
deixa passar alucinação é pior que inútil, porque produz uma trilha que dá
falsa segurança. Precisão baixa custa tempo de revisor; recall baixo custa
credibilidade da empresa.

Uso:
    python avaliar.py                 # compara métodos e varre limiares
    python avaliar.py --json saida.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from preparar_casos import DESTINO as ORIGEM
from preparar_casos import carregar
from trilha.ancoragem import verificar


def metricas(verdadeiro_positivo: int, falso_positivo: int, falso_negativo: int) -> dict:
    precisao = (
        verdadeiro_positivo / (verdadeiro_positivo + falso_positivo)
        if verdadeiro_positivo + falso_positivo
        else 0.0
    )
    recall = (
        verdadeiro_positivo / (verdadeiro_positivo + falso_negativo)
        if verdadeiro_positivo + falso_negativo
        else 0.0
    )
    f1 = 2 * precisao * recall / (precisao + recall) if precisao + recall else 0.0
    return {"precisao": round(precisao, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def rodar(casos: list[dict], metodo: str, limiar: float, checar_citacoes: bool) -> dict:
    """A classe positiva é 'a resposta contém invenção'."""
    vp = fp = fn = vn = 0
    erros: list[dict] = []

    for caso in casos:
        veredito = verificar(
            caso["resposta"],
            caso["fontes"],
            limiar=limiar,
            metodo=metodo,
            checar_citacoes=checar_citacoes,
        )
        acusou = not veredito.ancorada
        inventou = not caso["ancorada"]

        if acusou and inventou:
            vp += 1
        elif acusou and not inventou:
            fp += 1
            erros.append({"id": caso["id"], "tipo": "falso alarme", "score": veredito.score})
        elif not acusou and inventou:
            fn += 1
            erros.append(
                {
                    "id": caso["id"],
                    "tipo": "invenção não detectada",
                    "score": veredito.score,
                    "problema": caso["problema"],
                }
            )
        else:
            vn += 1

    resultado = {
        "metodo": metodo,
        "limiar": limiar,
        "checar_citacoes": checar_citacoes,
        "acuracia": round((vp + vn) / len(casos), 4),
        **metricas(vp, fp, fn),
        "verdadeiro_positivo": vp,
        "falso_positivo": fp,
        "falso_negativo": fn,
        "verdadeiro_negativo": vn,
        "erros": erros,
    }
    return resultado


def linha_de_base(casos: list[dict], estrategia: str) -> dict:
    """Detector burro, para dar escala ao número do detector de verdade.

    'Acusar tudo' tem recall perfeito e não serve para nada: manda o revisor
    ler cada resposta. É contra isso que o F1 do detector precisa ganhar — não
    contra zero.
    """
    inventadas = sum(1 for c in casos if not c["ancorada"])
    fieis = len(casos) - inventadas
    if estrategia == "acusar tudo":
        vp, fp, fn, vn = inventadas, fieis, 0, 0
    else:
        vp, fp, fn, vn = 0, 0, inventadas, fieis
    return {
        "metodo": estrategia,
        "limiar": 0.0,
        "checar_citacoes": False,
        "acuracia": round((vp + vn) / len(casos), 4),
        **metricas(vp, fp, fn),
        "verdadeiro_positivo": vp,
        "falso_positivo": fp,
        "falso_negativo": fn,
        "verdadeiro_negativo": vn,
        "erros": [],
    }


def tabela(linhas: list[dict]) -> str:
    cabecalho = (
        f"{'método':>12} {'limiar':>7} {'citações':>9} {'acurácia':>9} "
        f"{'precisão':>9} {'recall':>7} {'F1':>7}"
    )
    saida = [cabecalho, "-" * len(cabecalho)]
    for r in linhas:
        saida.append(
            f"{r['metodo']:>12} {r['limiar']:>7.2f} "
            f"{('sim' if r['checar_citacoes'] else 'não'):>9} "
            f"{r['acuracia']:>9.3f} {r['precisao']:>9.3f} "
            f"{r['recall']:>7.3f} {r['f1']:>7.3f}"
        )
    return "\n".join(saida)


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("--casos", default=str(ORIGEM))
    analisador.add_argument("--json", help="grava o resultado completo neste arquivo")
    argumentos = analisador.parse_args()

    casos = carregar(argumentos.casos)
    print(f"{len(casos)} casos — {sum(1 for c in casos if c['ancorada'])} ancorados, "
          f"{sum(1 for c in casos if not c['ancorada'])} com invenção\n")

    limiares = [0.20, 0.30, 0.40, 0.50, 0.55, 0.60, 0.70, 0.80]
    resultados = []
    for metodo in ("cobertura", "tfidf"):
        for limiar in limiares:
            for checar in (True, False):
                resultados.append(rodar(casos, metodo, limiar, checar))

    print("LINHA DE BASE (o número contra o qual o detector precisa valer a pena)")
    print(tabela([linha_de_base(casos, "acusar tudo"), linha_de_base(casos, "acusar nada")]))

    print("\nVARREDURA DE LIMIAR")
    print(tabela(resultados))

    melhor = max(resultados, key=lambda r: (r["f1"], r["recall"]))
    print(f"\nMELHOR CONFIGURAÇÃO POR F1: {melhor['metodo']} @ limiar {melhor['limiar']}, "
          f"checagem de citações {'ligada' if melhor['checar_citacoes'] else 'desligada'}")
    print(f"  acurácia {melhor['acuracia']}  precisão {melhor['precisao']}  "
          f"recall {melhor['recall']}  F1 {melhor['f1']}")

    print("\nCONTRIBUIÇÃO DA CHECAGEM DE CITAÇÕES (mesmo método e limiar)")
    com = [r for r in resultados if r["checar_citacoes"]]
    sem = [r for r in resultados if not r["checar_citacoes"]]
    melhor_com = max(com, key=lambda r: r["f1"])
    melhor_sem = max(sem, key=lambda r: r["f1"])
    print(f"  com checagem: F1 {melhor_com['f1']} ({melhor_com['metodo']} @ {melhor_com['limiar']})")
    print(f"  sem checagem: F1 {melhor_sem['f1']} ({melhor_sem['metodo']} @ {melhor_sem['limiar']})")

    print("\nO QUE O MELHOR DETECTOR AINDA DEIXA PASSAR")
    if not melhor["erros"]:
        print("  nada")
    for erro in melhor["erros"]:
        print(f"  {erro['id']:>9}  {erro['tipo']:<24} score {erro['score']:.3f}"
              + (f"  — {erro['problema']}" if erro.get("problema") else ""))

    if argumentos.json:
        Path(argumentos.json).write_text(
            json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nresultado completo em {argumentos.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
