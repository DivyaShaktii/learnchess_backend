"""Payment authentication, captured-payment validation and durable entitlement updates."""
from fastapi import HTTPException

AMOUNT = 100
CURRENCY = 'INR'


def authenticated_user(request, db, expected_id=None):
    authorization = request.headers.get('authorization', '')
    if not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Sign in before continuing.')
    try:
        user = db.auth.get_user(authorization[7:]).user
    except Exception:
        raise HTTPException(401, 'Your session expired. Please sign in again.')
    if not user or (expected_id and user.id != expected_id):
        raise HTTPException(403, 'This account does not own the request.')
    if not user.email_confirmed_at:
        raise HTTPException(403, 'Confirm your email before paying.')
    return user


def validate_purchase(client, order_id, payment_id, user_id=None):
    order = client.order.fetch(order_id)
    payment = client.payment.fetch(payment_id)
    owner = order.get('notes', {}).get('user_id')
    if not owner or (user_id and owner != user_id):
        raise HTTPException(403, 'Payment belongs to a different account.')
    if payment.get('order_id') != order_id:
        raise HTTPException(400, 'Payment and order do not match.')
    if any(item.get('amount') != AMOUNT or item.get('currency') != CURRENCY for item in (order, payment)):
        raise HTTPException(400, 'Payment amount or currency does not match this product.')
    if payment.get('status') != 'captured':
        raise HTTPException(409, 'Payment is not captured yet. Retry verification shortly; do not pay again.')
    return owner


def grant_premium(db, user_id):
    # Upsert also repairs accounts whose signup profile trigger did not run.
    try:
        result = db.table('profiles').upsert({'id': user_id, 'is_premium': True}, on_conflict='id').execute()
        if not result.data or not any(row.get('is_premium') is True for row in result.data):
            raise ValueError('No saved entitlement returned')
    except Exception:
        raise HTTPException(503, 'Payment received, but access could not be saved. Retry verification; do not pay again.')
