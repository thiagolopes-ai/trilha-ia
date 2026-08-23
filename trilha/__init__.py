"""Trilha de auditoria para decisões apoiadas por inteligência artificial."""

from .ancoragem import Veredito, verificar
from .auditor import Auditor, Politica, Resultado
from .registro import (
    APROVADA,
    NAO_REQUERIDA,
    PENDENTE,
    REPROVADA,
    Cofre,
    Registro,
    Trilha,
)

__all__ = [
    "APROVADA",
    "Auditor",
    "Cofre",
    "NAO_REQUERIDA",
    "PENDENTE",
    "Politica",
    "REPROVADA",
    "Registro",
    "Resultado",
    "Trilha",
    "Veredito",
    "verificar",
]

__version__ = "0.1.0"
