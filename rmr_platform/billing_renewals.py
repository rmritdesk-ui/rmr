"""Next-cycle changes using Stripe schedules and durable billing operations.

No new consent records, invoices, PaymentIntents or refunds are created here.
The initial operation's request_data remains immutable. Its result_data holds
the reconciled current items; renewal operations hold pending changes/history.
"""
from datetime import datetime, timedelta, timezone
import asyncio
import logging

from fastapi import HTTPException
from sqlalchemy import select
from stripe import StripeError

from . import billing_subscriptions as monthly
from .models import BillingOperation, BillingServicePrice, BillingSubscription
from .services import audit

logger = logging.getLogger(__name__)


def ensure_prices(db, client, tenant_id, op, services):
    """Tenant/service/amount mappings; reuse a service Product across prices."""
    items = []
    for service in services:
        key = f"{tenant_id}:{op.mode}:{service['service_code']}:{service['amount_cents']}"
        price = db.get(BillingServicePrice, key)
        if not price:
            prior = db.scalar(select(BillingServicePrice).where(
                BillingServicePrice.id.startswith(f"{tenant_id}:{op.mode}:{service['service_code']}:", autoescape=True),
                BillingServicePrice.mode == op.mode, BillingServicePrice.service_code == service['service_code']))
            metadata = {'rmr_tenant_id': tenant_id, 'rmr_service_code': service['service_code'], 'rmr_operation_id': op.id}
            product_id = prior.stripe_product_id if prior else client.v1.products.create(
                {'name': service['name'], 'metadata': metadata},
                options={'idempotency_key': f"rmr-product-{op.id}-{service['service_code']}"}).id
            remote = client.v1.prices.create({'product': product_id, 'unit_amount': service['amount_cents'],
                'currency': 'usd', 'recurring': {'interval': 'month'}, 'metadata': metadata},
                options={'idempotency_key': f"rmr-price-{op.id}-{service['service_code']}"})
            price = BillingServicePrice(id=key, mode=op.mode, service_code=service['service_code'],
                amount_cents=service['amount_cents'], stripe_product_id=product_id, stripe_price_id=remote.id)
            db.add(price)
            db.flush()
        items.append({'price': price.stripe_price_id, 'quantity': 1})
    return items


def signature(services):
    return sorted((s['service_code'], s['amount_cents']) for s in services)


def sync_schedule_payment_method(db, client, row, payment_method_id, setup_id):
    """A replacement card must also remain the default at the scheduled phase."""
    from .routes.billing import _value, _id
    history = list(db.scalars(select(BillingOperation).where(BillingOperation.tenant_id == row.tenant_id,
        BillingOperation.kind == 'renewal', BillingOperation.mode == row.mode)))
    known = {(h.result_data or {}).get('schedule_id') for h in history} - {None}
    if not known:
        return
    remote = client.v1.subscriptions.retrieve(row.stripe_subscription_id)
    schedule_id = _id(_value(remote, 'schedule'))
    if not schedule_id:
        return
    if (_id(remote.customer) != row.stripe_customer_id or remote.livemode != (row.mode == 'live') or schedule_id not in known):
        raise HTTPException(409, 'Schedule ownership mismatch during card replacement.')
    client.v1.subscription_schedules.update(schedule_id,
        {'default_settings': {'default_payment_method': payment_method_id}, 'proration_behavior': 'none'},
        options={'idempotency_key': f'rmr-schedule-card-{row.id}-{setup_id}'})


def pending(db, tenant_id, mode='test'):
    return db.scalar(select(BillingOperation).where(
        BillingOperation.active_slot == f'{tenant_id}:{mode}:renewal',
        BillingOperation.tenant_id == tenant_id, BillingOperation.kind == 'renewal', BillingOperation.mode == mode))


def record_change(db, tenant_id, actor=None):
    """Caller holds tenant lock; queue in the same transaction as assignment save."""
    from .routes.billing import _stripe_mode
    mode = _stripe_mode()
    if mode not in {'test', 'live'}:
        return
    row = monthly.subscription(db, tenant_id, mode)
    if not row or not row.stripe_subscription_id or row.status in {'canceled', 'incomplete_expired'}:
        return
    db.flush()
    desired = monthly.quote(db, tenant_id)
    old = pending(db, tenant_id, mode)
    before = monthly.current_services(db, row)
    if old and old.request_data['desired']['quote_hash'] == desired['quote_hash']:
        return
    if not old and signature(before) == signature(desired['services']):
        return
    # Finish an uncertain remote write before accepting another desired state.
    if old and (old.result_data or {}).get('state') not in {'scheduled', 'applied'}:
        raise HTTPException(409, 'A previous billing update is reconciling. Retry after it finishes.')
    if old:
        old.active_slot = None
        db.flush()
    op = BillingOperation(tenant_id=tenant_id, kind='renewal', mode=mode, active_slot=f'{tenant_id}:{mode}:renewal',
        request_data={'desired': desired, 'previous_services': before, 'actor_id': actor.id if actor else None,
            'requested_at': datetime.now(timezone.utc).isoformat()}, result_data=None)
    db.add(op); db.flush()
    audit(db, actor, 'billing.renewal_change_requested', tenant_id=tenant_id,
        entity_type='billing_operation', entity_id=op.id, data=op.request_data)


