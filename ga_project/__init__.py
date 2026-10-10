"""Compat shim para o layout do projeto.

O código real fica em ``src/ga_project``. Quando o projeto é executado a partir da
raiz do repositório (modo de desenvolvimento), o Python só procura módulos em
``ga_project`` na raiz do projeto. Ao incluir o diretório ``src/ga_project`` no
``__path__`` do pacote, os submódulos continuam importáveis como
``ga_project.tratamento`` e ``ga_project.analytics_client`` sem exigir instalação.
"""

from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent
_SRC_PACKAGE = (_PACKAGE_ROOT.parent / "src" / "ga_project").resolve()

if _SRC_PACKAGE.exists():
    __path__ = [str(_PACKAGE_ROOT), str(_SRC_PACKAGE)]
else:
    __path__ = [str(_PACKAGE_ROOT)]

__all__ = []
