"""Testes do cadastro de clientes."""
import json

import pytest
from helpers import fresh_db

from ga_project.clientes import (
    add_cliente, count_clientes, ensure_cliente, get_cliente, list_clientes, service_account_email,
    set_ativo, update_cliente, validate_ga4_property_id, validate_gsc_site_url, validate_slug,
)
from ga_project.errors import GA4ProjectError


def test_slug_valido_e_invalido():
    assert validate_slug("loja-exemplo") == "loja-exemplo" and validate_slug("a1") == "a1"
    for bad in ("", "a", "Loja", "loja exemplo", "-loja", "loja-", "loja_x", "lójá", "x" * 41):
        with pytest.raises(GA4ProjectError, match="Slug inválido"):
            validate_slug(bad)


def test_ids_do_google_sao_validados_e_normalizados():
    assert validate_ga4_property_id("properties/123456789") == "123456789"
    assert validate_ga4_property_id("  ") is None and validate_ga4_property_id(None) is None
    with pytest.raises(GA4ProjectError, match="só números"):
        validate_ga4_property_id("abc")
    assert validate_gsc_site_url("sc-domain:exemplo.com.br") == "sc-domain:exemplo.com.br"
    assert validate_gsc_site_url("https://www.exemplo.com.br/") == "https://www.exemplo.com.br/"
    with pytest.raises(GA4ProjectError, match="Search Console"):
        validate_gsc_site_url("exemplo.com.br")


def test_cadastro_e_leitura_com_privacidade_da_ia_desligada_por_padrao():
    conn = fresh_db()
    c = add_cliente(conn, "loja-a", "Loja A", "123456789", "sc-domain:a.com.br")
    assert (c.slug, c.nome, c.ga4_property_id, c.gsc_site_url, c.ativo) == ("loja-a", "Loja A", "123456789", "sc-domain:a.com.br", True)
    assert c.enviar_consultas_ia is False
    assert get_cliente(conn, "loja-a") == c


def test_slug_duplicado_e_cliente_inexistente_dao_erro_claro():
    conn = fresh_db()
    add_cliente(conn, "loja-a", "Loja A")
    with pytest.raises(GA4ProjectError, match="Já existe"):
        add_cliente(conn, "loja-a", "Outra")
    with pytest.raises(GA4ProjectError, match="não encontrado"):
        get_cliente(conn, "fantasma")
    with pytest.raises(GA4ProjectError, match="não encontrado"):
        update_cliente(conn, "fantasma", nome="X")


def test_atualizacao_nao_permite_trocar_slug_nem_ativar_por_aqui():
    conn = fresh_db()
    add_cliente(conn, "loja-a", "Loja A")
    updated = update_cliente(conn, "loja-a", nome="Loja A Ltda", ga4_property_id="987654321", enviar_consultas_ia=True)
    assert (updated.nome, updated.ga4_property_id, updated.enviar_consultas_ia) == ("Loja A Ltda", "987654321", True)
    with pytest.raises(GA4ProjectError, match="não editável"):
        update_cliente(conn, "loja-a", ativo=False)          # ativar/desativar tem comando próprio; o slug nem é aceito


def test_desativar_nao_apaga_e_tira_das_listas_de_ativos():
    conn = fresh_db()
    add_cliente(conn, "loja-a", "Loja A")
    add_cliente(conn, "loja-b", "Loja B")
    set_ativo(conn, "loja-b", False)
    assert [c.slug for c in list_clientes(conn)] == ["loja-a", "loja-b"]
    assert [c.slug for c in list_clientes(conn, only_active=True)] == ["loja-a"]
    assert get_cliente(conn, "loja-b").ativo is False
    assert set_ativo(conn, "loja-b", True).ativo is True


def test_paginacao_e_contagem():
    conn = fresh_db()
    for i in range(25):
        add_cliente(conn, f"loja-{i:02d}", f"Loja {i}")
    assert count_clientes(conn) == 25
    page1, page2, page3 = (list_clientes(conn, limit=10, offset=o) for o in (0, 10, 20))
    assert (len(page1), len(page2), len(page3)) == (10, 10, 5)
    assert len({c.slug for c in page1 + page2 + page3}) == 25


def test_ensure_cliente_e_idempotente():
    conn = fresh_db()
    first = ensure_cliente(conn, "loja-a", "Loja A")
    assert ensure_cliente(conn, "loja-a", "Nome diferente") == first
    assert count_clientes(conn) == 1


def test_email_da_conta_de_servico_le_so_o_email(tmp_path):
    key = tmp_path / "chave.json"
    key.write_text(json.dumps({"client_email": "robo@projeto.iam.gserviceaccount.com", "private_key": "SEGREDO"}), encoding="utf-8")
    assert service_account_email(key) == "robo@projeto.iam.gserviceaccount.com"
    assert service_account_email(tmp_path / "nao_existe.json") is None
    broken = tmp_path / "quebrada.json"
    broken.write_text("{nao e json", encoding="utf-8")
    assert service_account_email(broken) is None