def sync_current_items(db, row, remote_items):
    """Use Stripe's current items, not edited assignments or event snapshots."""
    from .routes.billing import _value, _id
    if not remote_items or not all(_id(_value(i, 'price')) for i in remote_items):
        # Legacy/test responses may omit item details; never apply a pending change
        # from such a response. The prior accepted/current state remains intact.
        return
    op = db.get(BillingOperation, row.operation_id)
    names = {s['service_code']: s['name'] for s in monthly.current_services(db, row)}
    names.update({s['service_code']: s['name'] for s in monthly.quote(db, row.tenant_id)['services']})
    services = []
    for item in remote_items:
        price_id = _id(_value(item, 'price'))
        price = db.scalar(select(BillingServicePrice).where(BillingServicePrice.stripe_price_id == price_id,
            BillingServicePrice.mode == row.mode,
            BillingServicePrice.id.startswith(f'{row.tenant_id}:{row.mode}:', autoescape=True)))
        if not price or _value(item, 'quantity', 1) != 1:
            raise HTTPException(409, 'Unknown or cross-tenant subscription item; billing reconciliation requires review.')
        services.append({'service_code': price.service_code, 'name': names.get(price.service_code, price.service_code),
            'amount_cents': price.amount_cents, 'quantity': 1})
    if len({s['service_code'] for s in services}) != len(services):
        raise HTTPException(409, 'Duplicate subscription service items require review.')
    row.monthly_amount_cents = sum(s['amount_cents'] for s in services)
    op.result_data = {**(op.result_data or {}), 'current_services': services}


