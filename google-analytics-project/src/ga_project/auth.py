"""Autenticação com a Google Analytics Data API (Service Account)."""
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.auth.exceptions import DefaultCredentialsError

from ga_project.errors import GA4ProjectError


def create_ga4_client() -> BetaAnalyticsDataClient:
    """Cria o cliente GA4.

    Precisa ser chamada DEPOIS de load_settings(), que deixa a variável
    GOOGLE_APPLICATION_CREDENTIALS pronta. O cliente lê o JSON sozinho.
    """
    try:
        return BetaAnalyticsDataClient()
    except DefaultCredentialsError as exc:
        raise GA4ProjectError(f"Credencial inválida ou ilegível: {exc}") from exc
