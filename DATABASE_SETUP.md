# PostgreSQL setup

The application connects directly to PostgreSQL using psycopg 3. Set
`DATABASE_URL` in the deployment environment or the existing local `.env` file.
The value is read only by the server and must never be exposed to browser code.
The app also accepts `DATABASE_POOL_MAX_SIZE` (default `10`) and `SECRET_KEY`;
set a long, random `SECRET_KEY` for deployments with multiple workers or
instances.

On startup the app creates its PostgreSQL tables and indexes in a single
transaction. This is repeatable and leaves no partial schema if initialization
fails. No historical data migration is performed.

No sample/default user accounts are created. To bootstrap the first
administrator, set `ADMIN_INITIAL_PASSWORD` to a strong password in the local
`.env` file or deployment environment. The account username is fixed to
`Tushar_Borse`; the password is stored as a Werkzeug password hash. The insert
is skipped when an administrator already exists, so restarts never reset its
password. Remove `ADMIN_INITIAL_PASSWORD` after the initial account is created.
Additional staff accounts can then be added through the existing admin UI.

Admin profile pictures use the existing private Supabase Storage bucket with
the API-reported ID `admin-profile-pictures` (the Dashboard may display the
label in uppercase). The application only reads and verifies this bucket; it
never creates or makes a bucket public. Configure `SUPABASE_SERVICE_ROLE_KEY`
with your server-only Supabase secret key (`sb_secret_...`) in `.env` or the
deployment environment. For compatibility, if that variable is unset, the app
uses `SECRET_KEY` as the Storage key only when its value starts with
`sb_secret_`. The existing Flask session `SECRET_KEY` setting is unchanged.
Storage requests use the `apikey` header and never send the new secret key as a
Bearer token. Never put this key in browser code or commit it.

The admin-only `POST /api/admin/profile/storage-diagnostic` endpoint checks
configuration, bucket access and privacy, performs a small test upload,
generates a short-lived signed URL, and removes the test object. Call it with
the authenticated admin session and the `X-Admin-Profile-CSRF` token returned
by `GET /api/admin/profile`. The response reports the failing stage and a
sanitized Supabase error without exposing credentials. The application
re-encodes accepted JPEG, PNG, and WebP uploads to WebP and serves them through
an authenticated admin-only backend endpoint; the bucket is not public.

Install dependencies with `pip install -r requirements.txt`, then run
`python app.py`.
