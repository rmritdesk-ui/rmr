"""Customer import: disposable database, no payment/research/provider calls."""
import pytest
from sqlalchemy.orm import Session

from test_prospectiq_federation import federation_engine, fx
from test_launch1_crm_drip import app_client, edit_and_reload
from rmr_platform.models import Account, Contact, Lead, TenantService


def post(client, fx, rows, operation='import-preview', tenant=None):
    return client.post(f'/api/tenants/{tenant or fx.a.id}/crm/{operation}', json={'rows': rows})


def test_client_admin_preview_commit_view_edit(app_client, fx):
    # No purchased services, including PIQ/AR, are needed for this path.
    fx.db.query(TenantService).delete()
    fx.db.commit()
    rows = [{'company_name': ' Customer ', 'contact_name': 'Pat', 'email': 'PAT@example.invalid', 'phone': '123'}]
    result = post(app_client, fx, rows)
    assert result.status_code == 200, result.text
    assert result.json()['ready'] == 1
    assert fx.db.query(Lead).count() == 0  # Preview is read-only.
    result = post(app_client, fx, rows, 'import')
    assert result.status_code == 200, result.text
    assert result.json() == {'created': 1, 'duplicates': 0, 'errors': 0, 'skipped': 0}
    with Session(fx.engine) as db:
        lead = db.query(Lead).one()
        assert (lead.tenant_id, lead.company_name, lead.email) == (fx.a.id, 'Customer', 'pat@example.invalid')
        lead_id = lead.id
    listed = app_client.get(f'/api/tenants/{fx.a.id}/leads')
    assert listed.status_code == 200 and lead_id in listed.text
    edit_and_reload(app_client, fx, lead_id)


@pytest.mark.parametrize('row', [
    {'email': 'ok@example.invalid'}, {'company_name': '   '},
    {'company_name': 'Company', 'email': 'not-an-email'},
    {'company_name': 'Company', 'email': 'x@localhost'},
    {'company_name': 'Company', 'email': 'x y@example.invalid'},
    {'company_name': 'Company', 'email': '.x@example.invalid'},
    {'company_name': 'Company', 'email': 'x..y@example.invalid'},
    {'company_name': 'Company', 'email': 'x@-example.invalid'},
    {'company_name': 'Company', 'email': 'x@example,com.invalid'},
    {'company_name': 'X' * 201}, {'company_name': 'Company', 'phone': '1' * 81},
])
def test_invalid_rows_not_imported_even_with_forged_ready(app_client, fx, row):
    row['status'] = 'ready'
    preview = post(app_client, fx, [row]).json()
    assert preview['errors'] == 1 and preview['ready'] == 0
    assert preview['preview'][0]['errors']
    result = post(app_client, fx, [row], 'import').json()
    assert result['created'] == 0 and result['errors'] == 1
    assert fx.db.query(Lead).count() == 0


def test_same_file_duplicates_preview_matches_commit(app_client, fx):
    rows = [
        {'company_name': 'One', 'email': 'A@example.invalid'},
        {'company_name': 'Other', 'email': 'a@example.invalid'},
        {'company_name': 'Two', 'contact_name': 'Pat'},
        {'company_name': ' TWO ', 'contact_name': 'pat'},
        {'company_name': 'Two', 'contact_name': 'Another'},
        {'company_name': '', 'email': 'b@example.invalid'},
        {'company_name': 'Valid', 'email': 'b@example.invalid'},
    ]
    preview = post(app_client, fx, rows).json()
    assert (preview['ready'], preview['duplicates'], preview['errors']) == (4, 2, 1)
    assert preview['preview'][1]['duplicate_reason'] == 'Duplicate within this import'
    result = post(app_client, fx, rows, 'import').json()
    assert result == {'created': 4, 'duplicates': 2, 'errors': 1, 'skipped': 3}
    assert post(app_client, fx, rows).json()['ready'] == 0
    assert post(app_client, fx, rows, 'import').json()['created'] == 0


def test_existing_crm_duplicates_and_tenant_scope(app_client, fx):
    fx.db.add_all([
        Account(tenant_id=fx.a.id, name='Existing Account'),
        Contact(tenant_id=fx.a.id, first_name='Pat', email='contact@example.invalid'),
        Lead(tenant_id=fx.a.id, company_name='Existing Lead', contact_name='Pat'),
        Lead(tenant_id=fx.a.id, company_name='Email Lead', email='lead@example.invalid'),
        Lead(tenant_id=fx.b.id, company_name='Other Tenant', email='other@example.invalid'),
    ])
    fx.db.commit()
    rows = [
        {'company_name': ' existing ACCOUNT '},
        {'company_name': 'Another', 'email': 'CONTACT@example.invalid'},
        {'company_name': 'Existing Lead', 'contact_name': 'PAT'},
        {'company_name': 'Another', 'email': 'LEAD@example.invalid'},
        {'company_name': 'Other Tenant', 'email': 'other@example.invalid', 'tenant_id': fx.b.id},
    ]
    preview = post(app_client, fx, rows).json()
    assert (preview['ready'], preview['duplicates']) == (1, 4)
    assert all(r['duplicate_reason'] == "Already in this client's CRM" for r in preview['preview'][:4])
    assert post(app_client, fx, rows, 'import').json()['created'] == 1
    with Session(fx.engine) as db:
        assert db.query(Lead).filter_by(tenant_id=fx.a.id, email='other@example.invalid').count() == 1
        assert db.query(Lead).filter_by(tenant_id=fx.b.id).count() == 1


def test_commit_rechecks_duplicates_since_preview(app_client, fx):
    rows = [{'company_name': 'Customer', 'email': 'same@example.invalid'}]
    assert post(app_client, fx, rows).json()['ready'] == 1
    fx.db.add(Lead(tenant_id=fx.a.id, company_name='Created elsewhere', email='same@example.invalid'))
    fx.db.commit()
    assert post(app_client, fx, rows, 'import').json()['duplicates'] == 1


@pytest.mark.parametrize('operation', ['import-preview', 'import'])
@pytest.mark.parametrize('mode', ['foreign', 'read_only'])
def test_import_authorization(app_client, fx, operation, mode):
    tenant = fx.b.id if mode == 'foreign' else fx.a.id
    if mode == 'read_only':
        fx.user.tenant_role = 'EXECUTIVE_VIEWER'
    response = post(app_client, fx, [{'company_name': 'Forbidden'}], operation, tenant)
    assert response.status_code == 403
    assert fx.db.query(Lead).count() == 0


@pytest.mark.parametrize('operation', ['import-preview', 'import'])
def test_server_row_limit(app_client, fx, operation):
    rows = [{'company_name': f'Company {i}'} for i in range(501)]
    assert post(app_client, fx, rows, operation).status_code == 422
    assert fx.db.query(Lead).count() == 0
    result = post(app_client, fx, rows[:500], operation)
    assert result.status_code == 200, result.text
    assert result.json()['ready' if operation == 'import-preview' else 'created'] == 500
