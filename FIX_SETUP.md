# Payment and roast-mode fixes

1. `payment_security.sql` was applied and the enabled trigger verified in Supabase project `cpjptqgrfjysebmhqide` on 2026-09-11. Apply it separately to any other deployment database. It protects `profiles.is_premium` against direct browser updates and preserves existing paid accounts.
2. Keep `SUPABASE_KEY` as a backend-only service-role key. Never use it in frontend environment variables.
3. Configure `RAZORPAY_WEBHOOK_SECRET` to match the Razorpay webhook signing secret. Until set, webhook requests return 503 intentionally. The authenticated checkout verification flow remains available.
4. Configure Razorpay to capture payments and send `payment.captured` / `order.paid` to the deployed backend's `/api/payment/webhook`. A localhost URL is not reachable by Razorpay.
5. Local payment keys are test-mode keys. Use the matching live keys only when intentionally going live. The browser receives the correct public key from the order endpoint.
6. Confirm signup email before signing in. A payment does not confirm an email address. Already-paid users should not pay again; retry saved payment verification if checkout returned a payment reference.
7. Supabase Auth's redirect allowlist must include each frontend origin (including `http://localhost:3000` for local Google sign-in).

The previous source contained a hardcoded Razorpay secret. It has been removed; rotate any still-active exposed credential in Razorpay before production use.

Tests: backend `python -m unittest test_payments.py`; frontend `node test-roast.cjs` and `npx tsc --noEmit`.

Roast mode uses browser text-to-speech, account-scoped adult consent, twelve or more lines per category, and a five-line exclusion buffer. A single idle reminder runs after 25 seconds on a player's active turn, excluding dialogs, pending warnings, robot turns and hidden tabs. Actual voice availability depends on the browser and OS.
