"""Shared Phase 4 test data; pure matcher only, no database or network startup."""
import json
from datetime import datetime, timezone

from rmr_platform.piq_engine.contracts import NormalizedCandidate
from rmr_platform.piq_engine.matching import match_candidate


def canonical_profile(profile_id='profile-a'):
    return {'id': profile_id, 'name': 'Target', 'industries': ['Mortgage Broker'],
            'locations': ['Phoenix, Arizona'], 'employee_min': 25, 'employee_max': 250,
            'revenue_min_cents': 5000000, 'keywords': [], 'exclusions': ['Competitor'], 'active': True}


def canonical_candidate():
    return NormalizedCandidate(
        external_provider='google_places', external_id='phase4-place',
        company_name='Local Mortgage Broker Company', formatted_address='100 Main St, Phoenix, AZ',
        city='Phoenix', state='Arizona', country='United States', latitude=33.4, longitude=-112.1,
        categories=('mortgage_broker', 'finance'), business_status='OPERATIONAL',
        phone='+1 555 0100', website='https://www.example.com/about', rating=4.7, review_count=32,
        source_url='https://maps.google.test/place', source_metadata={'api': 'places_web_service_legacy'},
        raw_metadata={'place_id': 'phase4-place'}, retrieved_at=datetime(2026, 9, 7, tzinfo=timezone.utc))


def browser_payload():
    candidate = canonical_candidate()
    match = match_candidate(canonical_profile(), candidate)
    assert match.qualified
    evidence = [
        {'id': f'evidence-{index}', 'tenant_id': 'tenant-a', 'opportunity_id': 'live-1',
         'provider': 'google_places', 'evidence_type': 'profile_criterion', 'source_name': 'Google Places',
         'source_url': candidate.source_url, 'source_title': candidate.company_name,
         'fact': f'{criterion.reason} Observed: {json.dumps(criterion.observed, ensure_ascii=True, sort_keys=True)}',
         'confidence_pct': 35 if criterion.state == 'inferred' else 90,
         'evidence_state': criterion.state, 'verified': criterion.state in {'confirmed', 'contradicted'},
         'is_synthesized': False, 'profile_criterion': criterion.criterion,
         'discovery_run_id': 'run-a', 'raw_json': {'external_id': candidate.external_id}}
        for index, criterion in enumerate(match.criteria) if criterion.evidence_refs
    ]
    opportunity = {
        'id': 'live-1', 'tenant_id': 'tenant-a', 'company_name': candidate.company_name,
        'provider': candidate.external_provider, 'source_external_id': candidate.external_id,
        'source_url': candidate.source_url, 'phone': candidate.phone, 'website': candidate.website,
        'location': candidate.formatted_address, 'industry': 'mortgage_broker, finance',
        'score': match.base_match_score, 'base_match_score': match.base_match_score,
        'confidence_score': match.confidence_score, 'evidence_completeness_pct': match.evidence_completeness_pct,
        'evidence_count': len(evidence), 'estimated_value_cents': 0, 'enhanced': False,
        'status': 'Priority', 'moved_to_crm': False, 'target_profile_id': 'profile-a',
        'signal': 'Google candidate qualified for discovery; unresolved criteria remain unverified.',
    }
    return opportunity, evidence
