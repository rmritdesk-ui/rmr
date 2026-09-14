"""Shared operator/runtime serialization; eligibility is chosen by the caller."""
import json
from datetime import date, datetime


def serialize_export(mappings, profiles, issuer):
    if len(mappings) != 1:
        raise ValueError('Exactly one active canonical mapping is required')
    mapping = dict(mappings[0])
    profiles = [dict(row) for row in profiles]
    for profile in profiles:
        for key in ('industries_json', 'locations_json', 'keywords_json', 'exclusions_json'):
            if isinstance(profile[key], str):
                profile[key] = json.loads(profile[key])
        for key, value in profile.items():
            if isinstance(value, (date, datetime)):
                profile[key] = value.isoformat()
    return {'version': 1, 'issuer': issuer.rstrip('/'), 'mapping': {key: mapping[key] for key in
            ('id', 'tenant_id', 'piq_client_id', 'integration_instance_id', 'status')}, 'profiles': profiles}
