"""Confere o gabarito antes de acreditar em qualquer métrica.

Este script não avalia o detector. Ele avalia **o conjunto de avaliação**, que
é o erro mais caro e mais silencioso de um projeto de IA: quando o gabarito
está errado, todo número medido em cima dele é ficção — e o gráfico continua
bonito.

Duas checagens:

1. Toda resposta marcada como fiel precisa ter, nas fontes, os termos que ela
   afirma. Cobertura baixa aqui quase sempre significa fonte truncada antes do
   trecho citado — foi exatamente o que aconteceu com o art. 6 na primeira
   rodada.
2. Toda citação normativa feita por uma resposta fiel precisa existir na fonte.

Uso:
    python conferir_gabarito.py
"""

from __future__ import annotations

import sys

from preparar_casos import carregar
from trilha.ancoragem import citacoes, dividir_frases, termos

PISO_SUSPEITA = 0.60  # abaixo disso a resposta "fiel" merece leitura humana


def main() -> int:
    casos = carregar()
    suspeitas: list[str] = []

    for caso in casos:
        if not caso["ancorada"]:
            continue

        texto_fontes = " ".join(caso["fontes"])
        nas_fontes = termos(texto_fontes)

        for frase in dividir_frases(caso["resposta"]):
            alvo = termos(frase)
            if len(alvo) < 3:
                continue
            cobertura = len(alvo & nas_fontes) / len(alvo)
            if cobertura < PISO_SUSPEITA:
                faltando = sorted(alvo - nas_fontes)
                suspeitas.append(
                    f"{caso['id']} (art. {caso['artigo_fonte']}) cobertura "
                    f"{cobertura:.2f} — ausentes na fonte: {', '.join(faltando)}"
                )

        inventadas = citacoes(caso["resposta"]) - citacoes(texto_fontes)
        if inventadas:
            suspeitas.append(
                f"{caso['id']} cita {sorted(inventadas)} e a fonte não tem"
            )

    fieis = sum(1 for c in casos if c["ancorada"])
    print(f"{len(casos)} casos conferidos ({fieis} rotulados como fiéis)")

    if not suspeitas:
        print("Nenhuma resposta fiel afirma algo que não está na fonte.")
        return 0

    print(f"\n{len(suspeitas)} resposta(s) fiéis merecem leitura humana:")
    for linha in suspeitas:
        print(f"  {linha}")
    print(
        "\nCobertura baixa numa resposta fiel costuma significar paráfrase "
        "legítima (sinônimo que a fonte não usa) ou fonte cortada antes do "
        "trecho citado. A primeira é limitação conhecida do método; a segunda "
        "é defeito do gabarito e precisa ser corrigida."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
