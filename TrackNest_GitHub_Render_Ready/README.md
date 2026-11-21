# TrackNest / Expanse Tracker — Django authentication, monthly budgets and email alerts

## Local setup
```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python manage.py makemigrations accounts
python manage.py migrate
python manage.py runserver
```
Open http://127.0.0.1:8000/. Existing sign-in/sign-up and dashboard UI are preserved.

## Budget behavior
The registered user's email is stored in Django's User.email. Transaction records and monthly budget limits are stored per authenticated user in SQLite. When an accepted expense brings this month's spending exactly to the limit, TrackNest blocks subsequent expense records and queues a limit-reached email. An expense that would exceed the limit is rejected and not saved. The alert is sent only once per user/month. The budget may be increased by the user. Budget enforcement applies only to TrackNest records, never external payments.

## Email testing
By default Django uses the console email backend. The alert appears in the `runserver` terminal; **no real email is sent**.

To send real email, configure SMTP credentials via environment variables (do not commit passwords):
```
DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
DJANGO_EMAIL_HOST=smtp.gmail.com
DJANGO_EMAIL_PORT=587
DJANGO_EMAIL_USE_TLS=1
DJANGO_EMAIL_HOST_USER=your-sender@gmail.com
DJANGO_EMAIL_HOST_PASSWORD=your-app-password
DJANGO_DEFAULT_FROM_EMAIL=your-sender@gmail.com
```
For Gmail, use an app password on an eligible account with 2-Step Verification, not your regular Gmail password. In production, use a transactional email provider and a background task queue, rather than sending SMTP in the request callback. Add email verification to ensure addresses belong to registrants before sending alerts.

## Caveats
This is a development starter, not a deployed service. Email delivery, concurrency behavior (especially SQLite), and Django runtime have not been verified here. The email is queued on transaction commit, but the current synchronous callback can still fail after a transaction is saved; production should use an outbox and worker. Income/expense data is saved; dashboard forecasting and AI assistant remain demos. Set DEBUG=0, a strong SECRET_KEY, secure cookies and HTTPS before deployment. Do not assume the registered email is verified.

## Updated interface and administrator reporting
- The Sign In and Create Account screens have a new two-column responsive layout. Technical marketing copy such as “Secure Django REST API & Forecasting” has been removed from the login screen.
- Registered users and saved expenses are already represented by Django's `auth.User` and `accounts.ExpenseTransaction`; SQLite stores records in `db.sqlite3` after migrations. The ZIP intentionally does **not** contain any real user data.
- An administrator can view user counts, saved expense counts, and total expenses in Nrs at **http://127.0.0.1:8000/admin/overview/**. The report includes historical recorded expense amounts across all dates, not just the current month. Income is not counted as an expense. Staff accounts are included in the full accounts total but excluded from the registered-user count.
- The regular Django administration at `/admin/` has searchable user, transaction, profile and monthly budget views. Transaction and budget records are read-only there to avoid bypassing validation and budget rules.
- Users cannot access the admin overview without a staff account. Ordinary user financial APIs still filter to `request.user`.

### Set up the database and admin login
```bash
python manage.py makemigrations accounts
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```
Open the website at `http://127.0.0.1:8000/` and sign up to create user records. Then log into the admin using the superuser account at `/admin/overview/`. The site does not create or ship any fake user accounts.

### Tests
```bash
python manage.py check
python manage.py test accounts
```
These tests verify administrator access, global sums, per-user totals, user data isolation, and budget rejection. Install requirements and run these tests locally; Python syntax checks alone do not prove Django runtime behavior. SQLite transaction locking is not equivalent to PostgreSQL row-level locking under concurrency.

### Preview
`tracknest_auth_design_preview.html` is an optional static browser preview of the redesigned sign-in/sign-up screen. It has no running database or working login by itself. Use the Django server URL to exercise actual authentication.
