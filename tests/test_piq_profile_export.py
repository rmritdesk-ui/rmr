import json
import sqlite3
import pytest
from scripts.export_piq_profiles import export_profiles, validate_issuer

def test_sqlite_export_read_only_and_tenant_bound(tmp_path):
    path=tmp_path/'source.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE prospectiq_client_mappings(id TEXT,tenant_id TEXT,piq_client_id TEXT,integration_instance_id TEXT,status TEXT)')
        db.execute("INSERT INTO prospectiq_client_mappings VALUES('m','tenant','client','instance','active')")
        db.execute('CREATE TABLE piq_target_profiles(id TEXT,tenant_id TEXT,industries_json TEXT,locations_json TEXT,keywords_json TEXT,exclusions_json TEXT)')
        for tenant in ['tenant','other']:
            db.execute('INSERT INTO piq_target_profiles VALUES(?,?,?,?,?,?)',('p',tenant,json.dumps(['Mortgage','Home Services']),json.dumps(['Phoenix Metro, Arizona','Northern Colorado']),'[]','[]'))
    before=path.read_bytes()
    result=export_profiles(path,'tenant','instance','https://rmr.example/')
    assert len(result['profiles'])==1
    assert result['profiles'][0]['locations_json']==['Phoenix Metro, Arizona','Northern Colorado']
    assert result['mapping']['piq_client_id']=='client'
    assert path.read_bytes()==before
    with pytest.raises(ValueError):export_profiles(path,'other','instance','https://rmr.example')
    assert path.read_bytes()==before

@pytest.mark.parametrize('issuer',['http://rmr.example','https://user:secret@rmr.example','https://rmr.example/path','https://rmr.example/#x'])
def test_reject_unsafe_export_issuer(issuer):
    with pytest.raises(ValueError):validate_issuer(issuer)
