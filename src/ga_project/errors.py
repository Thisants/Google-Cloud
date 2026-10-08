"""Erros do projeto.

Usar uma exceção própria deixa o main.py simples: ele captura apenas
GA4ProjectError e mostra uma mensagem clara, sem despejar o traceback.
"""


class GA4ProjectError(Exception):
    """Erro esperado (configuração, credencial, permissão, consulta inválida...)."""
