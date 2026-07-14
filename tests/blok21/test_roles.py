"""BLOK 21 - test_roles: backend rol kontrolu (12 test).

Kapsam: header yok 401, bos 401, yanlis 403, ADMIN ok, READONLY ok,
ADMIN>=READONLY require, READONLY ADMIN gereken yerde ROLE_FORBIDDEN,
token mesajda sizmaz, env json parse, bozuk json {}, dict provider,
compare_digest kullanimi. Tum token degerleri SAHTE (test verisi).
"""
from __future__ import annotations

import secrets as stdlib_secrets

import pytest

from app.api.masking import ApiError
from app.ops import roles as roles_mod
from app.ops.roles import (
    CODE_ROLE_FORBIDDEN,
    ROLE_ADMIN,
    ROLE_READONLY,
    RoleAuth,
    load_token_roles_from_env,
)

ADMIN_TOK = "test-admin-token-aaaa"
RO_TOK = "test-readonly-token-bbbb"
ROLES = {ADMIN_TOK: ROLE_ADMIN, RO_TOK: ROLE_READONLY}


def _auth(provider=None):
    return RoleAuth(provider if provider is not None else dict(ROLES))


def test_header_yok_401():
    with pytest.raises(ApiError) as excinfo:
        _auth().role_for({})
    assert excinfo.value.status == 401
    assert excinfo.value.code == "ADMIN_TOKEN_MISSING"


def test_header_bos_401():
    with pytest.raises(ApiError) as excinfo:
        _auth().role_for({"X-Admin-Token": "   "})
    assert excinfo.value.status == 401
    assert excinfo.value.code == "ADMIN_TOKEN_MISSING"


def test_yanlis_token_403():
    with pytest.raises(ApiError) as excinfo:
        _auth().role_for({"X-Admin-Token": "yanlis-token-00000"})
    assert excinfo.value.status == 403
    assert excinfo.value.code == "ADMIN_TOKEN_INVALID"


def test_admin_token_rolu_admin():
    rol = _auth().role_for({"x-admin-token": ADMIN_TOK})
    assert rol == ROLE_ADMIN


def test_readonly_token_rolu_readonly():
    rol = _auth().role_for({"X-Admin-Token": RO_TOK})
    assert rol == ROLE_READONLY


def test_require_admin_readonly_gereken_yerde_gecer():
    rol = _auth().require({"X-Admin-Token": ADMIN_TOK}, ROLE_READONLY)
    assert rol == ROLE_ADMIN


def test_require_readonly_admin_gereken_yerde_forbidden():
    with pytest.raises(ApiError) as excinfo:
        _auth().require({"X-Admin-Token": RO_TOK}, ROLE_ADMIN)
    assert excinfo.value.status == 403
    assert excinfo.value.code == CODE_ROLE_FORBIDDEN


def test_token_degeri_hata_mesajinda_sizmaz():
    gizli = "cok-gizli-token-degeri-xyz"
    auth = RoleAuth({"baska-token-111": ROLE_ADMIN})
    for headers in ({}, {"X-Admin-Token": gizli}):
        with pytest.raises(ApiError) as excinfo:
            auth.require(headers, ROLE_ADMIN)
        assert gizli not in str(excinfo.value)
        assert gizli not in excinfo.value.message


def test_env_json_parse():
    env = {
        "ADMIN_TOKEN": ADMIN_TOK,
        "ADMIN_ROLES_JSON": '{"%s": "READONLY"}' % RO_TOK,
    }
    roles = load_token_roles_from_env(env)
    assert roles[RO_TOK] == ROLE_READONLY
    assert roles[ADMIN_TOK] == ROLE_ADMIN


def test_env_bozuk_json_guvenli_bos_dict():
    env = {"ADMIN_TOKEN": ADMIN_TOK, "ADMIN_ROLES_JSON": "{bozuk-json"}
    assert load_token_roles_from_env(env) == {}
    env2 = {"ADMIN_TOKEN": ADMIN_TOK, "ADMIN_ROLES_JSON": '["liste", "degil"]'}
    assert load_token_roles_from_env(env2) == {}


def test_dict_provider_dogrudan_kullanilir():
    auth = RoleAuth({RO_TOK: ROLE_READONLY})
    assert auth.require({"X-Admin-Token": RO_TOK}, ROLE_READONLY) == ROLE_READONLY


def test_compare_digest_ile_karsilastirilir(monkeypatch):
    cagri = []
    gercek = stdlib_secrets.compare_digest

    def casus(a, b):
        cagri.append((a, b))
        return gercek(a, b)

    monkeypatch.setattr(roles_mod.secrets, "compare_digest", casus)
    rol = _auth().role_for({"X-Admin-Token": ADMIN_TOK})
    assert rol == ROLE_ADMIN
    assert cagri, "compare_digest cagrilmadi"
    assert any(ADMIN_TOK in (a, b) for a, b in cagri)
