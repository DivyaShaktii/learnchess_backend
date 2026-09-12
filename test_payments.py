import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from fastapi import HTTPException
from app.payments import authenticated_user, validate_purchase, grant_premium


class PaymentsTest(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.order.fetch.return_value = {'amount': 100, 'currency': 'INR', 'notes': {'user_id': 'alice'}}
        self.client.payment.fetch.return_value = {'amount': 100, 'currency': 'INR', 'status': 'captured', 'order_id': 'order1'}

    def test_captured_payment_for_owner(self):
        self.assertEqual(validate_purchase(self.client, 'order1', 'pay1', 'alice'), 'alice')

    def test_reject_replayed_payment_for_different_user(self):
        with self.assertRaises(HTTPException) as e:
            validate_purchase(self.client, 'order1', 'pay1', 'bob')
        self.assertEqual(e.exception.status_code, 403)

    def test_reject_uncaptured_or_wrong_amount_currency_or_order(self):
        for field, value in [('status', 'authorized'), ('amount', 1), ('currency', 'USD'), ('order_id', 'other')]:
            with self.subTest(field=field):
                payment = dict(self.client.payment.fetch.return_value)
                self.client.payment.fetch.return_value = {**payment, field: value}
                with self.assertRaises(HTTPException):
                    validate_purchase(self.client, 'order1', 'pay1', 'alice')
                self.client.payment.fetch.return_value = payment

    def test_db_failure_or_empty_write_never_succeeds(self):
        db = Mock()
        db.table.return_value.upsert.return_value.execute.return_value.data = []
        with self.assertRaises(HTTPException) as e:
            grant_premium(db, 'alice')
        self.assertEqual(e.exception.status_code, 503)
        db.table.return_value.upsert.return_value.execute.side_effect = RuntimeError('offline')
        with self.assertRaises(HTTPException): grant_premium(db, 'alice')

    def test_authentication_and_email_confirmation(self):
        db = Mock()
        request = SimpleNamespace(headers={})
        with self.assertRaises(HTTPException): authenticated_user(request, db)
        request.headers['authorization'] = 'Bearer token'
        db.auth.get_user.return_value.user = SimpleNamespace(id='alice', email_confirmed_at=None)
        with self.assertRaises(HTTPException): authenticated_user(request, db)
        db.auth.get_user.return_value.user.email_confirmed_at = '2026-09-11'
        self.assertEqual(authenticated_user(request, db, 'alice').id, 'alice')
        with self.assertRaises(HTTPException): authenticated_user(request, db, 'bob')

if __name__ == '__main__': unittest.main()