def reconcile(db, tenant_id):
    from .routes import billing as b
    client = b._sandbox_subscriptions()
    mode = b._stripe_mode()
    b._lock_tenant(db, tenant_id)
    row = monthly.subscription(db, tenant_id, mode)
    op = pending(db, tenant_id, mode)
    if not row or not op or not row.stripe_subscription_id:
        db.rollback(); return
    # A rejected Stripe configuration cannot get past _sandbox_subscriptions.
    remote = client.v1.subscriptions.retrieve(row.stripe_subscription_id, {'expand': ['latest_invoice.confirmation_secret']})
    b._sync_subscription(db, row, client, remote)
    state = op.result_data or {}
    operation_id = op.id
    desired = op.request_data['desired']
    effective = state.get('effective_at')
    start = int(row.current_period_start.timestamp()) if row.current_period_start else 0
    if effective and start >= effective and signature(monthly.current_services(db, row)) == signature(desired['services']):
        op.result_data = {**state, 'state': 'applied'}; op.active_slot = None
        audit(db, None, 'billing.renewal_change_applied', tenant_id=tenant_id,
            entity_type='billing_operation', entity_id=op.id, data={'effective_at': effective, 'services': desired['services']})
        db.commit(); return
    if row.status == 'canceled':
        if not desired['services'] and effective and int(datetime.now(timezone.utc).timestamp()) >= effective:
            row.monthly_amount_cents = 0
            agreement = db.get(BillingOperation, row.operation_id)
            agreement.result_data = {**(agreement.result_data or {}), 'current_services': []}
        op.result_data = {**state, 'state': 'applied' if not desired['services'] else 'canceled'}
        op.active_slot = None; db.commit(); return
    if state.get('state') == 'scheduled':
        db.commit(); return  # Stripe owns the future transition; no repeated writes.
    created = op.created_at.replace(tzinfo=timezone.utc) if op.created_at.tzinfo is None else op.created_at
    if datetime.now(timezone.utc) - created > timedelta(hours=23):
        raise HTTPException(409, 'Uncertain billing update expired; administrator reconciliation required.')
    if not monthly.paid(row) or not row.current_period_end:
        db.commit(); return  # Don't mutate an unpaid/incomplete subscription.
    end = int(row.current_period_end.timestamp())
    if end <= int(datetime.now(timezone.utc).timestamp()) + 60:
        raise HTTPException(409, 'Renewal boundary is too close; reconcile after renewal.')
    items = b._value(b._value(remote, 'items'), 'data', [])
    if not items or b._value(b._value(remote, 'items'), 'has_more', False):
        raise HTTPException(409, 'Complete subscription items required for scheduling.')
    current = []
    for item in items:
        price_id = b._id(b._value(item, 'price'))
        if not isinstance(price_id, str) or b._value(item, 'current_period_end') != end:
            raise HTTPException(409, 'Monthly subscription items must share one billing cycle.')
        current.append({'price': price_id, 'quantity': 1})
    future = ensure_prices(db, client, tenant_id, op, desired['services'])
    # Freeze the provider request before side effects, including its billing boundary.
    if 'schedule_params' not in op.request_data:
        phase = {'start_date': start, 'end_date': end, 'items': current, 'proration_behavior': 'none'}
        phases = [phase]
        if future:
            phases.append({'start_date': end, 'duration': {'interval': 'month', 'interval_count': 1},
                'items': future, 'proration_behavior': 'none'})
        op.request_data = {**op.request_data, 'schedule_params': {'phases': phases,
            'end_behavior': 'release' if future else 'cancel', 'proration_behavior': 'none',
            'metadata': {'rmr_tenant_id': tenant_id, 'rmr_operation_id': op.id}}}
        op.result_data = {**state, 'effective_at': end, 'state': 'preparing'}
    db.commit()
    b._lock_tenant(db, tenant_id)
    op = pending(db, tenant_id, mode)
    if not op or op.id != operation_id:
        db.rollback(); return
    if (op.result_data or {}).get('state') == 'scheduled':
        db.commit(); return
    row = monthly.subscription(db, tenant_id, mode)
    remote = client.v1.subscriptions.retrieve(row.stripe_subscription_id)
    if b._id(remote.customer) != row.stripe_customer_id or remote.livemode != (mode == 'live'):
        raise HTTPException(409, 'Subscription ownership mismatch.')
    schedule_id = (op.result_data or {}).get('schedule_id')
    remote_schedule_id = b._id(b._value(remote, 'schedule'))
    if not schedule_id and remote_schedule_id:
        # Only reuse schedules already known to this tenant's durable operations.
        history = db.scalars(select(BillingOperation).where(BillingOperation.tenant_id == tenant_id,
            BillingOperation.kind == 'renewal', BillingOperation.mode == mode))
        if any((h.result_data or {}).get('schedule_id') == remote_schedule_id for h in history):
            schedule_id = remote_schedule_id
    if schedule_id:
        schedule = client.v1.subscription_schedules.retrieve(schedule_id)
    else:
        schedule = client.v1.subscription_schedules.create({'from_subscription': row.stripe_subscription_id},
            options={'idempotency_key': f'rmr-schedule-{op.id}'})
    if (b._id(b._value(schedule, 'customer')) != row.stripe_customer_id or b._value(schedule, 'livemode') is not (mode == 'live')
            or b._id(b._value(schedule, 'subscription')) != row.stripe_subscription_id):
        raise HTTPException(409, 'Schedule ownership mismatch.')
    owner = b._value(b._value(schedule, 'metadata'), 'rmr_tenant_id')
    if owner and owner != tenant_id:
        raise HTTPException(409, 'Schedule tenant mismatch.')
    # Retain exact current schedule phase start (may predate current month).
    params = op.request_data['schedule_params']
    phase_start = b._value(b._value(schedule, 'current_phase'), 'start_date')
    if phase_start and not (op.result_data or {}).get('schedule_id'):
        params = {**params, 'phases': [{**params['phases'][0], 'start_date': phase_start}, *params['phases'][1:]]}
        op.request_data = {**op.request_data, 'schedule_params': params}
    op.result_data = {**(op.result_data or {}), 'schedule_id': schedule.id}
    db.commit()
    b._lock_tenant(db, tenant_id)
    op = pending(db, tenant_id, mode)
    if not op or op.id != operation_id:
        db.rollback(); return
    if (op.result_data or {}).get('state') != 'scheduled':
        params = op.request_data['schedule_params']
        if params['phases'][0]['end_date'] <= int(datetime.now(timezone.utc).timestamp()) + 30:
            raise HTTPException(409, 'Frozen schedule boundary passed; administrator reconciliation required.')
        client.v1.subscription_schedules.update(op.result_data['schedule_id'], params,
            options={'idempotency_key': f'rmr-schedule-update-{op.id}'})
        op.result_data = {**op.result_data, 'state': 'scheduled'}
        audit(db, None, 'billing.renewal_change_scheduled', tenant_id=tenant_id,
            entity_type='billing_operation', entity_id=op.id,
            data={'effective_at': op.result_data['effective_at'], 'previous_services': op.request_data['previous_services'],
                  'services': desired['services'], 'actor_id': op.request_data['actor_id']})
    db.commit()


def reconcile_pass():
    """Durable retry, independent of an open browser. One failed tenant is isolated."""
    if not monthly.monthly_billing_enabled():
        return
    from .db import db_session
    from .routes import billing as b
    mode = b._stripe_mode()
    if mode not in {'test', 'live'}:
        return
    with db_session() as db:
        ids = list(db.scalars(select(BillingOperation.tenant_id).where(
            BillingOperation.kind == 'renewal', BillingOperation.mode == mode, BillingOperation.active_slot.is_not(None))))
    for tenant_id in ids:
        try:
            with db_session() as db:
                reconcile(db, tenant_id)
        except StripeError as exc:
            b._log_stripe_error(exc, 'renewal-reconcile')
        except Exception as exc:
            logger.warning('Monthly renewal reconciliation deferred tenant=%s class=%s', tenant_id, type(exc).__name__)


async def run_reconciler():
    while True:
        await asyncio.sleep(60)
        try:
            await asyncio.to_thread(reconcile_pass)
        except Exception as exc:
            logger.warning('Monthly reconciliation pass deferred class=%s', type(exc).__name__)
