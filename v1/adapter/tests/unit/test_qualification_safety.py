"""Qualification must not weaken trust or broaden management mutations."""
from pathlib import Path
import sys
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'scripts'))
from rbac_fixture import PrivateConfig, management, verify_software, update_role_bindings


def test_fixture_settings_do_not_expose_secrets():
    assert 'secret' not in repr(PrivateConfig(password='secret', username='reader'))


def test_management_rejects_plaintext_before_any_network_call(monkeypatch):
    for key, value in {'REDIS_RBAC_API_URL':'http://localhost:19444',
                       'REDIS_RBAC_API_USERNAME':'user','REDIS_RBAC_API_PASSWORD':'secret',
                       'REDIS_RBAC_API_CA_FILE':'/unused'}.items():
        monkeypatch.setenv(key,value)
    with pytest.raises(ValueError, match='verified management TLS'):
        management()


@pytest.mark.parametrize('change', [{'query_performance_factor':{'active':False,'scaling_factor':4}},
                                   {'tls_mode':'disabled'}, {'eviction_policy':'allkeys-lru'},
                                   {'search':{'search-workers':1}}])
def test_fixture_rejects_unsafe_database_before_provisioning(change):
    database = {'status':'active','tls_mode':'enabled','eviction_policy':'noeviction',
                'query_performance_factor':{'active':True,'scaling_factor':4},
                'search':{'search-workers':6},'sched_policy':'mnp','conns':32, 'uid':1}
    database.update(change)
    call=Mock(side_effect=[[{'uid':1}], database, {'search':database['search']}])
    with pytest.raises(RuntimeError, match='4x QPF'):
        verify_software(call)
    assert all(args[0] == 'GET' for args, kwargs in call.call_args_list)


def test_refused_binding_update_rereads_and_preserves_unrelated_roles(monkeypatch):
    monkeypatch.setattr('rbac_fixture.time.sleep', lambda _: None)
    original = [{'role_uid': 1}, {'role_uid': 2}]
    concurrent = original + [{'role_uid': 3}]
    call = Mock(side_effect=[{'roles_permissions': original},
                            HTTPError('https://localhost/v1/bdbs/1', 409, 'Conflict', {}, None),
                            {'roles_permissions': concurrent}, None])
    update_role_bindings(call, 1, lambda current: [p for p in current if p['role_uid'] != 1])
    assert call.call_args_list[-1].args == (
        'PUT', 'bdbs/1', {'roles_permissions': [{'role_uid': 2}, {'role_uid': 3}]})


def test_unknown_binding_update_outcome_is_not_replayed():
    call = Mock(side_effect=[{'roles_permissions': []}, TimeoutError('unknown outcome')])
    with pytest.raises(TimeoutError):
        update_role_bindings(call, 1, lambda current: current)
    assert call.call_count == 2
