from flask import Flask, Response, render_template, request, jsonify, session, redirect, url_for, send_file, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape
import os
import io
from io import BytesIO
import re
import uuid
import hashlib
import hmac
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.graphics import renderPDF
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as pdf_canvas
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill
from psycopg import IntegrityError
from PIL import Image, UnidentifiedImageError
from dotenv import load_dotenv

load_dotenv(override=False)

from database import execute, fetch_all, fetch_one, initialize_schema, transaction

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or secrets.token_hex(32)
app.config['INVOICE_STORAGE_PATH'] = os.path.join(app.instance_path, 'private', 'invoices')

FINANCIAL_YEAR_OPTIONS = tuple(
    f'{start_year}-{(start_year + 1) % 100:02d}'
    for start_year in range(2025, 2030)
)

def get_user(user_id):
    return fetch_one('SELECT * FROM "user" WHERE id = %s', (user_id,))


def get_client(client_id):
    return fetch_one('SELECT * FROM client WHERE id = %s', (client_id,))


def get_invoice(invoice_id, include_deleted=False):
    sql = 'SELECT * FROM invoice WHERE id = %s'
    if not include_deleted:
        sql += ' AND deleted_at IS NULL'
    return fetch_one(sql, (invoice_id,))


def get_task(task_id):
    return fetch_one('SELECT * FROM task WHERE id = %s', (task_id,))


def get_or_404(record):
    if record is None:
        from flask import abort
        abort(404)
    return record

REMARK_CATEGORIES = {
    'ITR Return Pending',
    'Documents Pending',
    'Payment Pending',
    'Client Information Required',
    'Other'
}

initialize_schema()

ADMIN_USERNAME = 'Tushar_Borse'
ADMIN_PROFILE_BUCKET = 'admin-profile-pictures'
MAX_ADMIN_AVATAR_BYTES = 5 * 1024 * 1024
ALLOWED_ADMIN_AVATAR_MIMES = {'image/webp'}


def initialize_admin_account():
    initial_password = os.getenv('ADMIN_INITIAL_PASSWORD')
    admin = fetch_one('SELECT id, username FROM "user" WHERE role = %s', ('admin',))
    if admin is None:
        if not initial_password:
            app.logger.warning(
                'Admin account is not initialized. Configure ADMIN_INITIAL_PASSWORD '
                'to create the initial %s account.',
                ADMIN_USERNAME
            )
            return
        if len(initial_password) < 12:
            raise RuntimeError('ADMIN_INITIAL_PASSWORD must contain at least 12 characters.')
        username_conflict = fetch_one(
            'SELECT id FROM "user" WHERE username = %s',
            (ADMIN_USERNAME,)
        )
        if username_conflict:
            raise RuntimeError('The fixed admin username is already assigned to a non-admin account.')
        execute(
            'INSERT INTO "user" (username, password_hash, role, full_name) '
            'VALUES (%s, %s, %s, %s)',
            (ADMIN_USERNAME, generate_password_hash(initial_password), 'admin', 'Tushar Borse')
        )
        admin = fetch_one('SELECT id FROM "user" WHERE username = %s', (ADMIN_USERNAME,))
    elif admin.username != ADMIN_USERNAME:
        username_conflict = fetch_one(
            'SELECT id FROM "user" WHERE username = %s AND id <> %s',
            (ADMIN_USERNAME, admin.id)
        )
        if username_conflict:
            raise RuntimeError('The fixed admin username is already assigned to another account.')
        execute('UPDATE "user" SET username = %s WHERE id = %s', (ADMIN_USERNAME, admin.id))
    execute(
        'INSERT INTO admin_profile (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING',
        (admin.id,)
    )


initialize_admin_account()


def _admin_profile_identity():
    if 'user_id' not in session:
        return None, (jsonify({'error': 'Unauthorized'}), 401)
    user = get_user(session['user_id'])
    if user is None or user.role != 'admin' or user.username != ADMIN_USERNAME:
        return None, (jsonify({'error': 'Admin access required'}), 403)
    return user, None


def _validate_profile_csrf():
    expected = session.get('admin_profile_csrf')
    supplied = request.headers.get('X-Admin-Profile-CSRF')
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def _valid_storage_hostname(hostname):
    if not hostname or len(hostname) > 253:
        return False
    try:
        hostname = hostname.encode('idna').decode('ascii')
    except UnicodeError:
        return False
    if hostname.endswith('.'):
        hostname = hostname[:-1]
    return bool(hostname) and all(
        0 < len(label) <= 63
        and re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?', label)
        for label in hostname.split('.')
    )


def _storage_credentials():
    raw_supabase_url = os.getenv('SUPABASE_URL')
    supabase_url = (raw_supabase_url or '').strip()
    surrounding_whitespace = (
        raw_supabase_url is not None
        and raw_supabase_url != raw_supabase_url.strip()
    )
    surrounding_quotes = (
        len(supabase_url) >= 2
        and supabase_url[0] == supabase_url[-1]
        and supabase_url[0] in ('"', "'")
    )
    if surrounding_quotes:
        supabase_url = supabase_url[1:-1].strip()
    trailing_slash = supabase_url.endswith('/')
    supabase_url = supabase_url.rstrip('/')
    starts_https = supabase_url.lower().startswith('https://')
    url_parts = None
    hostname = None
    port = None
    try:
        url_parts = urllib.parse.urlsplit(supabase_url)
        hostname = url_parts.hostname
        port = url_parts.port
    except ValueError:
        url_parts = None
        hostname = None
        port = None
    hostname_valid = _valid_storage_hostname(hostname)
    url_valid = (
        starts_https
        and url_parts is not None
        and url_parts.scheme.lower() == 'https'
        and hostname_valid
        and url_parts.username is None
        and url_parts.password is None
        and (port is None or 1 <= port <= 65535)
        and url_parts.path in ('', '/')
        and not url_parts.query
        and not url_parts.fragment
        and not any(ord(character) <= 32 or ord(character) == 127 for character in supabase_url)
    )
    if url_valid and url_parts is not None:
        supabase_url = url_parts._replace(scheme='https').geturl()
    service_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '').strip()
    if not service_key:
        secret_key_fallback = os.getenv('SECRET_KEY', '').strip()
        if secret_key_fallback.startswith('sb_secret_'):
            service_key = secret_key_fallback
    if not url_valid or not app.config.get('_SUPABASE_URL_DIAGNOSTIC_LOGGED'):
        logger = app.logger.info if url_valid else app.logger.error
        logger(
            'Supabase Storage URL configuration: present=%s starts_https=%s '
            'hostname_valid=%s surrounding_whitespace=%s surrounding_quotes=%s '
            'trailing_slash_removed=%s',
            raw_supabase_url is not None and bool(raw_supabase_url.strip()),
            starts_https,
            hostname_valid,
            surrounding_whitespace,
            surrounding_quotes,
            trailing_slash,
        )
        app.config['_SUPABASE_URL_DIAGNOSTIC_LOGGED'] = True
    if not url_valid:
        raise RuntimeError(
            'SUPABASE_URL must be configured as an HTTPS URL for private profile image storage.'
        )
    if not service_key:
        raise RuntimeError(
            'SUPABASE_SERVICE_ROLE_KEY is missing or empty, and SECRET_KEY is not a Supabase '
            'secret key. Configure SUPABASE_SERVICE_ROLE_KEY with the sb_secret_... value.'
        )
    if not service_key.startswith('sb_secret_'):
        raise RuntimeError(
            'The configured SUPABASE_SERVICE_ROLE_KEY is not a Supabase secret key '
            '(expected the sb_secret_ prefix).'
        )
    return supabase_url, service_key


def _storage_request(method, path, body=None, content_type='application/json'):
    supabase_url, service_key = _storage_credentials()
    url = f'{supabase_url}/storage/v1/{path}'
    headers = {
        'apikey': service_key,
    }
    if not service_key.startswith('sb_secret_'):
        headers['Authorization'] = f'Bearer {service_key}'
    if body is not None:
        headers['Content-Type'] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, response.read(), response.headers.get('Content-Type', '')
    except urllib.error.HTTPError as error:
        error_body = error.read(2048)
        try:
            payload = json.loads(error_body)
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        detail = next(
            (
                payload.get(field)
                for field in ('message', 'error_description', 'error', 'msg')
                if isinstance(payload.get(field), str) and payload[field].strip()
            ),
            None,
        )
        if detail:
            detail = ' '.join(detail.split())[:300]
            message = f'Supabase Storage returned HTTP {error.code}: {detail}'
        else:
            message = f'Supabase Storage returned HTTP {error.code}.'
        raise RuntimeError(message) from error
    except urllib.error.URLError as error:
        raise RuntimeError(f'Supabase Storage could not be reached: {error.reason}.') from error


def _ensure_private_profile_bucket():
    bucket_path = urllib.parse.quote(ADMIN_PROFILE_BUCKET, safe='')
    _, bucket_bytes, _ = _storage_request('GET', f'bucket/{bucket_path}')
    try:
        bucket = json.loads(bucket_bytes)
    except (TypeError, ValueError) as error:
        raise RuntimeError('Supabase Storage returned invalid bucket metadata.') from error
    if bucket.get('id') != ADMIN_PROFILE_BUCKET:
        raise RuntimeError(
            f'Supabase Storage returned a different bucket than {ADMIN_PROFILE_BUCKET}.'
        )
    if bucket.get('public') is not False:
        raise RuntimeError(f'The existing {ADMIN_PROFILE_BUCKET} bucket must be private.')


def _storage_object_path(object_path):
    return urllib.parse.quote(object_path, safe='/')


def _upload_profile_image(user_id, image_bytes):
    _ensure_private_profile_bucket()
    object_path = f'{user_id}/{uuid.uuid4().hex}.webp'
    _storage_request(
        'POST',
        f'object/{ADMIN_PROFILE_BUCKET}/{_storage_object_path(object_path)}',
        image_bytes,
        'image/webp',
    )
    return object_path


def _create_profile_image_signed_url(object_path):
    body = json.dumps({'expiresIn': 60}).encode('utf-8')
    _, response_bytes, _ = _storage_request(
        'POST',
        f'object/sign/{urllib.parse.quote(ADMIN_PROFILE_BUCKET, safe="")}/'
        f'{_storage_object_path(object_path)}',
        body,
    )
    try:
        response = json.loads(response_bytes)
    except (TypeError, ValueError) as error:
        raise RuntimeError('Supabase Storage returned an invalid signed URL response.') from error
    signed_url = response.get('signedURL') or response.get('signedUrl')
    if not isinstance(signed_url, str) or not signed_url:
        raise RuntimeError('Supabase Storage did not return a signed URL.')
    return signed_url


def _delete_profile_image(object_path):
    if not object_path:
        return
    body = json.dumps({'prefixes': [object_path]}).encode('utf-8')
    _storage_request('DELETE', f'object/{ADMIN_PROFILE_BUCKET}', body)


def _read_profile_image(object_path):
    _storage_credentials()
    _, image_bytes, _ = _storage_request(
        'GET',
        f'object/{ADMIN_PROFILE_BUCKET}/{_storage_object_path(object_path)}',
        content_type='',
    )
    return image_bytes, 'image/webp'


def _normalized_profile_image(file_storage):
    if file_storage is None or not file_storage.filename:
        raise ValueError('Choose a profile picture to upload.')
    content_length = request.content_length
    if content_length and content_length > MAX_ADMIN_AVATAR_BYTES + 128 * 1024:
        raise ValueError('Profile pictures must be 5 MB or smaller.')
    source = file_storage.stream.read(MAX_ADMIN_AVATAR_BYTES + 1)
    if not source or len(source) > MAX_ADMIN_AVATAR_BYTES:
        raise ValueError('Profile pictures must be between 1 byte and 5 MB.')
    try:
        with Image.open(BytesIO(source)) as image:
            if image.format not in ('JPEG', 'PNG', 'WEBP'):
                raise ValueError('Upload a JPEG, PNG, or WebP image.')
            if image.width > 4096 or image.height > 4096:
                raise ValueError('Image dimensions must not exceed 4096 by 4096 pixels.')
            image.load()
            normalized = image.convert('RGBA' if 'A' in image.getbands() else 'RGB')
            output = BytesIO()
            normalized.save(output, format='WEBP', quality=86, method=6)
            result = output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError('The uploaded file is not a valid supported image.') from error
    if len(result) > MAX_ADMIN_AVATAR_BYTES:
        raise ValueError('The processed profile picture exceeds the 5 MB limit.')
    return result


@app.route('/api/admin/profile', methods=['GET', 'PUT'])
def admin_profile():
    admin, error_response = _admin_profile_identity()
    if error_response:
        return error_response

    profile = fetch_one(
        'SELECT email, avatar_object_path FROM admin_profile WHERE user_id = %s',
        (admin.id,)
    )
    if request.method == 'GET':
        csrf_token = session.setdefault('admin_profile_csrf', secrets.token_urlsafe(32))
        response = jsonify({
            'username': ADMIN_USERNAME,
            'email': profile.email if profile else None,
            'contact_number': admin.contact_number or '',
            'avatar_url': url_for('admin_profile_avatar') if profile and profile.avatar_object_path else None,
            'csrf_token': csrf_token,
        })
        response.headers['Cache-Control'] = 'no-store'
        return response

    if not _validate_profile_csrf():
        return jsonify({'error': 'Your profile session expired. Reload the page and try again.'}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) - {'email', 'contact_number'}:
        return jsonify({'error': 'Submit only profile email and contact number fields.'}), 400
    email = data.get('email')
    contact_number = data.get('contact_number')
    if not isinstance(email, str):
        return jsonify({'error': 'Enter a valid email address.'}), 400
    email = email.strip().lower()
    if len(email) > 254 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
        return jsonify({'error': 'Enter a valid email address (maximum 254 characters).'}), 400
    if not isinstance(contact_number, str):
        return jsonify({'error': 'Enter a valid contact number.'}), 400
    digits = re.sub(r'\D', '', contact_number)
    if len(digits) == 12 and digits.startswith('91'):
        digits = digits[2:]
    if not re.fullmatch(r'[6-9][0-9]{9}', digits):
        return jsonify({'error': 'Enter a valid 10-digit Indian mobile number.'}), 400
    try:
        with transaction() as connection:
            connection.execute(
                'UPDATE "user" SET contact_number = %s WHERE id = %s AND role = %s',
                (digits, admin.id, 'admin')
            )
            connection.execute(
                'INSERT INTO admin_profile (user_id, email, updated_at) '
                'VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET '
                'email = EXCLUDED.email, updated_at = EXCLUDED.updated_at',
                (admin.id, email, datetime.utcnow())
            )
    except IntegrityError:
        return jsonify({'error': 'That email address is already associated with another admin profile.'}), 409
    return jsonify({
        'success': True,
        'message': 'Profile details updated.',
        'email': email,
        'contact_number': digits,
    })


@app.route('/api/admin/profile/password', methods=['POST'])
def update_admin_password():
    admin, error_response = _admin_profile_identity()
    if error_response:
        return error_response
    if not _validate_profile_csrf():
        return jsonify({'error': 'Your profile session expired. Reload the page and try again.'}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Submit password details as a JSON object.'}), 400
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    if not isinstance(current_password, str) or not isinstance(new_password, str):
        return jsonify({'error': 'Enter your current and new passwords.'}), 400
    if len(new_password) < 12 or len(new_password) > 128:
        return jsonify({'error': 'New password must be between 12 and 128 characters.'}), 400
    if not any(char.islower() for char in new_password) or \
       not any(char.isupper() for char in new_password) or \
       not any(char.isdigit() for char in new_password):
        return jsonify({'error': 'New password must include uppercase, lowercase, and numeric characters.'}), 400
    current = fetch_one(
        'SELECT password_hash FROM "user" WHERE id = %s AND role = %s AND username = %s',
        (admin.id, 'admin', ADMIN_USERNAME)
    )
    if current is None or not check_password_hash(current.password_hash, current_password):
        return jsonify({'error': 'Current password is incorrect.'}), 403
    if check_password_hash(current.password_hash, new_password):
        return jsonify({'error': 'Choose a new password different from your current password.'}), 400
    execute(
        'UPDATE "user" SET password_hash = %s WHERE id = %s AND role = %s',
        (generate_password_hash(new_password), admin.id, 'admin')
    )
    session.clear()
    session['user_id'] = admin.id
    session['username'] = ADMIN_USERNAME
    session['role'] = 'admin'
    session['admin_profile_csrf'] = secrets.token_urlsafe(32)
    return jsonify({'success': True, 'message': 'Password changed successfully.'})


@app.route('/api/admin/profile/avatar', methods=['GET', 'POST', 'DELETE'])
def admin_profile_avatar():
    admin, error_response = _admin_profile_identity()
    if error_response:
        return error_response
    if request.method != 'GET' and not _validate_profile_csrf():
        return jsonify({'error': 'Your profile session expired. Reload the page and try again.'}), 403

    if request.method == 'GET':
        profile = fetch_one(
            'SELECT avatar_object_path FROM admin_profile WHERE user_id = %s',
            (admin.id,)
        )
        if profile is None or not profile.avatar_object_path:
            return jsonify({'error': 'No profile picture is set.'}), 404
        try:
            image_bytes, content_type = _read_profile_image(profile.avatar_object_path)
        except RuntimeError:
            app.logger.exception('Could not read the private admin profile picture.')
            return jsonify({'error': 'The profile picture is temporarily unavailable.'}), 502
        response = Response(image_bytes, mimetype=content_type or 'image/webp')
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    if request.method == 'POST':
        try:
            image_bytes = _normalized_profile_image(request.files.get('profile_picture'))
            new_path = _upload_profile_image(admin.id, image_bytes)
        except ValueError as error:
            return jsonify({'error': str(error)}), 400
        except RuntimeError as error:
            app.logger.warning('Could not upload the private admin profile picture: %s', error)
            return jsonify({'error': str(error)}), 503
        old_profile = fetch_one(
            'SELECT avatar_object_path FROM admin_profile WHERE user_id = %s',
            (admin.id,)
        )
        try:
            execute(
                'INSERT INTO admin_profile (user_id, avatar_object_path, updated_at) '
                'VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET '
                'avatar_object_path = EXCLUDED.avatar_object_path, updated_at = EXCLUDED.updated_at',
                (admin.id, new_path, datetime.utcnow())
            )
        except Exception:
            try:
                _delete_profile_image(new_path)
            except RuntimeError:
                app.logger.exception('Could not clean up an unreferenced admin profile picture.')
            raise
        if old_profile and old_profile.avatar_object_path:
            try:
                _delete_profile_image(old_profile.avatar_object_path)
            except RuntimeError:
                app.logger.exception('Could not remove the previous admin profile picture.')
        return jsonify({
            'success': True,
            'message': 'Profile picture updated.',
            'avatar_url': url_for('admin_profile_avatar', v=uuid.uuid4().hex),
        })

    profile = fetch_one(
        'SELECT avatar_object_path FROM admin_profile WHERE user_id = %s',
        (admin.id,)
    )
    if profile and profile.avatar_object_path:
        try:
            _delete_profile_image(profile.avatar_object_path)
        except RuntimeError:
            app.logger.exception('Could not remove the admin profile picture from private storage.')
            return jsonify({'error': 'The profile picture could not be removed from storage.'}), 503
    execute(
        'INSERT INTO admin_profile (user_id, avatar_object_path, updated_at) '
        'VALUES (%s, NULL, %s) ON CONFLICT (user_id) DO UPDATE SET '
        'avatar_object_path = NULL, updated_at = EXCLUDED.updated_at',
        (admin.id, datetime.utcnow())
    )
    return jsonify({'success': True, 'message': 'Profile picture removed.'})


@app.route('/api/admin/profile/storage-diagnostic', methods=['POST'])
def admin_profile_storage_diagnostic():
    _, error_response = _admin_profile_identity()
    if error_response:
        return error_response
    if not _validate_profile_csrf():
        return jsonify({'error': 'Your profile session expired. Reload the page and try again.'}), 403

    stage = 'configuration'
    object_path = None
    uploaded = False
    diagnostic_error = None
    cleanup_error = None
    try:
        _storage_credentials()
        stage = 'bucket_access'
        _ensure_private_profile_bucket()
        stage = 'test_upload'
        image = BytesIO()
        Image.new('RGB', (1, 1), (80, 20, 20)).save(image, format='WEBP')
        object_path = f'_diagnostics/{uuid.uuid4().hex}.webp'
        _storage_request(
            'POST',
            f'object/{urllib.parse.quote(ADMIN_PROFILE_BUCKET, safe="")}/'
            f'{_storage_object_path(object_path)}',
            image.getvalue(),
            'image/webp',
        )
        uploaded = True
        stage = 'test_retrieval'
        retrieved_bytes, _ = _read_profile_image(object_path)
        if retrieved_bytes != image.getvalue():
            raise RuntimeError('Supabase Storage returned different bytes for the test image.')
        stage = 'signed_url'
        _create_profile_image_signed_url(object_path)
    except RuntimeError as error:
        diagnostic_error = str(error)
    finally:
        if uploaded and object_path:
            try:
                _delete_profile_image(object_path)
            except RuntimeError as error:
                cleanup_error = str(error)

    if diagnostic_error:
        app.logger.warning('Admin profile Storage diagnostic failed at %s: %s', stage, diagnostic_error)
        return jsonify({
            'success': False,
            'stage': stage,
            'error': diagnostic_error,
            'cleanup_error': cleanup_error,
        }), 503
    if cleanup_error:
        app.logger.error('Admin profile Storage diagnostic object cleanup failed: %s', cleanup_error)
        return jsonify({
            'success': False,
            'stage': 'cleanup',
            'error': cleanup_error,
        }), 503
    return jsonify({
        'success': True,
        'bucket': ADMIN_PROFILE_BUCKET,
        'private': True,
        'checks': {
            'configuration': True,
            'bucket_access': True,
            'private_bucket': True,
            'test_upload': True,
            'test_retrieval': True,
            'signed_url': True,
            'test_object_removed': True,
        },
    })


@app.before_request
def enforce_active_account():
    user_id = session.get('user_id')
    if user_id is None or request.endpoint in ('login', 'logout', 'static'):
        return None

    current_user = get_user(user_id)
    if current_user is None or not current_user.is_active:
        session.clear()
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Unauthorized'}), 401
        return redirect(url_for('login'))
    return None

# Routes
@app.route('/')
def index():
    if 'user_id' in session:
        return render_template('index.html')
    business = invoice_business_details()
    contact = {
        'address': INVOICE_SHOP_ADDRESS,
        'mobile': business['mobile'],
        'email': business['email']
    }
    return render_template(
        'home.html',
        company_name=business['name'],
        contact=contact,
        current_year=datetime.now().year
    )

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json()
        username = (data.get('username') or '').strip()
        password = data.get('password')
        user_type = data.get('user_type')
        
        user = fetch_one('SELECT * FROM "user" WHERE username = %s', (username,))
        
        if user and user.is_active and check_password_hash(user.password_hash, password):
            if (user_type == 'admin' and user.role == 'admin') or \
               (user_type == 'staff' and user.role == 'staff'):
                session['user_id'] = user.id
                session['username'] = user.username
                session['role'] = user.role
                return jsonify({
                    'success': True,
                    'role': user.role,
                    'user_id': user.id
                })
        
        return jsonify({'success': False, 'message': 'Invalid credentials'})

    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('index.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


def parse_optional_client_id(value):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise ValueError('Select a valid referring client')
    if isinstance(value, str):
        value = value.strip()
        if not re.fullmatch(r'[0-9]+', value):
            raise ValueError('Select a valid referring client')
    elif not isinstance(value, int):
        raise ValueError('Select a valid referring client')
    client_id = int(value)
    if client_id < 1:
        raise ValueError('Select a valid referring client')
    return client_id


def staff_remark_client_ids(user):
    if user.role != 'staff':
        return set()
    return {
        row.client_id for row in fetch_all(
            'SELECT DISTINCT client_id FROM task WHERE assigned_to = %s AND client_id IS NOT NULL',
            (user.id,)
        )
    }


def can_manage_client_remarks(user, client, assigned_task_client_ids=None):
    if user.role == 'admin':
        return True
    if user.role != 'staff':
        return False
    if client.assigned_to == user.id:
        return True
    if assigned_task_client_ids is None:
        return fetch_one(
            'SELECT 1 FROM task WHERE client_id = %s AND assigned_to = %s LIMIT 1',
            (client.id, user.id)
        ) is not None
    return client.id in assigned_task_client_ids


@app.route('/api/clients', methods=['GET', 'POST'])
def clients():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    if request.method == 'GET':
        current_user = get_user(session['user_id'])
        if current_user is None or current_user.role not in ('admin', 'staff'):
            return jsonify({'error': 'Unauthorized'}), 403
        clients = fetch_all(
            'SELECT c.*, r.client_name AS referrer_name FROM client c '
            'LEFT JOIN client r ON r.id = c.referred_by_id ORDER BY c.client_name, c.id'
        )
        assigned_task_client_ids = staff_remark_client_ids(current_user)
        
        client_list = []
        for client in clients:
            client_data = {
                'id': client.id,
                'client_name': client.client_name,
                'email': client.email,
                'pan_number': client.pan_number,
                'phone': client.phone,
                'status': client.status,
                'created_at': client.created_at.strftime('%Y-%m-%d %H:%M'),
                'referred_by_id': client.referred_by_id,
                'referred_by_name': client.referrer_name
            }
            if current_user.role == 'admin':
                assigned_user = get_user(client.assigned_to) if client.assigned_to else None
                client_data['assigned_to'] = assigned_user.username if assigned_user else 'Unassigned'
            else:
                client_data['can_manage_remarks'] = can_manage_client_remarks(
                    current_user, client, assigned_task_client_ids
                )
            client_list.append(client_data)
        return jsonify({'clients': client_list})
    
    elif request.method == 'POST':
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({'error': 'Submit client details as a JSON object'}), 400

        current_user = get_user(session['user_id'])
        if current_user is None:
            session.clear()
            return jsonify({'error': 'Your session has expired. Please sign in again.'}), 401

        client_name = data.get('client_name')
        email = data.get('email')
        pan_number = data.get('pan_number')
        password = data.get('password')
        phone = data.get('phone')
        if not isinstance(client_name, str) or not client_name.strip():
            return jsonify({'error': 'Client name is required'}), 400
        if not isinstance(phone, str) or not phone.strip():
            return jsonify({'error': 'Contact number is required'}), 400
        if email is not None and not isinstance(email, str):
            return jsonify({'error': 'Enter a valid email address (maximum 120 characters)'}), 400
        if pan_number is not None and not isinstance(pan_number, str):
            return jsonify({'error': 'Enter a valid PAN in the format AAAAA9999A'}), 400
        if password is not None and not isinstance(password, str):
            return jsonify({'error': 'Password must be 100 characters or fewer'}), 400

        client_name = client_name.strip()
        email = (email.strip().lower() or None) if email is not None else None
        pan_number = (pan_number.strip().upper() or None) if pan_number is not None else None
        password = (password.strip() or None) if password is not None else None
        phone = re.sub(r'\D', '', phone)
        if len(client_name) > 100:
            return jsonify({'error': 'Client name must be 100 characters or fewer'}), 400
        if email is not None and (
            len(email) > 120 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email)
        ):
            return jsonify({'error': 'Enter a valid email address (maximum 120 characters)'}), 400
        if pan_number is not None and not re.fullmatch(r'[A-Z]{5}[0-9]{4}[A-Z]', pan_number):
            return jsonify({'error': 'Enter a valid PAN in the format AAAAA9999A'}), 400
        if password is not None and len(password) > 100:
            return jsonify({'error': 'Password must be 100 characters or fewer'}), 400
        if not re.fullmatch(r'[6-9][0-9]{9}', phone):
            return jsonify({'error': 'Enter a valid 10-digit Indian mobile number'}), 400

        status = data.get('status', 'pending')
        if status not in ('pending', 'found', 'not_found'):
            return jsonify({'error': 'Select a valid client status'}), 400

        try:
            referred_by_id = parse_optional_client_id(data.get('referred_by_id'))
        except ValueError as error:
            return jsonify({'error': str(error)}), 400
        if referred_by_id is not None:
            referrer = get_client(referred_by_id)
            if referrer is None:
                return jsonify({'error': 'The selected referring client does not exist'}), 400
            if current_user.role == 'staff' and referrer.assigned_to != current_user.id:
                return jsonify({'error': 'Select one of your assigned clients as the referrer'}), 403

        if pan_number is not None and fetch_one(
            'SELECT id FROM client WHERE UPPER(pan_number) = %s LIMIT 1',
            (pan_number,)
        ):
            return jsonify({'error': 'A client with this PAN number already exists'}), 409
        if fetch_one('SELECT id FROM client WHERE phone = %s LIMIT 1', (phone,)):
            return jsonify({'error': 'A client with this contact number already exists'}), 409

        assigned_to = data.get('assigned_to') or None
        if current_user.role == 'staff':
            assigned_to = current_user.id
        elif assigned_to is not None:
            try:
                assigned_to = int(assigned_to)
            except (TypeError, ValueError):
                return jsonify({'error': 'Select an active staff account'}), 400
            assigned_staff = fetch_one(
                'SELECT id FROM "user" WHERE id = %s AND role = %s AND is_active = TRUE',
                (assigned_to, 'staff')
            )
            if assigned_staff is None:
                return jsonify({'error': 'Select an active staff account'}), 400
        elif current_user.role != 'admin':
            return jsonify({'error': 'You do not have permission to add clients'}), 403

        try:
            new_client = execute(
                'INSERT INTO client (client_name, email, pan_number, password, phone, status, '
                'assigned_to, referred_by_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) '
                'RETURNING *',
                (client_name, email, pan_number, password, phone, status, assigned_to, referred_by_id)
            )
        except IntegrityError:
            if pan_number is not None and fetch_one(
                'SELECT id FROM client WHERE UPPER(pan_number) = %s LIMIT 1', (pan_number,)
            ):
                return jsonify({'error': 'A client with this PAN number already exists'}), 409
            if fetch_one('SELECT id FROM client WHERE phone = %s LIMIT 1', (phone,)):
                return jsonify({'error': 'A client with this contact number already exists'}), 409
            app.logger.exception('Client creation failed due to a database integrity error.')
            return jsonify({'error': 'The client could not be saved because of a database constraint'}), 409

        assigned_user = get_user(new_client.assigned_to) if new_client.assigned_to else None
        referrer = get_client(new_client.referred_by_id) if new_client.referred_by_id else None
        client_data = {
            'id': new_client.id,
            'client_name': new_client.client_name,
            'email': new_client.email,
            'pan_number': new_client.pan_number,
            'phone': new_client.phone,
            'status': new_client.status,
            'created_at': new_client.created_at.strftime('%Y-%m-%d %H:%M'),
            'referred_by_id': new_client.referred_by_id,
            'referred_by_name': referrer.client_name if referrer else None
        }
        if current_user.role == 'admin':
            client_data['assigned_to'] = assigned_user.username if assigned_user else 'Unassigned'
        else:
            client_data['can_manage_remarks'] = can_manage_client_remarks(
                current_user, new_client
            )
        return jsonify({
            'success': True,
            'message': 'Client added successfully',
            'client': client_data
        }), 201


@app.route('/api/clients/year-wise')
def year_wise_clients():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    current_user = get_user(session['user_id'])
    if current_user is None:
        session.clear()
        return jsonify({'error': 'Your session has expired. Please sign in again.'}), 401

    clients = fetch_all('SELECT * FROM client ORDER BY client_name, id')
    assigned_task_client_ids = staff_remark_client_ids(current_user)
    client_ids = [client.id for client in clients]
    clients_by_id = {client.id: client for client in clients}
    assigned_users = {}
    if current_user.role == 'admin':
        assigned_users = {
            user.id: user.username
            for user in fetch_all(
                'SELECT id, username FROM "user" WHERE id = ANY(%s)',
                ([client.assigned_to for client in clients if client.assigned_to],)
            )
        } if clients else {}
    invoices = fetch_all(
        'SELECT * FROM invoice WHERE client_id = ANY(%s) AND deleted_at IS NULL',
        (client_ids,)
    ) if client_ids else []

    totals_by_client = {}
    totals_by_client_and_year = {}
    for invoice in invoices:
        client_totals = totals_by_client.setdefault(
            invoice.client_id, {'total_invoices': 0, 'total_invoice_amount': Decimal('0.00')}
        )
        client_totals['total_invoices'] += 1
        client_totals['total_invoice_amount'] += invoice_total(invoice)

        if invoice.date is None:
            continue
        invoice_date = invoice.date
        if invoice_date.tzinfo is not None:
            invoice_date = invoice_date.astimezone(timezone.utc).replace(tzinfo=None)
        local_invoice_date = invoice_date + timedelta(hours=5, minutes=30)
        financial_year = financial_year_for_date(local_invoice_date)
        year_totals = totals_by_client_and_year.setdefault(
            (invoice.client_id, financial_year),
            {'total_invoices': 0, 'total_invoice_amount': Decimal('0.00')}
        )
        year_totals['total_invoices'] += 1
        year_totals['total_invoice_amount'] += invoice_total(invoice)

    def client_row(client, financial_year, totals):
        row = {
            'id': client.id,
            'client_name': client.client_name,
            'email': client.email or '',
            'pan_number': client.pan_number or '',
            'phone': client.phone,
            'status': client.status,
            'total_invoices': totals['total_invoices'],
            'total_invoice_amount': float(totals['total_invoice_amount']),
            'financial_year': financial_year
        }
        if current_user.role == 'admin':
            row['assigned_to'] = assigned_users.get(client.assigned_to, 'Unassigned')
        else:
            row['can_manage_remarks'] = can_manage_client_remarks(
                current_user, client, assigned_task_client_ids
            )
        return row

    clients_by_year = {}
    year_counts = {}
    for (client_id, financial_year), totals in totals_by_client_and_year.items():
        client = clients_by_id[client_id]
        clients_by_year.setdefault(financial_year, []).append(
            client_row(client, f'FY {financial_year}', totals)
        )
        year_counts[financial_year] = year_counts.get(financial_year, 0) + 1

    financial_years = []
    for financial_year in FINANCIAL_YEAR_OPTIONS:
        financial_years.append({
            'value': financial_year,
            'label': f'FY {financial_year}',
            'client_count': year_counts.get(financial_year, 0)
        })

    for year_clients in clients_by_year.values():
        year_clients.sort(key=lambda item: (item['client_name'].casefold(), item['id']))

    all_years = []
    for client in clients:
        totals = totals_by_client.get(
            client.id, {'total_invoices': 0, 'total_invoice_amount': Decimal('0.00')}
        )
        all_years.append(client_row(client, 'All Financial Years', totals))

    return jsonify({
        'financial_years': financial_years,
        'all_years': all_years,
        'clients_by_year': clients_by_year
    })


@app.route('/api/clients/<int:client_id>', methods=['GET', 'PUT', 'DELETE'])
def client_operations(client_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    current_user = get_user(session['user_id'])
    if current_user is None or current_user.role not in ('admin', 'staff'):
        return jsonify({'error': 'Unauthorized'}), 403
    if request.method == 'DELETE' and current_user.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    client = fetch_one(
        'SELECT c.*, r.client_name AS referrer_name FROM client c '
        'LEFT JOIN client r ON r.id = c.referred_by_id WHERE c.id = %s',
        (client_id,)
    )
    if client is None:
        return jsonify({'error': 'Client not found'}), 404

    if request.method == 'GET':
        return jsonify({
            'id': client.id,
            'client_name': client.client_name,
            'email': client.email,
            'pan_number': client.pan_number,
            'phone': client.phone,
            'status': client.status,
            'referred_by_id': client.referred_by_id,
            'referred_by_name': client.referrer_name
        })
    
    if request.method == 'PUT':
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({'error': 'Submit client details as a JSON object'}), 400
        if current_user.role == 'staff' and 'assigned_to' in data:
            return jsonify({'error': 'Only administrators can change client assignments'}), 403
        if 'referred_by_id' in data:
            try:
                referred_by_id = parse_optional_client_id(data.get('referred_by_id'))
            except ValueError as error:
                return jsonify({'error': str(error)}), 400
            if referred_by_id is not None:
                referrer = get_client(referred_by_id)
                if referrer is None:
                    return jsonify({'error': 'The selected referring client does not exist'}), 400
                if referred_by_id == client.id:
                    return jsonify({'error': 'A client cannot refer themselves'}), 400
            client.referred_by_id = referred_by_id
        assigned_to = data.get('assigned_to', client.assigned_to)
        if current_user.role == 'admin' and not assigned_to:
            assigned_to = None
        if current_user.role == 'admin' and assigned_to is not None:
            try:
                assigned_to = int(assigned_to)
            except (TypeError, ValueError):
                return jsonify({'error': 'Select an active staff account'}), 400
            assigned_staff = fetch_one(
                'SELECT id FROM "user" WHERE id = %s AND role = %s AND is_active = TRUE',
                (assigned_to, 'staff')
            )
            if assigned_staff is None:
                return jsonify({'error': 'Select an active staff account'}), 400

        pan_number = client.pan_number
        if 'client_name' in data:
            client_name = data['client_name']
            if not isinstance(client_name, str) or not client_name.strip() or len(client_name.strip()) > 100:
                return jsonify({'error': 'Client name is required and must be 100 characters or fewer'}), 400
            client.client_name = client_name.strip()
        if 'email' in data:
            email = data['email']
            if email is not None and not isinstance(email, str):
                return jsonify({'error': 'Enter a valid email address (maximum 120 characters)'}), 400
            email = (email.strip().lower() or None) if email is not None else None
            if email is not None and (
                len(email) > 120 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email)
            ):
                return jsonify({'error': 'Enter a valid email address (maximum 120 characters)'}), 400
            client.email = email
        if 'pan_number' in data:
            pan_number = data['pan_number']
            if pan_number is not None and not isinstance(pan_number, str):
                return jsonify({'error': 'Enter a valid PAN in the format AAAAA9999A'}), 400
            pan_number = (pan_number.strip().upper() or None) if pan_number is not None else None
            if pan_number is not None and not re.fullmatch(r'[A-Z]{5}[0-9]{4}[A-Z]', pan_number):
                return jsonify({'error': 'Enter a valid PAN in the format AAAAA9999A'}), 400
            if pan_number is not None and fetch_one(
                'SELECT id FROM client WHERE UPPER(pan_number) = %s AND id <> %s LIMIT 1',
                (pan_number, client.id)
            ):
                return jsonify({'error': 'A client with this PAN number already exists'}), 409
            client.pan_number = pan_number
        if 'phone' in data:
            phone = data['phone']
            if not isinstance(phone, str):
                return jsonify({'error': 'Enter a valid 10-digit Indian mobile number'}), 400
            phone = re.sub(r'\D', '', phone)
            if not re.fullmatch(r'[6-9][0-9]{9}', phone):
                return jsonify({'error': 'Enter a valid 10-digit Indian mobile number'}), 400
            if fetch_one(
                'SELECT id FROM client WHERE phone = %s AND id <> %s LIMIT 1',
                (phone, client.id)
            ):
                return jsonify({'error': 'A client with this contact number already exists'}), 409
            client.phone = phone
        if 'status' in data:
            status = data['status']
            if status not in ('pending', 'found', 'not_found'):
                return jsonify({'error': 'Select a valid client status'}), 400
            client.status = status
        if 'password' in data:
            password = data['password']
            if not isinstance(password, str) or len(password) > 100:
                return jsonify({'error': 'Password must be 100 characters or fewer'}), 400
            client.password = password
        fields = {
            'client_name': client.client_name,
            'email': client.email,
            'pan_number': client.pan_number,
            'phone': client.phone,
            'status': client.status,
            'password': client.password,
            'assigned_to': assigned_to,
            'referred_by_id': client.referred_by_id,
        }
        try:
            execute(
                'UPDATE client SET client_name = %s, email = %s, pan_number = %s, phone = %s, '
                'status = %s, password = %s, assigned_to = %s, referred_by_id = %s, '
                'updated_at = %s WHERE id = %s',
                (fields['client_name'], fields['email'], fields['pan_number'], fields['phone'],
                 fields['status'], fields['password'], fields['assigned_to'],
                 fields['referred_by_id'], datetime.utcnow(), client.id)
            )
        except IntegrityError:
            if pan_number is not None and fetch_one(
                'SELECT id FROM client WHERE UPPER(pan_number) = %s AND id <> %s LIMIT 1',
                (pan_number, client.id)
            ):
                return jsonify({'error': 'A client with this PAN number already exists'}), 409
            if fetch_one(
                'SELECT id FROM client WHERE phone = %s AND id <> %s LIMIT 1',
                (client.phone, client.id)
            ):
                return jsonify({'error': 'A client with this contact number already exists'}), 409
            app.logger.exception('Client update failed due to a database integrity error.')
            return jsonify({'error': 'The client could not be updated because of a database constraint'}), 409
        return jsonify({'success': True, 'message': 'Client updated successfully'})
    
    elif request.method == 'DELETE':
        with transaction() as connection:
            connection.execute('DELETE FROM client_remark WHERE client_id = %s', (client.id,))
            connection.execute(
                'UPDATE client SET referred_by_id = NULL WHERE referred_by_id = %s',
                (client.id,)
            )
            connection.execute('DELETE FROM client WHERE id = %s', (client.id,))
        return jsonify({'success': True, 'message': 'Client deleted successfully'})

@app.route('/api/clients/<int:client_id>/remark', methods=['GET', 'POST', 'PUT'])
def client_remark(client_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    current_user = get_user(session['user_id'])
    if current_user is None or current_user.role not in ('admin', 'staff'):
        return jsonify({'error': 'Unauthorized'}), 403

    client = get_client(client_id)
    if client is None:
        return jsonify({'error': 'Client not found'}), 404
    if not can_manage_client_remarks(current_user, client):
        return jsonify({'error': 'You can only manage remarks for your assigned clients'}), 403

    if request.method == 'GET':
        sql = (
            'SELECT cr.*, u.username AS author_username, u.full_name AS author_full_name '
            'FROM client_remark cr JOIN "user" u ON u.id = cr.staff_id '
            'WHERE cr.client_id = %s'
        )
        params = [client.id]
        if current_user.role == 'staff':
            sql += ' AND (cr.author_role = %s OR cr.staff_id = %s)'
            params.extend(('admin', current_user.id))
        saved_remarks = fetch_all(sql + ' ORDER BY cr.created_at, cr.id', params)
        remarks_data = [
            client_remark_json(
                saved_remark,
                SimpleNamespace(username=saved_remark.author_username,
                                full_name=saved_remark.author_full_name)
            )
            for saved_remark in saved_remarks
        ]
        latest_own_remark = next(
            (remark for remark in reversed(remarks_data)
             if remark['author_id'] == current_user.id),
            None
        )
        return jsonify({
            'client_name': client.client_name,
            'pan_number': client.pan_number,
            'remarks': remarks_data,
            'remark': latest_own_remark
        })

    data = request.get_json(silent=True) or {}
    category = data.get('category')
    remark_text = data.get('remark')
    if not isinstance(category, str) or category not in REMARK_CATEGORIES:
        return jsonify({'error': 'Select a valid remark category'}), 400
    if not isinstance(remark_text, str) or not remark_text.strip():
        return jsonify({'error': 'Remark text is required'}), 400
    remark_text = remark_text.strip()

    if request.method == 'POST':
        saved_remark = execute(
            'INSERT INTO client_remark (client_id, staff_id, author_role, category, remark) '
            'VALUES (%s, %s, %s, %s, %s) RETURNING *',
            (client.id, current_user.id, current_user.role, category, remark_text)
        )
    else:
        saved_remark = fetch_one(
            'SELECT * FROM client_remark WHERE client_id = %s AND staff_id = %s '
            'ORDER BY updated_at DESC, id DESC LIMIT 1',
            (client.id, current_user.id)
        )
        if saved_remark is None:
            saved_remark = execute(
                'INSERT INTO client_remark (client_id, staff_id, author_role, category, remark) '
                'VALUES (%s, %s, %s, %s, %s) RETURNING *',
                (client.id, current_user.id, current_user.role, category, remark_text)
            )
        else:
            saved_remark = execute(
                'UPDATE client_remark SET category = %s, remark = %s, updated_at = %s '
                'WHERE id = %s RETURNING *',
                (category, remark_text, datetime.utcnow(), saved_remark.id)
            )

    return jsonify({
        'success': True,
        'remark': client_remark_json(saved_remark, current_user)
    }), 201 if request.method == 'POST' else 200


@app.route(
    '/api/clients/<int:client_id>/remark/<int:remark_id>',
    methods=['PUT']
)
def update_client_remark(client_id, remark_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    current_user = get_user(session['user_id'])
    if current_user is None or current_user.role not in ('admin', 'staff'):
        return jsonify({'error': 'Unauthorized'}), 403
    client = get_client(client_id)
    if client is None:
        return jsonify({'error': 'Client not found'}), 404
    if not can_manage_client_remarks(current_user, client):
        return jsonify({'error': 'You can only manage remarks for your assigned clients'}), 403
    saved_remark = fetch_one(
        'SELECT * FROM client_remark WHERE id = %s AND client_id = %s',
        (remark_id, client.id)
    )
    if saved_remark is None:
        return jsonify({'error': 'Remark not found'}), 404
    if saved_remark.staff_id != current_user.id:
        return jsonify({'error': 'You can only edit remarks you created'}), 403

    data = request.get_json(silent=True) or {}
    category = data.get('category')
    remark_text = data.get('remark')
    if not isinstance(category, str) or category not in REMARK_CATEGORIES:
        return jsonify({'error': 'Select a valid remark category'}), 400
    if not isinstance(remark_text, str) or not remark_text.strip():
        return jsonify({'error': 'Remark text is required'}), 400

    saved_remark = execute(
        'UPDATE client_remark SET category = %s, remark = %s, updated_at = %s '
        'WHERE id = %s RETURNING *',
        (category, remark_text.strip(), datetime.utcnow(), saved_remark.id)
    )
    return jsonify({
        'success': True,
        'remark': client_remark_json(saved_remark, current_user)
    })


def client_remark_json(saved_remark, author):
    created_at = saved_remark.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    created_at = created_at.astimezone(
        timezone(timedelta(hours=5, minutes=30))
    )
    updated_at = saved_remark.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    updated_at = updated_at.astimezone(
        timezone(timedelta(hours=5, minutes=30))
    )
    return {
        'id': saved_remark.id,
        'author_id': saved_remark.staff_id,
        'author_name': (author.full_name or author.username) if author else 'Unknown',
        'author_role': saved_remark.author_role,
        'category': saved_remark.category,
        'text': saved_remark.remark,
        'created_at': created_at.strftime('%Y-%m-%d %H:%M'),
        'updated_at': updated_at.strftime('%Y-%m-%d %H:%M'),
        'remark_date': created_at.strftime('%Y-%m-%d'),
        'remark_time': created_at.strftime('%H:%M')
    }


@app.route('/api/remarks')
def get_remarks():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    current_user = get_user(session['user_id'])
    if current_user is None:
        return jsonify({'error': 'Unauthorized'}), 401
    if current_user.role not in ('admin', 'staff'):
        return jsonify({'error': 'Unauthorized'}), 403

    sql = (
        'SELECT cr.*, c.id AS c_id, c.client_name, c.pan_number, '
        'u.id AS u_id, u.username AS u_username, u.full_name AS u_full_name '
        'FROM client_remark cr JOIN client c ON c.id = cr.client_id '
        'JOIN "user" u ON u.id = cr.staff_id'
    )
    params = []
    if current_user.role == 'staff':
        sql += (
            ' WHERE (c.assigned_to = %s OR EXISTS '
            '(SELECT 1 FROM task t WHERE t.client_id = c.id AND t.assigned_to = %s)) '
            'AND (cr.author_role = %s OR cr.staff_id = %s)'
        )
        params.extend((current_user.id, current_user.id, 'admin', current_user.id))
    if current_user.role == 'admin':
        sql += ' ORDER BY cr.created_at, cr.id'
    else:
        sql += ' ORDER BY cr.created_at DESC, cr.id DESC'
    remarks = fetch_all(sql, params)
    invoice_numbers_by_client = {}
    if current_user.role == 'admin':
        for invoice in fetch_all(
            'SELECT client_id, invoice_number FROM invoice WHERE deleted_at IS NULL '
            'ORDER BY date, id'
        ):
            invoice_numbers_by_client.setdefault(invoice.client_id, []).append(
                invoice.invoice_number
            )
    remarks_data = []
    for row in remarks:
        saved_remark = SimpleNamespace(
            id=row.id, client_id=row.client_id, staff_id=row.staff_id,
            author_role=row.author_role, category=row.category, remark=row.remark,
            created_at=row.created_at, updated_at=row.updated_at
        )
        client = SimpleNamespace(
            id=row.c_id, client_name=row.client_name, pan_number=row.pan_number
        )
        staff_member = SimpleNamespace(
            id=row.u_id, username=row.u_username, full_name=row.u_full_name
        )
        created_at = saved_remark.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        created_at = created_at.astimezone(
            timezone(timedelta(hours=5, minutes=30))
        )
        updated_at = saved_remark.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        updated_at = updated_at.astimezone(
            timezone(timedelta(hours=5, minutes=30))
        )
        remark_data = {
            'client_id': client.id,
            'client_name': client.client_name,
            'pan_number': client.pan_number,
            'category': saved_remark.category,
            'remark': saved_remark.remark,
            'updated_at': updated_at.strftime('%Y-%m-%d %H:%M'),
            'created_at': created_at.strftime('%Y-%m-%d %H:%M'),
            'remark_date': created_at.strftime('%Y-%m-%d'),
            'remark_time': created_at.strftime('%H:%M'),
            'author_id': saved_remark.staff_id,
            'author_name': staff_member.full_name or staff_member.username,
            'author_role': saved_remark.author_role
        }
        if current_user.role == 'admin':
            role_label = 'Admin' if saved_remark.author_role == 'admin' else 'Staff'
            remark_data['staff_name'] = (
                f'{staff_member.full_name or staff_member.username} ({role_label})'
            )
            remark_data['invoice_numbers'] = invoice_numbers_by_client.get(
                client.id, []
            )
        remarks_data.append(remark_data)

    return jsonify({'remarks': remarks_data})


def current_admin_for_notes():
    if 'user_id' not in session:
        return None, (jsonify({'error': 'Unauthorized'}), 401)
    current_user = get_user(session['user_id'])
    if current_user is None or current_user.role != 'admin':
        return None, (jsonify({'error': 'Admin access required'}), 403)
    return current_user, None


def user_note_json(note):
    created_at = note.created_at
    updated_at = note.updated_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return {
        'id': note.id,
        'title': note.title,
        'content': note.content,
        'created_at': created_at.isoformat(),
        'updated_at': updated_at.isoformat()
    }


@app.route('/api/admin/notes', methods=['GET', 'POST'])
def admin_notes():
    current_user, error_response = current_admin_for_notes()
    if error_response:
        return error_response

    if request.method == 'GET':
        notes = fetch_all(
            'SELECT * FROM user_note WHERE user_id = %s ORDER BY updated_at DESC, id DESC',
            (current_user.id,)
        )
        return jsonify({'notes': [user_note_json(note) for note in notes]})

    note = execute(
        'INSERT INTO user_note (user_id) VALUES (%s) RETURNING *',
        (current_user.id,)
    )
    return jsonify({'note': user_note_json(note)}), 201


@app.route('/api/admin/notes/<int:note_id>', methods=['PUT', 'DELETE'])
def admin_note(note_id):
    current_user, error_response = current_admin_for_notes()
    if error_response:
        return error_response

    note = fetch_one(
        'SELECT * FROM user_note WHERE id = %s AND user_id = %s',
        (note_id, current_user.id)
    )
    if note is None:
        return jsonify({'error': 'Note not found'}), 404

    if request.method == 'DELETE':
        execute('DELETE FROM user_note WHERE id = %s', (note.id,))
        return jsonify({'success': True})

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Submit note details as a JSON object'}), 400
    title = data.get('title')
    content = data.get('content')
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
        return jsonify({'error': 'Note title is required and must be 200 characters or fewer'}), 400
    if not isinstance(content, str) or len(content) > 50000:
        return jsonify({'error': 'Note content must be text with 50,000 characters or fewer'}), 400

    note = execute(
        'UPDATE user_note SET title = %s, content = %s, updated_at = %s '
        'WHERE id = %s RETURNING *',
        (title.strip(), content, datetime.utcnow(), note.id)
    )
    return jsonify({'note': user_note_json(note)})


@app.route('/api/staff')
def get_staff():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    current_user = get_user(session['user_id'])
    if current_user is None:
        return jsonify({'error': 'Unauthorized'}), 401
    if current_user.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    staff = fetch_all('SELECT * FROM "user" WHERE role = %s ORDER BY id', ('staff',))
    staff_list = [{
        'id': user.id,
        'username': user.username,
        'email': user.username,
        'full_name': user.full_name or user.username,
        'contact_number': user.contact_number,
        'is_active': user.is_active
    } for user in staff]
    return jsonify({'staff': staff_list})

def validate_staff_email(email):
    return bool(re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email))

@app.route('/api/staff/<int:staff_id>', methods=['PUT', 'DELETE'])
def delete_staff(staff_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    current_user = get_user(session['user_id'])
    if current_user is None:
        return jsonify({'error': 'Unauthorized'}), 401
    if current_user.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    staff_member = fetch_one(
        'SELECT * FROM "user" WHERE id = %s AND role = %s',
        (staff_id, 'staff')
    )
    if staff_member is None:
        return jsonify({'error': 'Staff user not found'}), 404
    if request.method == 'PUT':
        data = request.get_json(silent=True) or {}
        email = staff_member.username
        full_name = data.get('full_name', staff_member.full_name or staff_member.username)
        contact_number = data.get('contact_number', staff_member.contact_number)

        if 'email' in data:
            if not isinstance(data['email'], str) or not validate_staff_email(data['email'].strip()):
                return jsonify({'error': 'Enter a valid staff email address'}), 400
            email = data['email'].strip().lower()
            if fetch_one(
                'SELECT id FROM "user" WHERE username = %s AND id <> %s',
                (email, staff_id)
            ):
                return jsonify({'error': 'Email address is already in use'}), 409
        if not isinstance(full_name, str) or not full_name.strip():
            return jsonify({'error': 'Staff full name is required'}), 400
        if not isinstance(contact_number, str):
            return jsonify({'error': 'Contact number must be text'}), 400
        if 'is_active' in data and not isinstance(data['is_active'], bool):
            return jsonify({'error': 'Account status must be active or inactive'}), 400

        password = data.get('password')
        confirm_password = data.get('confirm_password')
        if password is not None:
            if not isinstance(password, str) or len(password) < 8:
                return jsonify({'error': 'Password must be at least 8 characters'}), 400
            if password != confirm_password:
                return jsonify({'error': 'Passwords do not match'}), 400

        password_hash = (
            generate_password_hash(password) if password is not None
            else staff_member.password_hash
        )
        is_active = data.get('is_active', staff_member.is_active)
        execute(
            'UPDATE "user" SET username = %s, full_name = %s, contact_number = %s, '
            'is_active = %s, password_hash = %s WHERE id = %s',
            (email, full_name.strip(), contact_number.strip(), is_active, password_hash, staff_id)
        )
        return jsonify({'success': True, 'message': 'Staff account updated successfully'})

    if fetch_one('SELECT 1 FROM client WHERE assigned_to = %s LIMIT 1', (staff_id,)) or \
       fetch_one('SELECT 1 FROM task WHERE assigned_to = %s LIMIT 1', (staff_id,)):
        return jsonify({
            'error': "Reassign this staff member's clients and tasks before deleting the account"
        }), 409
    
    with transaction() as connection:
        connection.execute('DELETE FROM client_remark WHERE staff_id = %s', (staff_id,))
        connection.execute('DELETE FROM "user" WHERE id = %s', (staff_id,))
    return jsonify({'success': True, 'message': 'Staff user deleted successfully'})

def invoice_client_details(invoice):
    client = get_client(invoice.client_id)
    return {
        'name': invoice.client_name or (client.client_name if client else 'N/A'),
        'email': invoice.client_email or (client.email if client and client.email else 'N/A'),
        'pan': invoice.client_pan_number or (client.pan_number if client and client.pan_number else 'N/A'),
        'phone': invoice.client_phone or (client.phone if client else 'N/A')
    }

def invoice_allowed_for_user(invoice, user):
    if user.role == 'admin':
        return True
    client = get_client(invoice.client_id)
    return user.role == 'staff' and client is not None and client.assigned_to == user.id


def invoice_business_details():
    return {
        'name': os.getenv('TAXSECURE_COMPANY_NAME', 'Tushar Borse And Co.').strip(),
        'address': os.getenv('TAXSECURE_COMPANY_ADDRESS', '').strip(),
        'mobile': os.getenv('TAXSECURE_COMPANY_MOBILE', '').strip(),
        'email': os.getenv('TAXSECURE_COMPANY_EMAIL', '').strip(),
        'bank_name': os.getenv('TAXSECURE_BANK_NAME', '').strip(),
        'account_holder': os.getenv('TAXSECURE_BANK_ACCOUNT_HOLDER', '').strip(),
        'account_number': os.getenv('TAXSECURE_BANK_ACCOUNT_NUMBER', '').strip(),
        'ifsc': os.getenv('TAXSECURE_BANK_IFSC', '').strip(),
        'upi_id': os.getenv('TAXSECURE_UPI_ID', '').strip(),
        'logo_path': os.getenv('TAXSECURE_LOGO_PATH', '').strip()
        or os.path.join(app.static_folder, 'images', 'tushar-borse-and-co-logo.jpeg')
    }


INVOICE_PAYMENT_DETAILS = (
    ('Bank Name', 'IDBI Bank'),
    ('Account Holder', 'Tushar Borse And Co.'),
    ('Account Number', '2387102000004541'),
    ('Account Type', 'Current Account'),
    ('IFSC Code', 'IBKL0002387'),
    ('Branch', 'Not specified'),
)
INVOICE_UPI_ACCOUNTS = (
    ('HDFC Bank', 'tusharborse75-4@okhdfcbank', 'tbhdfcqr-invoice.png'),
    ('SBI Bank', 'tusharborseandco@oksbi', 'tbsbiqr-invoice.png'),
)
INVOICE_PAYMENT_APPS = (
    ('GPay', 'gpay-invoice.png'),
    ('PhonePe', 'phonepe-invoice.png'),
    ('Paytm', 'paytm-invoice.png'),
)
INVOICE_SHOP_ADDRESS = (
    'Shop No. 102, Om Sai Avenue, Swaraj Road, Opp. Krystal One, MIDC, '
    'Chikhali, Pimpri-Chinchwad, Maharashtra – 411062.'
)


def draw_business_logo(canvas, x, y, width, height, logo_path=None):
    logo_path = logo_path or invoice_business_details()['logo_path']
    if not logo_path or not os.path.isfile(logo_path):
        return False
    try:
        logo = ImageReader(logo_path)
        image_width, image_height = logo.getSize()
        scale = min(width / image_width, height / image_height)
        drawn_width = image_width * scale
        drawn_height = image_height * scale
        canvas.drawImage(
            logo,
            x + (width - drawn_width) / 2,
            y + (height - drawn_height) / 2,
            width=drawn_width,
            height=drawn_height,
            mask='auto'
        )
    except (OSError, ValueError):
        app.logger.exception('Configured business logo could not be read.')
        return False
    return True


def invoice_total(invoice):
    subtotal = Decimal(str(invoice.amount))
    discount = Decimal(str(invoice.discount_amount or 0))
    return (subtotal - discount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculate_invoice_discount(subtotal, discount_type, discount_value):
    try:
        subtotal = Decimal(str(subtotal))
        value = Decimal(str(discount_value or 0).strip() or '0')
        if not subtotal.is_finite() or subtotal <= 0:
            raise ValueError('Enter a valid invoice amount greater than zero')
        if not value.is_finite() or value < 0:
            raise ValueError('Discount cannot be negative')
        value = value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError, AttributeError) as error:
        if isinstance(error, ValueError):
            raise
        raise ValueError('Enter a valid discount value') from error

    if discount_type not in ('percentage', 'fixed'):
        raise ValueError('Select a percentage or fixed amount discount')
    if discount_type == 'percentage':
        if value > 100:
            raise ValueError('Percentage discount cannot exceed 100%')
        discount_amount = (subtotal * value / Decimal('100')).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
    else:
        value = value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if value > subtotal:
            raise ValueError('Fixed discount cannot exceed the invoice subtotal')
        discount_amount = value

    return discount_type, value, discount_amount


def invoice_discount_label(invoice):
    value = Decimal(str(invoice.discount_value or 0))
    if invoice.discount_type == 'fixed':
        return f'Discount (Fixed INR {value:,.2f})'
    return f'Discount ({format(value.normalize(), "f")}%)'


def invoice_received(invoice):
    return Decimal(str(invoice.received_amount or 0)).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )


def number_to_words_indian(number):
    number = int(number)
    ones = (
        'Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
        'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
        'Seventeen', 'Eighteen', 'Nineteen'
    )
    tens = (
        '', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety'
    )

    def under_thousand(value):
        words = []
        if value >= 100:
            words.extend((ones[value // 100], 'Hundred'))
            value %= 100
        if value >= 20:
            words.append(tens[value // 10])
            value %= 10
        if value:
            words.append(ones[value])
        return ' '.join(words)

    if number == 0:
        return 'Zero'
    parts = []
    for divisor, label in ((10000000, 'Crore'), (100000, 'Lakh'), (1000, 'Thousand')):
        group, number = divmod(number, divisor)
        if group:
            parts.extend((under_thousand(group), label))
    if number:
        parts.append(under_thousand(number))
    return ' '.join(parts)


def amount_in_words(amount):
    value = Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    rupees = int(value)
    paise = int((value - rupees) * 100)
    words = f'{number_to_words_indian(rupees)} Rupees'
    if paise:
        words += f' and {number_to_words_indian(paise)} Paise'
    return words + ' Only'


def build_invoice_pdf(invoice):
    client = invoice_client_details(invoice)
    business = invoice_business_details()
    subtotal = Decimal(str(invoice.amount)).quantize(Decimal('0.01'))
    discount_amount = Decimal(str(invoice.discount_amount or 0)).quantize(Decimal('0.01'))
    total = invoice_total(invoice)
    received = invoice_received(invoice)
    balance = max(total - received, Decimal('0.00'))

    teal = colors.HexColor('#171717')
    primary = colors.HexColor('#C90016')
    mint = colors.HexColor('#FAF1F2')
    border = colors.HexColor('#E8E8E8')
    muted = colors.HexColor('#777777')
    ink = colors.HexColor('#202020')
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='InvoiceCompany', parent=styles['Heading1'], fontName='Helvetica-Bold',
        fontSize=19, leading=23, textColor=teal, spaceAfter=3
    ))
    styles.add(ParagraphStyle(
        name='InvoiceTitle', parent=styles['Heading1'], fontName='Helvetica-Bold',
        fontSize=21, leading=24, alignment=2, textColor=primary, spaceAfter=3
    ))
    styles.add(ParagraphStyle(
        name='InvoiceBody', parent=styles['BodyText'], fontName='Helvetica',
        fontSize=9, leading=13, textColor=ink
    ))
    styles.add(ParagraphStyle(
        name='InvoiceMuted', parent=styles['BodyText'], fontName='Helvetica',
        fontSize=8, leading=11, textColor=muted
    ))
    styles.add(ParagraphStyle(
        name='InvoiceMicro', parent=styles['BodyText'], fontName='Helvetica',
        fontSize=6, leading=7, alignment=1, textColor=muted
    ))
    styles.add(ParagraphStyle(
        name='InvoiceSection', parent=styles['Heading3'], fontName='Helvetica-Bold',
        fontSize=9, leading=12, textColor=teal, spaceBefore=0, spaceAfter=2
    ))
    styles.add(ParagraphStyle(
        name='InvoiceTableHeader', parent=styles['BodyText'], fontName='Helvetica-Bold',
        fontSize=8, leading=11, textColor=colors.white
    ))

    def para(value, style='InvoiceBody', allow_markup=False):
        text = str(value or '—')
        return Paragraph(text if allow_markup else escape(text), styles[style])

    def rich_para(label, value, style='InvoiceBody'):
        return para(f'<b>{escape(label)}</b> {escape(str(value or "—"))}', style, allow_markup=True)

    buffer = BytesIO()
    page_width, page_height = A4
    left_margin = 18 * mm
    right_margin = 18 * mm
    usable_width = page_width - left_margin - right_margin

    def draw_footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(border)
        canvas.setLineWidth(.6)
        canvas.line(left_margin, 14 * mm, page_width - right_margin, 14 * mm)
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(muted)
        canvas.drawString(left_margin, 10 * mm, 'Thank you for choosing our professional services.')
        canvas.drawRightString(page_width - right_margin, 10 * mm, f'Page {document.page}')
        canvas.restoreState()

    document = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=right_margin, leftMargin=left_margin,
        topMargin=8 * mm, bottomMargin=20 * mm,
        title=f'Invoice {invoice.invoice_number}', author=business['name']
    )
    company_lines = [para(business['name'], 'InvoiceCompany')]
    for detail in (business['address'], business['mobile'], business['email']):
        if detail:
            company_lines.append(para(detail, 'InvoiceMuted'))
    company_cell = company_lines
    if business['logo_path'] and os.path.isfile(business['logo_path']):
        try:
            logo = Image(
                business['logo_path'], width=33 * mm, height=22 * mm,
                kind='proportional'
            )
            company_cell = Table(
                [[logo, company_lines]],
                colWidths=[35 * mm, usable_width * .40]
            )
        except (OSError, ValueError):
            app.logger.exception('Configured invoice logo could not be read.')

    header_meta = [
        para('TAX INVOICE', 'InvoiceTitle'),
        rich_para('Invoice No.', invoice.invoice_number, 'InvoiceMuted'),
        rich_para('Date:', invoice.date.strftime('%d %b %Y'), 'InvoiceMuted'),
        para('Original for Recipient', 'InvoiceMuted')
    ]
    header = Table([[company_cell, header_meta]], colWidths=[usable_width * .62, usable_width * .38])
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('LINEBELOW', (0, 0), (-1, -1), 2, primary)
    ]))

    bill_rows = [
        [para('BILL TO', 'InvoiceSection'), para('INVOICE DETAILS', 'InvoiceSection')],
        [para(client['name']), rich_para('Invoice No.:', invoice.invoice_number)],
        [rich_para('Phone:', client['phone']), rich_para('Invoice Date:', invoice.date.strftime('%d %b %Y'))],
        [rich_para('Email:', client['email']), rich_para('Payment:', invoice.status.title())],
        [rich_para('PAN:', client['pan']), rich_para('Approval:', (invoice.workflow_status or 'pending_review').replace('_', ' ').title())]
    ]
    bill = Table(bill_rows, colWidths=[usable_width * .5, usable_width * .5])
    bill.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), mint),
        ('BOX', (0, 0), (-1, -1), .6, border),
        ('INNERGRID', (0, 0), (-1, -1), .35, border),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 9),
        ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5)
    ]))

    service_rows = [
        [para('SERVICE DESCRIPTION', 'InvoiceTableHeader'), para('QTY', 'InvoiceTableHeader'),
         para('AMOUNT (INR)', 'InvoiceTableHeader')],
        [para(invoice.service_description), para('1'), para(f'{subtotal:,.2f}')]
    ]
    services = Table(service_rows, colWidths=[usable_width * .64, usable_width * .12, usable_width * .24])
    services.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), teal),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), .5, border),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 9),
        ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7)
    ]))

    summary = Table([
        [para('Subtotal'), para(f'INR {subtotal:,.2f}')],
        [para(invoice_discount_label(invoice)), para(f'-INR {discount_amount:,.2f}')],
        [para('Grand Total'), para(f'INR {total:,.2f}')],
        [para('Received Amount'), para(f'INR {received:,.2f}')],
        [para('Balance Due'), para(f'INR {balance:,.2f}')]
    ], colWidths=[usable_width * .32, usable_width * .24], hAlign='RIGHT')
    summary.setStyle(TableStyle([
        ('BACKGROUND', (0, 2), (-1, 2), mint),
        ('BACKGROUND', (0, 4), (-1, 4), mint),
        ('LINEABOVE', (0, 2), (-1, 2), 1, primary),
        ('LINEABOVE', (0, 4), (-1, 4), .7, border),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4)
    ]))

    payment_rows = [[para(label, 'InvoiceMuted'), para(value)] for label, value in INVOICE_PAYMENT_DETAILS]
    payment_table = Table(
        [[para('IDBI Bank Account', 'InvoiceSection'), '']] + payment_rows,
        colWidths=[27 * mm, 43 * mm]
    )
    payment_table.setStyle(TableStyle([
        ('SPAN', (0, 0), (1, 0)),
        ('BACKGROUND', (0, 0), (-1, 0), mint),
        ('BACKGROUND', (0, 1), (0, -1), mint),
        ('BOX', (0, 0), (-1, -1), .5, border),
        ('INNERGRID', (0, 0), (-1, -1), .35, border),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5)
    ]))

    qr_cards = []
    qr_card_width = (usable_width - 74 * mm) / 2
    for bank_name, upi_id, filename in INVOICE_UPI_ACCOUNTS:
        qr_path = os.path.join(app.static_folder, 'images', filename)
        qr_image = Image(qr_path, width=32 * mm, height=32 * mm, kind='proportional')
        payment_app_images = [
            Image(
                os.path.join(app.static_folder, 'images', app_filename),
                width=8 * mm, height=6 * mm, kind='proportional'
            )
            for _, app_filename in INVOICE_PAYMENT_APPS
        ]
        payment_app_names = [
            para(app_name, 'InvoiceMicro')
            for app_name, _ in INVOICE_PAYMENT_APPS
        ]
        payment_app_row = Table(
            [payment_app_images, payment_app_names],
            colWidths=[(qr_card_width - 6 * mm) / 3] * 3,
            style=TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0)
            ])
        )
        qr_cards.append(Table(
            [
                [para(bank_name, 'InvoiceSection')],
                [qr_image],
                [payment_app_row],
                [para(upi_id, 'InvoiceMuted')]
            ],
            colWidths=[qr_card_width],
            style=TableStyle([
                ('BOX', (0, 0), (-1, -1), .5, border),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3)
            ])
        ))
    qr_grid = Table(
        [[qr_cards[0], qr_cards[1]]],
        colWidths=[qr_card_width] * 2
    )
    qr_grid.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0)
    ]))
    payment_content = Table(
        [[payment_table, qr_grid]],
        colWidths=[74 * mm, usable_width - 74 * mm]
    )
    payment_content.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0)
    ]))

    signature_path = os.path.join(app.static_folder, 'images', 'tbsign-invoice.png')
    stamp_path = os.path.join(app.static_folder, 'images', 'tbstamp-invoice.png')
    signature_image = Image(signature_path, width=46 * mm, height=12 * mm, kind='proportional')
    stamp_image = Image(stamp_path, width=23 * mm, height=23 * mm, kind='proportional')
    authorization = Table(
        [
            [para('Authorised Signature', 'InvoiceSection'), para('Company Stamp', 'InvoiceSection')],
            [signature_image, stamp_image],
            [para(business['name'], 'InvoiceMuted'), '']
        ],
        colWidths=[48 * mm, 27 * mm],
        style=TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('SPAN', (0, 2), (1, 2)),
            ('LEFTPADDING', (0, 0), (-1, -1), 2),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3)
        ])
    )
    invoice_closing = Table(
        [[
            [para('SHOP ADDRESS', 'InvoiceSection'), para(INVOICE_SHOP_ADDRESS.replace(' – ', ' - '), 'InvoiceMuted')],
            [para('For ' + business['name'], 'InvoiceSection'), authorization]
        ]],
        colWidths=[usable_width * .46, usable_width * .54]
    )
    invoice_closing.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), .5, border),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5)
    ]))

    story = [
        header, Spacer(1, 1 * mm), bill, Spacer(1, 1 * mm),
        services, Spacer(1, 1 * mm), summary, Spacer(1, 1 * mm),
        rich_para('Amount in Words:', amount_in_words(total), 'InvoiceMuted'),
        Spacer(1, 1 * mm), para('PAYMENT DETAILS', 'InvoiceSection'), payment_content,
        Spacer(1, 1 * mm), invoice_closing
    ]
    document.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buffer.getvalue()


def save_approved_invoice_pdf(invoice):
    pdf_bytes = build_invoice_pdf(invoice)
    filename = f'{uuid.uuid4().hex}.pdf'
    storage_path = app.config['INVOICE_STORAGE_PATH']
    os.makedirs(storage_path, mode=0o700, exist_ok=True)
    path = os.path.join(storage_path, filename)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as pdf_file:
            pdf_file.write(pdf_bytes)
    except Exception:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        raise
    invoice.pdf_filename = filename
    invoice.pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    return pdf_bytes, path


def get_invoice_pdf(invoice):
    filename = invoice.pdf_filename or ''
    if re.fullmatch(r'[a-f0-9]{32}\.pdf', filename):
        path = os.path.join(app.config['INVOICE_STORAGE_PATH'], filename)
        try:
            with open(path, 'rb') as pdf_file:
                pdf_bytes = pdf_file.read()
            if invoice.pdf_sha256 and hashlib.sha256(pdf_bytes).hexdigest() != invoice.pdf_sha256:
                raise ValueError('The stored approved invoice PDF failed its integrity check.')
            return pdf_bytes
        except FileNotFoundError:
            if invoice.workflow_status == 'approved' and invoice.pdf_sha256:
                raise ValueError('The approved invoice PDF is missing from secure storage.')
    return build_invoice_pdf(invoice)


def normalize_whatsapp_number(phone):
    digits = re.sub(r'\D', '', phone or '')
    if len(digits) == 10:
        digits = '91' + digits
    elif len(digits) == 11 and digits.startswith('0'):
        digits = '91' + digits[1:]
    if not 10 <= len(digits) <= 15:
        raise ValueError('The client phone number is not a valid WhatsApp number.')
    return digits


def invoice_whatsapp_recipient(invoice):
    client = get_client(invoice.client_id)
    if client is None:
        raise ValueError('The invoice client is no longer available.')
    return normalize_whatsapp_number(client.phone)


def whatsapp_cloud_is_configured():
    return bool(os.getenv('WHATSAPP_ACCESS_TOKEN') and os.getenv('WHATSAPP_PHONE_NUMBER_ID'))


def whatsapp_api_request(url, token, body, content_type, timeout=25):
    request_object = urllib.request.Request(
        url, data=body, headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': content_type
        }, method='POST'
    )
    try:
        with urllib.request.urlopen(request_object, timeout=timeout) as response:
            response_body = response.read()
        return json.loads(response_body.decode('utf-8'))
    except urllib.error.HTTPError as error:
        response_body = error.read().decode('utf-8', errors='replace')
        try:
            message = json.loads(response_body).get('error', {}).get('message', '')
        except (json.JSONDecodeError, AttributeError):
            message = ''
        raise RuntimeError(message or f'WhatsApp API returned HTTP {error.code}.') from error
    except urllib.error.URLError as error:
        raise RuntimeError(f'WhatsApp API connection failed: {error.reason}') from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError('WhatsApp API returned an unreadable response.') from error


def send_invoice_pdf_via_whatsapp(invoice, pdf_bytes):
    token = os.getenv('WHATSAPP_ACCESS_TOKEN')
    phone_number_id = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
    version = os.getenv('WHATSAPP_GRAPH_API_VERSION', 'v21.0')
    if not token or not phone_number_id:
        raise RuntimeError('WhatsApp Cloud API is not configured.')
    if not re.fullmatch(r'v[0-9]+\.[0-9]+', version):
        raise RuntimeError('WHATSAPP_GRAPH_API_VERSION must use the format vNN.N.')

    recipient = invoice_whatsapp_recipient(invoice)
    base_url = f'https://graph.facebook.com/{version}/{phone_number_id}'
    boundary = f'----TaxSecure{uuid.uuid4().hex}'
    filename = f'{invoice.invoice_number}.pdf'
    multipart_body = b''.join((
        f'--{boundary}\r\nContent-Disposition: form-data; name="messaging_product"\r\n\r\nwhatsapp\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/pdf\r\n\r\n'.encode(),
        pdf_bytes,
        f'\r\n--{boundary}--\r\n'.encode()
    ))
    media_response = whatsapp_api_request(
        f'{base_url}/media', token, multipart_body, f'multipart/form-data; boundary={boundary}'
    )
    media_id = media_response.get('id')
    if not media_id:
        raise RuntimeError('WhatsApp did not return an uploaded document ID.')

    total = invoice_total(invoice)
    received = invoice_received(invoice)
    balance = max(total - received, Decimal('0.00'))
    message = (
        f'Dear {invoice.client_name},\n\n'
        f'Greetings from {invoice_business_details()["name"]}.\n\n'
        f'Please find attached your invoice {invoice.invoice_number} for the services provided.\n\n'
        f'Total Amount: INR {total:,.2f}\n'
        f'Received Amount: INR {received:,.2f}\n'
        f'Balance Amount: INR {balance:,.2f}\n\n'
        f'Thank you for choosing our services.\n\n'
        f'Regards,\n{invoice_business_details()["name"]}'
    )
    message_response = whatsapp_api_request(
        f'{base_url}/messages', token,
        json.dumps({
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': recipient,
            'type': 'document',
            'document': {
                'id': media_id,
                'caption': message,
                'filename': filename
            }
        }).encode('utf-8'),
        'application/json'
    )
    messages = message_response.get('messages') or []
    if not messages or not messages[0].get('id'):
        raise RuntimeError('WhatsApp did not confirm acceptance of the invoice message.')
    return messages[0]['id']


def invoice_json(invoice):
    client = invoice_client_details(invoice)
    total = invoice_total(invoice)
    received = invoice_received(invoice)
    return {
        'id': invoice.id,
        'invoice_number': invoice.invoice_number,
        'client_id': invoice.client_id,
        'client_name': client['name'],
        'client_email': client['email'],
        'client_pan_number': client['pan'],
        'client_phone': client['phone'],
        'service_description': invoice.service_description,
        'amount': float(invoice.amount),
        'subtotal': float(invoice.amount),
        'discount_type': invoice.discount_type or 'percentage',
        'discount_value': float(invoice.discount_value or 0),
        'discount_amount': float(invoice.discount_amount or 0),
        'discount_label': invoice_discount_label(invoice),
        'total': float(total),
        'received_amount': float(received),
        'balance_amount': float(max(total - received, Decimal('0.00'))),
        'date': invoice.date.strftime('%Y-%m-%d'),
        'status': invoice.status,
        'workflow_status': invoice.workflow_status or 'approved',
        'delivery_status': invoice.delivery_status or 'legacy_unknown',
        'approved_at': invoice.approved_at.isoformat() if invoice.approved_at else None,
        'sent_at': invoice.sent_at.isoformat() if invoice.sent_at else None,
        'delivery_error': invoice.delivery_error
    }


def assessment_year_for(date):
    financial_year_start = date.year if date.month >= 4 else date.year - 1
    assessment_year_start = financial_year_start + 1
    return f'{assessment_year_start}-{(assessment_year_start + 1) % 100:02d}'


def financial_year_for_date(date):
    financial_year_start = date.year if date.month >= 4 else date.year - 1
    return f'{financial_year_start}-{(financial_year_start + 1) % 100:02d}'


def parse_report_financial_year(value):
    if value == 'all':
        return None
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}', value):
        raise ValueError('Select a valid financial year')
    start_year, end_year = (int(part) for part in value.split('-'))
    if end_year != (start_year + 1) % 100:
        raise ValueError('Select a valid financial year')
    return start_year


def referral_report_rows(search_term='', financial_year_start=None):
    sql = (
        'SELECT referred.id AS referred_id, referred.client_name AS referred_name, '
        'referred.created_at, referrer.id AS referrer_id, referrer.client_name AS referrer_name '
        'FROM client referred JOIN client referrer ON referred.referred_by_id = referrer.id'
    )
    conditions = []
    params = []
    if search_term:
        search_pattern = f'%{search_term}%'
        conditions.append('(referred.client_name ILIKE %s OR referrer.client_name ILIKE %s)')
        params.extend((search_pattern, search_pattern))
    if financial_year_start is not None:
        india_offset = timedelta(hours=5, minutes=30)
        start_utc = datetime(financial_year_start, 4, 1) - india_offset
        end_utc = datetime(financial_year_start + 1, 4, 1) - india_offset
        conditions.extend(('referred.created_at >= %s', 'referred.created_at < %s'))
        params.extend((start_utc, end_utc))

    india_timezone = timezone(timedelta(hours=5, minutes=30))
    rows = []
    if conditions:
        sql += ' WHERE ' + ' AND '.join(conditions)
    for row in fetch_all(sql + ' ORDER BY referred.created_at DESC, referred.id', params):
        created_at = row.created_at
        if created_at is None:
            continue
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        local_date = created_at.astimezone(india_timezone)
        rows.append({
            'referrer_id': row.referrer_id,
            'referrer_name': row.referrer_name,
            'referred_client_id': row.referred_id,
            'referred_client_name': row.referred_name,
            'referral_date': local_date.strftime('%Y-%m-%d'),
            'financial_year': financial_year_for_date(local_date)
        })
    return rows


def referral_report_payload(search_term='', financial_year_start=None):
    rows = referral_report_rows(search_term, financial_year_start)
    referrals_by_client = {}
    for row in rows:
        referrals_by_client.setdefault(row['referrer_id'], {
            'client_name': row['referrer_name'],
            'referral_count': 0
        })['referral_count'] += 1
    for row in rows:
        row['referral_count'] = referrals_by_client[row['referrer_id']]['referral_count']
    most_referrals = sorted(
        referrals_by_client.values(),
        key=lambda item: (-item['referral_count'], item['client_name'].casefold())
    )
    referrals_by_year = {}
    for row in rows:
        referrals_by_year[row['financial_year']] = (
            referrals_by_year.get(row['financial_year'], 0) + 1
        )
    return {
        'referrals': rows,
        'summary': {
            'total_referring_clients': len(referrals_by_client),
            'total_referred_clients': len(rows),
            'most_referrals_by_client': most_referrals[0] if most_referrals else None,
            'financial_year_referrals': [
                {'financial_year': year, 'referral_count': count}
                for year, count in sorted(
                    referrals_by_year.items(), reverse=True
                )
            ]
        }
    }


def report_invoice_query(financial_year_start):
    sql = (
        'SELECT i.id, i.invoice_number, i.date, i.client_id, i.client_name, i.client_phone, '
        'i.amount, i.fees, i.received_amount, i.status, c.client_name AS current_client_name, '
        'c.phone AS current_client_phone FROM invoice i '
        'LEFT JOIN client c ON c.id = i.client_id WHERE i.deleted_at IS NULL'
    )
    params = []
    if financial_year_start is not None:
        india_offset = timedelta(hours=5, minutes=30)
        start_utc = datetime(financial_year_start, 4, 1) - india_offset
        end_utc = datetime(financial_year_start + 1, 4, 1) - india_offset
        sql += ' AND i.date >= %s AND i.date < %s'
        params.extend((start_utc, end_utc))
    return fetch_all(sql + ' ORDER BY i.date, i.id', params)


def report_invoice_rows(financial_year_start):
    for row in report_invoice_query(financial_year_start):
        taxable = Decimal(str(row.amount or 0)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        gst = Decimal(str(row.fees or 0)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        total = (taxable + gst).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        received = Decimal(str(row.received_amount or 0)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        yield {
            'id': row.id,
            'invoice_number': row.invoice_number or '',
            'invoice_date': row.date,
            'client_id': row.client_id,
            'client_name': row.current_client_name or row.client_name or 'N/A',
            'contact_number': row.current_client_phone or row.client_phone or '',
            'taxable': taxable,
            'gst': gst,
            'total': total,
            'received': received,
            'pending': total - received,
            'payment_status': (
                'Paid' if total > 0 and received >= total else
                'Partially Paid' if received > 0 else
                'Unpaid'
            )
        }


def report_data_summary(financial_year_start):
    summary = {
        'invoice_count': 0,
        'total_invoice_amount': Decimal('0.00'),
        'total_gst': Decimal('0.00'),
        'total_paid_amount': Decimal('0.00'),
        'total_pending_amount': Decimal('0.00'),
        'clients': {}
    }
    for row in report_invoice_rows(financial_year_start):
        summary['invoice_count'] += 1
        summary['total_invoice_amount'] += row['total']
        summary['total_gst'] += row['gst']
        summary['total_paid_amount'] += row['received']
        client = summary['clients'].setdefault(row['client_id'], {
            'client_name': row['client_name'],
            'contact_number': row['contact_number'],
            'invoice_count': 0,
            'total_invoice_amount': Decimal('0.00')
        })
        client['invoice_count'] += 1
        client['total_invoice_amount'] += row['total']
    summary['total_pending_amount'] = (
        summary['total_invoice_amount'] - summary['total_paid_amount']
    )
    return summary


def report_remark_rows(financial_year_start):
    invoice_where = 'deleted_at IS NULL'
    invoice_params = []
    if financial_year_start is not None:
        india_offset = timedelta(hours=5, minutes=30)
        start_utc = datetime(financial_year_start, 4, 1) - india_offset
        end_utc = datetime(financial_year_start + 1, 4, 1) - india_offset
        invoice_where += ' AND date >= %s AND date < %s'
        invoice_params.extend((start_utc, end_utc))

    invoice_numbers_by_client = {}
    for row in fetch_all(
        'SELECT client_id, invoice_number FROM invoice WHERE ' + invoice_where +
        ' ORDER BY date, id', invoice_params
    ):
        invoice_numbers_by_client.setdefault(row.client_id, []).append(row.invoice_number)

    remarks_sql = (
        'SELECT cr.*, c.id AS c_id, c.client_name, u.full_name, u.username '
        'FROM client_remark cr JOIN client c ON c.id = cr.client_id '
        'JOIN "user" u ON u.id = cr.staff_id'
    )
    if financial_year_start is not None:
        remarks_sql += (
            ' WHERE EXISTS (SELECT 1 FROM invoice i WHERE i.client_id = c.id AND ' +
            invoice_where.replace('deleted_at', 'i.deleted_at').replace('date', 'i.date') +
            ')'
        )

    rows = []
    india_timezone = timezone(timedelta(hours=5, minutes=30))
    for row in fetch_all(remarks_sql + ' ORDER BY cr.updated_at, cr.id', invoice_params):
        updated_at = row.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        updated_at = updated_at.astimezone(india_timezone)
        rows.append({
            'client_id': row.c_id,
            'client_name': row.client_name,
            'invoice_numbers': invoice_numbers_by_client.get(row.c_id, []),
            'staff_name': row.full_name or row.username,
            'category': row.category,
            'remark': row.remark,
            'remark_date': updated_at.strftime('%Y-%m-%d'),
            'remark_time': updated_at.strftime('%H:%M')
        })
    return rows


def report_financial_year_label(financial_year_start):
    return 'All Financial Years' if financial_year_start is None else (
        f'FY {financial_year_start}-{(financial_year_start + 1) % 100:02d}'
    )


def report_generated_at():
    return datetime.now(timezone.utc).astimezone(
        timezone(timedelta(hours=5, minutes=30))
    )


def report_currency(value):
    return f'INR {value:,.2f}'


def report_pdf(financial_year_start, summary, remarks):
    buffer = BytesIO()
    page_width, page_height = landscape(A4)
    margin = 30
    canvas = pdf_canvas.Canvas(buffer, pagesize=landscape(A4), pageCompression=1)
    year_label = report_financial_year_label(financial_year_start)
    generated_at = report_generated_at()
    business = invoice_business_details()
    canvas.setTitle(f'{business["name"]} Report - {year_label}')
    canvas.setAuthor(business['name'])
    canvas.setSubject(f'Invoice report for {year_label}')

    column_widths = [110, 58, 135, 75, 92, 86, 86, 68]
    headers = [
        'Invoice Number', 'Date', 'Client Name', 'Contact',
        'Invoice Amount', 'Paid Amount', 'Pending Amount', 'Status'
    ]
    table_width = sum(column_widths)
    table_left = (page_width - table_width) / 2
    table_top = page_height - 169
    row_height = 22
    page_number = 0

    def footer():
        canvas.setStrokeColor(colors.HexColor('#D6E8E4'))
        canvas.line(margin, 27, page_width - margin, 27)
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#637A78'))
        canvas.drawString(margin, 15, f'{business["name"]} | {year_label}')
        canvas.drawRightString(page_width - margin, 15, f'Page {page_number}')

    def start_page(first_page=False):
        nonlocal page_number
        if page_number:
            footer()
            canvas.showPage()
        page_number += 1
        canvas.setFillColor(colors.HexColor('#181818'))
        canvas.rect(0, page_height - 76, page_width, 76, fill=1, stroke=0)
        draw_business_logo(canvas, margin, page_height - 72, 100, 67, business['logo_path'])
        canvas.setFillColor(colors.white)
        canvas.setFont('Helvetica', 9)
        canvas.drawRightString(
            page_width - margin, page_height - 31, 'INVOICE & CLIENT REPORT'
        )
        canvas.setFillColor(colors.HexColor('#263746'))
        canvas.setFont('Helvetica-Bold', 13)
        canvas.drawString(margin, page_height - 96, year_label)
        canvas.setFont('Helvetica', 9)
        canvas.drawRightString(
            page_width - margin, page_height - 96,
            f'Generated: {generated_at:%d %b %Y %H:%M} IST'
        )
        if first_page:
            metrics = [
                ('Total Invoices', str(summary['invoice_count'])),
                ('Total Clients', str(len(summary['clients']))),
                ('Invoice Amount', report_currency(summary['total_invoice_amount'])),
                ('GST', report_currency(summary['total_gst'])),
                ('Paid Amount', report_currency(summary['total_paid_amount'])),
                ('Pending Amount', report_currency(summary['total_pending_amount']))
            ]
            box_gap = 8
            box_width = (page_width - 2 * margin - box_gap * (len(metrics) - 1)) / len(metrics)
            box_y = page_height - 139
            for index, (label, value) in enumerate(metrics):
                x = margin + index * (box_width + box_gap)
                canvas.setFillColor(colors.HexColor('#EFF8F6'))
                canvas.roundRect(x, box_y, box_width, 34, 5, fill=1, stroke=0)
                canvas.setFillColor(colors.HexColor('#176B65'))
                canvas.setFont('Helvetica-Bold', 8)
                canvas.drawString(x + 7, box_y + 21, label)
                canvas.setFillColor(colors.HexColor('#263746'))
                canvas.setFont('Helvetica-Bold', 9)
                canvas.drawString(x + 7, box_y + 8, value)
        draw_table_header(table_top)

    def draw_table_header(y):
        canvas.setFillColor(colors.HexColor('#176B65'))
        canvas.rect(table_left, y - row_height, table_width, row_height, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont('Helvetica-Bold', 7)
        x = table_left
        for header, width in zip(headers, column_widths):
            canvas.drawString(x + 4, y - 14, header)
            x += width

    def fit_text(value, width, font_name, font_size):
        value = str(value)
        if stringWidth(value, font_name, font_size) <= width:
            return value
        while value and stringWidth(value + '...', font_name, font_size) > width:
            value = value[:-1]
        return value + '...'

    def draw_row(values, y, is_total=False):
        canvas.setFillColor(
            colors.HexColor('#DDF5EE') if is_total else colors.white
        )
        canvas.rect(table_left, y - row_height, table_width, row_height, fill=1, stroke=0)
        canvas.setStrokeColor(colors.HexColor('#D6E8E4'))
        canvas.line(table_left, y - row_height, table_left + table_width, y - row_height)
        font_name = 'Helvetica-Bold' if is_total else 'Helvetica'
        font_size = 7
        canvas.setFont(font_name, font_size)
        canvas.setFillColor(colors.HexColor('#263746'))
        x = table_left
        for index, (value, width) in enumerate(zip(values, column_widths)):
            text = fit_text(value, width - 8, font_name, font_size)
            if index in (4, 5, 6):
                canvas.drawRightString(x + width - 4, y - 14, text)
            else:
                canvas.drawString(x + 4, y - 14, text)
            x += width

    def start_remarks_page():
        nonlocal page_number
        footer()
        canvas.showPage()
        page_number += 1
        canvas.setFillColor(colors.HexColor('#181818'))
        canvas.rect(0, page_height - 76, page_width, 76, fill=1, stroke=0)
        draw_business_logo(canvas, margin, page_height - 72, 100, 67, business['logo_path'])
        canvas.setFillColor(colors.white)
        canvas.setFont('Helvetica', 9)
        canvas.drawRightString(
            page_width - margin, page_height - 31, 'STAFF REMARKS'
        )
        canvas.setFillColor(colors.HexColor('#263746'))
        canvas.setFont('Helvetica-Bold', 13)
        canvas.drawString(margin, page_height - 88, f'Staff Remarks - {year_label}')
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#637A78'))
        canvas.drawRightString(
            page_width - margin, page_height - 88,
            'Remark dates and times shown in IST'
        )

    remark_widths = [92, 82, 88, 66, 42, 72, 330]
    remark_headers = [
        'Client', 'Client Invoice(s)', 'Staff Member', 'Date', 'Time', 'Category', 'Remark'
    ]
    remark_table_width = sum(remark_widths)
    remark_left = (page_width - remark_table_width) / 2
    remark_font_size = 7

    def draw_remarks_header(y):
        canvas.setFillColor(colors.HexColor('#176B65'))
        canvas.rect(
            remark_left, y - row_height, remark_table_width, row_height,
            fill=1, stroke=0
        )
        canvas.setFillColor(colors.white)
        canvas.setFont('Helvetica-Bold', remark_font_size)
        x = remark_left
        for header, width in zip(remark_headers, remark_widths):
            canvas.drawString(x + 4, y - 14, header)
            x += width

    start_page(first_page=True)
    y = table_top - row_height
    invoice_count = 0
    for row in report_invoice_rows(financial_year_start):
        if y - row_height < 42:
            start_page()
            y = table_top - row_height
        invoice_date = row['invoice_date']
        if invoice_date is None:
            date_label = ''
        else:
            if invoice_date.tzinfo is None:
                invoice_date = invoice_date.replace(tzinfo=timezone.utc)
            date_label = invoice_date.astimezone(
                timezone(timedelta(hours=5, minutes=30))
            ).strftime('%d-%m-%Y')
        draw_row([
            row['invoice_number'], date_label, row['client_name'], row['contact_number'],
            f'{row["total"]:,.2f}', f'{row["received"]:,.2f}',
            f'{row["pending"]:,.2f}', row['payment_status']
        ], y)
        y -= row_height
        invoice_count += 1
    if y - row_height < 42:
        start_page()
        y = table_top - row_height
    draw_row([
        f'GRAND TOTAL ({invoice_count})', '', '', '',
        f'{summary["total_invoice_amount"]:,.2f}',
        f'{summary["total_paid_amount"]:,.2f}',
        f'{summary["total_pending_amount"]:,.2f}', ''
    ], y, is_total=True)
    canvas.setFont('Helvetica-Oblique', 7)
    canvas.setFillColor(colors.HexColor('#637A78'))
    canvas.drawString(
        margin, 36,
        f'Total GST: {report_currency(summary["total_gst"])}. GST component breakdown is not stored.'
    )
    if remarks:
        start_remarks_page()
        y = page_height - 112
        draw_remarks_header(y)
        y -= row_height
        for remark in remarks:
            values = [
                remark['client_name'],
                ', '.join(remark['invoice_numbers']) or '-',
                remark['staff_name'],
                remark['remark_date'],
                remark['remark_time'],
                remark['category'],
                remark['remark']
            ]
            wrapped_values = [
                simpleSplit(str(value), 'Helvetica', remark_font_size, width - 8)
                for value, width in zip(values, remark_widths)
            ]
            wrapped_values = [lines or [''] for lines in wrapped_values]
            remaining_lines = [len(lines) for lines in wrapped_values]
            line_offsets = [0] * len(wrapped_values)
            while any(remaining_lines):
                if y - 34 < 42:
                    start_remarks_page()
                    y = page_height - 112
                    draw_remarks_header(y)
                    y -= row_height

                available_lines = max(1, int((y - 42 - 10) // 9))
                chunk_line_count = min(max(remaining_lines), available_lines)
                remark_height = max(24, chunk_line_count * 9 + 10)
                canvas.setFillColor(colors.white)
                canvas.rect(
                    remark_left, y - remark_height, remark_table_width, remark_height,
                    fill=1, stroke=0
                )
                canvas.setStrokeColor(colors.HexColor('#D6E8E4'))
                canvas.line(
                    remark_left, y - remark_height,
                    remark_left + remark_table_width, y - remark_height
                )
                canvas.setFont('Helvetica', remark_font_size)
                canvas.setFillColor(colors.HexColor('#263746'))
                x = remark_left
                for value_index, (lines, width) in enumerate(
                    zip(wrapped_values, remark_widths)
                ):
                    chunk = lines[
                        line_offsets[value_index]:
                        line_offsets[value_index] + chunk_line_count
                    ]
                    for line_index, line in enumerate(chunk):
                        canvas.drawString(
                            x + 4, y - 12 - line_index * 9, line
                        )
                    x += width
                for index, remaining in enumerate(remaining_lines):
                    lines_consumed = min(remaining, chunk_line_count)
                    remaining_lines[index] -= lines_consumed
                    line_offsets[index] += lines_consumed
                y -= remark_height
        footer()
    else:
        footer()
    canvas.save()
    buffer.seek(0)
    return buffer


def report_excel(financial_year_start, summary, remarks):
    year_label = report_financial_year_label(financial_year_start)
    workbook = Workbook(write_only=True)
    summary_sheet = workbook.create_sheet('Summary')
    invoice_sheet = workbook.create_sheet('Invoice Details')
    client_sheet = workbook.create_sheet('Client Details')
    header_fill = PatternFill('solid', fgColor='176B65')
    header_font = Font(color='FFFFFF', bold=True)
    title_font = Font(color='C4161C', bold=True, size=14)
    currency_format = '"INR" #,##0.00'
    business_name = invoice_business_details()['name']
    workbook.properties.creator = business_name
    workbook.properties.title = f'{business_name} Report - {year_label}'

    def styled_cell(sheet, value, *, header=False, title=False, number_format=None):
        cell = WriteOnlyCell(sheet, value=value)
        if header:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center')
        elif title:
            cell.font = title_font
        elif number_format:
            cell.number_format = number_format
        return cell

    summary_sheet.column_dimensions['A'].width = 30
    summary_sheet.column_dimensions['B'].width = 24
    summary_sheet.append([styled_cell(summary_sheet, business_name, title=True)])
    summary_sheet.append(['Tax Consultant | TaxSecure Report'])
    summary_sheet.append([styled_cell(summary_sheet, 'Financial Year'), year_label])
    summary_sheet.append([styled_cell(summary_sheet, 'Total Clients'), len(summary['clients'])])
    summary_sheet.append([styled_cell(summary_sheet, 'Total Invoices'), summary['invoice_count']])
    for label, key in (
        ('Total Invoice Amount', 'total_invoice_amount'),
        ('Total GST', 'total_gst'),
        ('Total Paid Amount', 'total_paid_amount'),
        ('Total Pending Amount', 'total_pending_amount')
    ):
        summary_sheet.append([
            label,
            styled_cell(summary_sheet, float(summary[key]), number_format=currency_format)
        ])
    summary_sheet.append([
        'GST detail',
        'CGST/SGST/IGST are blank because the database stores only total GST.'
    ])
    summary_sheet.freeze_panes = 'A2'

    invoice_headers = [
        'Invoice Number', 'Invoice Date', 'Client Name', 'Contact Number',
        'Invoice Amount', 'Paid Amount', 'Pending Amount', 'Payment Status'
    ]
    invoice_sheet.append([styled_cell(invoice_sheet, business_name, title=True)])
    invoice_sheet.append([f'Tax Consultant | Invoice Details | {year_label}'])
    invoice_sheet.append([
        styled_cell(invoice_sheet, value, header=True) for value in invoice_headers
    ])
    invoice_sheet.freeze_panes = 'A4'
    invoice_sheet.column_dimensions['A'].width = 30
    invoice_sheet.column_dimensions['B'].width = 16
    invoice_sheet.column_dimensions['C'].width = 28
    invoice_sheet.column_dimensions['D'].width = 18
    for column in ('E', 'F', 'G'):
        invoice_sheet.column_dimensions[column].width = 18
    invoice_sheet.column_dimensions['H'].width = 18
    invoice_count = 0
    for row in report_invoice_rows(financial_year_start):
        invoice_date = row['invoice_date']
        date_label = ''
        if invoice_date is not None:
            if invoice_date.tzinfo is None:
                invoice_date = invoice_date.replace(tzinfo=timezone.utc)
            date_label = invoice_date.astimezone(
                timezone(timedelta(hours=5, minutes=30))
            ).strftime('%Y-%m-%d')
        invoice_sheet.append([
            row['invoice_number'], date_label, row['client_name'], row['contact_number'],
            styled_cell(invoice_sheet, float(row['total']), number_format=currency_format),
            styled_cell(invoice_sheet, float(row['received']), number_format=currency_format),
            styled_cell(invoice_sheet, float(row['pending']), number_format=currency_format),
            row['payment_status']
        ])
        invoice_count += 1
    invoice_sheet.auto_filter.ref = f'A3:H{invoice_count + 3}'

    client_headers = [
        'Client Name', 'Contact Number', 'Financial Year', 'Total Invoices',
        'Total Invoice Amount'
    ]
    client_sheet.append([styled_cell(client_sheet, business_name, title=True)])
    client_sheet.append([f'Tax Consultant | Client Details | {year_label}'])
    client_sheet.append([
        styled_cell(client_sheet, value, header=True) for value in client_headers
    ])
    client_sheet.freeze_panes = 'A4'
    client_sheet.column_dimensions['A'].width = 30
    client_sheet.column_dimensions['B'].width = 20
    client_sheet.column_dimensions['C'].width = 18
    client_sheet.column_dimensions['D'].width = 18
    client_sheet.column_dimensions['E'].width = 22
    for client in sorted(
        summary['clients'].values(),
        key=lambda item: (item['client_name'].casefold(), item['contact_number'])
    ):
        client_sheet.append([
            client['client_name'],
            client['contact_number'],
            year_label,
            client['invoice_count'],
            styled_cell(
                client_sheet, float(client['total_invoice_amount']),
                number_format=currency_format
            )
        ])
    client_sheet.auto_filter.ref = f'A3:E{len(summary["clients"]) + 3}'

    remarks_sheet = workbook.create_sheet('Staff Remarks')
    remarks_headers = [
        'Client Name', 'Client Invoice Number(s)', 'Staff Member',
        'Remark Date', 'Remark Time', 'Category', 'Remark'
    ]
    remarks_sheet.append([styled_cell(remarks_sheet, business_name, title=True)])
    remarks_sheet.append([f'Tax Consultant | Staff Remarks | {year_label}'])
    remarks_sheet.append([
        styled_cell(remarks_sheet, value, header=True)
        for value in remarks_headers
    ])
    for column, width in {
        'A': 30, 'B': 32, 'C': 24, 'D': 16, 'E': 14, 'F': 30, 'G': 70
    }.items():
        remarks_sheet.column_dimensions[column].width = width
    remarks_sheet.freeze_panes = 'A4'
    for remark in remarks:
        remarks_sheet.append([
            remark['client_name'],
            ', '.join(remark['invoice_numbers']),
            remark['staff_name'],
            remark['remark_date'],
            remark['remark_time'],
            remark['category'],
            remark['remark']
        ])
    remarks_sheet.auto_filter.ref = f'A3:G{len(remarks) + 3}'

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


@app.route('/api/reports/financial-years')
def report_financial_years():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    current_user = get_user(session['user_id'])
    if current_user is None or current_user.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403

    return jsonify({
        'financial_years': [
            {'value': year, 'label': f'FY {year}'}
            for year in FINANCIAL_YEAR_OPTIONS
        ]
    })


@app.route('/api/reports/summary')
def financial_year_report_summary():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    current_user = get_user(session['user_id'])
    if current_user is None or current_user.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    try:
        financial_year_start = parse_report_financial_year(
            request.args.get('financial_year', 'all')
        )
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    summary = report_data_summary(financial_year_start)
    return jsonify({
        'financial_year': report_financial_year_label(financial_year_start),
        'total_invoice_amount': float(summary['total_invoice_amount']),
        'total_paid_amount': float(summary['total_paid_amount']),
        'total_pending_amount': float(summary['total_pending_amount']),
        'total_gst': float(summary['total_gst']),
        'total_invoices': summary['invoice_count'],
        'total_clients': len(summary['clients'])
    })


@app.route('/api/reports/remarks')
def financial_year_report_remarks():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    current_user = get_user(session['user_id'])
    if current_user is None or current_user.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    try:
        financial_year_start = parse_report_financial_year(
            request.args.get('financial_year', 'all')
        )
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    return jsonify({
        'remarks': report_remark_rows(financial_year_start)
    })


@app.route('/api/reports/export/<report_format>')
def export_financial_year_report(report_format):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    current_user = get_user(session['user_id'])
    if current_user is None or current_user.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    if report_format not in ('pdf', 'excel'):
        return jsonify({'error': 'Unsupported report format'}), 404
    try:
        financial_year_start = parse_report_financial_year(
            request.args.get('financial_year', 'all')
        )
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

    summary = report_data_summary(financial_year_start)
    remarks = report_remark_rows(financial_year_start)
    year_suffix = 'All_Years' if financial_year_start is None else (
        f'FY_{financial_year_start}-{(financial_year_start + 1) % 100:02d}'
    )
    if report_format == 'pdf':
        return send_file(
            report_pdf(financial_year_start, summary, remarks),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'TaxSecure_Report_{year_suffix}.pdf'
        )
    return send_file(
        report_excel(financial_year_start, summary, remarks),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'TaxSecure_Report_{year_suffix}.xlsx'
    )


@app.route('/api/referrals')
def referral_report():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    current_user = get_user(session['user_id'])
    if current_user is None or current_user.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    try:
        financial_year_start = parse_report_financial_year(
            request.args.get('financial_year', 'all')
        )
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    search_term = request.args.get('client', '').strip()
    if len(search_term) > 100:
        return jsonify({'error': 'Client search must be 100 characters or fewer'}), 400
    return jsonify(referral_report_payload(search_term, financial_year_start))


@app.route('/api/referrals/export/<report_format>')
def export_referral_report(report_format):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    current_user = get_user(session['user_id'])
    if current_user is None or current_user.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    if report_format not in ('pdf', 'excel'):
        return jsonify({'error': 'Unsupported report format'}), 404
    try:
        financial_year_start = parse_report_financial_year(
            request.args.get('financial_year', 'all')
        )
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    search_term = request.args.get('client', '').strip()
    if len(search_term) > 100:
        return jsonify({'error': 'Client search must be 100 characters or fewer'}), 400

    report = referral_report_payload(search_term, financial_year_start)
    year_suffix = 'All_Years' if financial_year_start is None else (
        f'FY_{financial_year_start}-{(financial_year_start + 1) % 100:02d}'
    )
    search_suffix = f'_{re.sub(r"[^A-Za-z0-9_-]+", "_", search_term)[:40]}' if search_term else ''
    filename = f'TaxSecure_Referral_Report_{year_suffix}{search_suffix}'
    if report_format == 'pdf':
        buffer = BytesIO()
        document = SimpleDocTemplate(
            buffer, pagesize=landscape(A4),
            rightMargin=12 * mm, leftMargin=12 * mm,
            topMargin=12 * mm, bottomMargin=12 * mm,
            title='TaxSecure Referral Report'
        )
        styles = getSampleStyleSheet()
        story = [
            Paragraph('Client Referral Report', styles['Title']),
            Paragraph(
                f'Financial Year: {escape("All Financial Years" if financial_year_start is None else f"FY {year_suffix[3:]}")}',
                styles['Normal']
            ),
            Spacer(1, 5 * mm)
        ]
        summary = report['summary']
        most_referrals = summary['most_referrals_by_client']
        story.append(Paragraph(
            'Total Referring Clients: '
            f'{summary["total_referring_clients"]} &nbsp; | &nbsp; '
            'Total Referred Clients: '
            f'{summary["total_referred_clients"]} &nbsp; | &nbsp; '
            'Most Referrals: '
            f'{escape(most_referrals["client_name"]) if most_referrals else "—"}'
            f' ({most_referrals["referral_count"] if most_referrals else 0})',
            styles['Normal']
        ))
        year_summary = ', '.join(
            f'FY {year["financial_year"]}: {year["referral_count"]}'
            for year in summary['financial_year_referrals']
        ) or 'No referrals'
        story.append(Paragraph(
            f'Financial Year-wise Referrals: {escape(year_summary)}',
            styles['Normal']
        ))
        story.append(Spacer(1, 5 * mm))
        data = [[
            'Referring Client', 'Referred Client', 'Total Referrals',
            'Referral Date', 'Financial Year'
        ]]
        data.extend([
            [
                Paragraph(escape(row['referrer_name']), styles['BodyText']),
                Paragraph(escape(row['referred_client_name']), styles['BodyText']),
                row['referral_count'],
                row['referral_date'],
                f'FY {row["financial_year"]}'
            ]
            for row in report['referrals']
        ])
        table = Table(data, colWidths=[58 * mm, 68 * mm, 32 * mm, 40 * mm, 34 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#176B65')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#D6E8E4')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F2FAF8')]),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5)
        ]))
        story.append(table)
        if not report['referrals']:
            story.append(Paragraph('No referrals match the selected filters.', styles['Normal']))
        document.build(story)
        buffer.seek(0)
        return send_file(
            buffer, mimetype='application/pdf', as_attachment=True,
            download_name=f'{filename}.pdf'
        )

    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = 'Referral Summary'
    summary_sheet.append(['Metric', 'Value'])
    summary = report['summary']
    most_referrals = summary['most_referrals_by_client']
    summary_sheet.append(['Total Referring Clients', summary['total_referring_clients']])
    summary_sheet.append(['Total Referred Clients', summary['total_referred_clients']])
    summary_sheet.append([
        'Most Referrals by Client',
        most_referrals['client_name'] if most_referrals else '—'
    ])
    summary_sheet.append([
        'Most Referrals', most_referrals['referral_count'] if most_referrals else 0
    ])
    summary_sheet.append([])
    summary_sheet.append(['Financial Year', 'Referrals'])
    for year in summary['financial_year_referrals']:
        summary_sheet.append([f'FY {year["financial_year"]}', year['referral_count']])

    details_sheet = workbook.create_sheet('Referral Details')
    details_sheet.append([
        'Referring Client', 'Referred Client', 'Total Referrals',
        'Referral Date', 'Financial Year'
    ])
    for row in report['referrals']:
        details_sheet.append([
            row['referrer_name'],
            row['referred_client_name'],
            row['referral_count'],
            row['referral_date'],
            f'FY {row["financial_year"]}'
        ])
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'{filename}.xlsx'
    )


def create_invoice_with_number(client, invoice_data):
    with transaction() as connection:
        existing = connection.execute(
            'SELECT id, invoice_number FROM invoice WHERE request_token = %s',
            (invoice_data['request_token'],)
        ).fetchone()
        if existing:
            return existing['id'], existing['invoice_number'], True

        created_at = datetime.utcnow()
        assessment_year = assessment_year_for(created_at + timedelta(hours=5, minutes=30))
        connection.execute(
            'INSERT INTO invoice_number_sequence (assessment_year, last_sequence) '
            'VALUES (%s, 0) ON CONFLICT (assessment_year) DO NOTHING',
            (assessment_year,)
        )
        sequence_row = connection.execute(
            'SELECT last_sequence FROM invoice_number_sequence '
            'WHERE assessment_year = %s FOR UPDATE',
            (assessment_year,)
        ).fetchone()
        existing_max = connection.execute(
            'SELECT COALESCE(MAX((regexp_match(invoice_number, %s))[1]::INTEGER), 0) AS max_seq '
            'FROM invoice WHERE invoice_number ~ %s',
            (rf'^AY{re.escape(assessment_year)}/([0-9]+)$',
             rf'^AY{re.escape(assessment_year)}/[0-9]+$')
        ).fetchone()['max_seq']
        next_sequence = max(sequence_row['last_sequence'], existing_max) + 1
        connection.execute(
            'UPDATE invoice_number_sequence SET last_sequence = %s WHERE assessment_year = %s',
            (next_sequence, assessment_year)
        )

        invoice_number = f'AY{assessment_year}/{next_sequence:04d}'
        inserted = connection.execute(
            'INSERT INTO invoice ('
            'client_id, invoice_number, amount, fees, discount_type, discount_value, '
            'discount_amount, service_description, request_token, '
            'client_name, client_email, client_pan_number, client_phone, date, status, '
            'created_at, workflow_status, delivery_status, received_amount'
            ') VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) '
            'ON CONFLICT (request_token) DO NOTHING RETURNING id',
            (
                client['id'], invoice_number, invoice_data['amount'], 0,
                invoice_data['discount_type'], invoice_data['discount_value'],
                invoice_data['discount_amount'],
                invoice_data['service_description'], invoice_data['request_token'],
                client['name'], client['email'], client['pan'], client['phone'],
                created_at, invoice_data['status'], created_at,
                invoice_data['workflow_status'], 'not_sent', invoice_data['received_amount']
            )
        ).fetchone()
        if inserted is None:
            existing = connection.execute(
                'SELECT id, invoice_number FROM invoice WHERE request_token = %s',
                (invoice_data['request_token'],)
            ).fetchone()
            return existing['id'], existing['invoice_number'], True
        return inserted['id'], invoice_number, False


def active_invoice_or_404(invoice_id):
    invoice = get_invoice(invoice_id)
    if invoice is None:
        from flask import abort
        abort(404)
    return invoice


@app.route('/api/invoices', methods=['GET', 'POST'])
def invoices():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    if request.method == 'GET':
        current_user = get_user(session['user_id'])
        
        if current_user.role == 'admin':
            invoice_records = fetch_all(
                'SELECT * FROM invoice WHERE deleted_at IS NULL ORDER BY date DESC, id DESC'
            )
        else:
            invoice_records = fetch_all(
                'SELECT i.* FROM invoice i JOIN client c ON c.id = i.client_id '
                'WHERE c.assigned_to = %s AND i.deleted_at IS NULL '
                'ORDER BY i.date DESC, i.id DESC',
                (current_user.id,)
            )
        return jsonify({'invoices': [invoice_json(invoice) for invoice in invoice_records]})

    if request.method == 'POST':
        current_user = get_user(session['user_id'])
        if current_user.role != 'admin':
            return jsonify({'error': 'Admin access required'}), 403

        data = request.get_json(silent=True) or {}
        try:
            client_id = int(data.get('client_id'))
        except (TypeError, ValueError):
            return jsonify({'error': 'Select a valid client'}), 400
        client = get_client(client_id)
        if client is None:
            return jsonify({'error': 'Selected client was not found'}), 404

        try:
            amount = Decimal(str(data.get('amount')))
            if not amount.is_finite() or amount <= 0:
                raise InvalidOperation
            amount = amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except (InvalidOperation, TypeError, ValueError):
            return jsonify({'error': 'Enter a valid invoice amount greater than zero'}), 400

        request_token = data.get('request_token')
        if not isinstance(request_token, str) or not re.fullmatch(r'[A-Za-z0-9-]{16,64}', request_token):
            return jsonify({'error': 'Invalid invoice request token'}), 400
        existing_invoice = fetch_one(
            'SELECT id, invoice_number FROM invoice WHERE request_token = %s',
            (request_token,)
        )
        if existing_invoice:
            return jsonify({
                'success': True,
                'duplicate': True,
                'invoice_id': existing_invoice.id,
                'invoice_number': existing_invoice.invoice_number
            })

        status = data.get('status', 'pending')
        if status not in ('pending', 'paid'):
            return jsonify({'error': 'Payment status must be Paid or Pending'}), 400
        service_description = data.get(
            'service_description',
            'Income Tax Filing & Documentation Services'
        )
        if not isinstance(service_description, str) or not service_description.strip():
            return jsonify({'error': 'Service description is required'}), 400

        workflow_status = data.get('workflow_status', 'pending_review')
        if workflow_status not in ('draft', 'pending_review'):
            return jsonify({'error': 'Invoice must be saved as a draft or submitted for review'}), 400

        discount_type = data.get('discount_type') or 'percentage'
        if discount_type in ('fixed_amount', 'fixed amount'):
            discount_type = 'fixed'
        elif discount_type in ('percent', '%'):
            discount_type = 'percentage'
        try:
            discount_type, discount_value, discount_amount = calculate_invoice_discount(
                amount, discount_type, data.get('discount_value', 0)
            )
        except ValueError as error:
            return jsonify({'error': str(error)}), 400
        total = (amount - discount_amount).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        try:
            received = Decimal(str(data.get('received_amount', 0)))
            if not received.is_finite() or received < 0 or received > total:
                raise InvalidOperation
            received = received.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except (InvalidOperation, TypeError, ValueError):
            return jsonify({'error': 'Received amount must be between zero and the invoice total'}), 400
        if status == 'paid' and received < total:
            return jsonify({'error': 'A paid invoice must have the full amount received'}), 400
        if received == total:
            status = 'paid'

        client_data = {
            'id': client.id,
            'name': client.client_name,
            'email': client.email or '',
            'pan': client.pan_number or '',
            'phone': client.phone
        }
        invoice_data = {
            'amount': float(amount),
            'discount_type': discount_type,
            'discount_value': float(discount_value),
            'discount_amount': float(discount_amount),
            'service_description': service_description.strip()[:250],
            'request_token': request_token,
            'status': status,
            'received_amount': float(received),
            'workflow_status': workflow_status
        }
        invoice_id, invoice_number, duplicate = create_invoice_with_number(
            client_data, invoice_data
        )
        if duplicate:
            return jsonify({
                'success': True,
                'duplicate': True,
                'invoice_id': invoice_id,
                'invoice_number': invoice_number
            })
        new_invoice = get_invoice(invoice_id)
        return jsonify({
            'success': True,
            **invoice_json(new_invoice)
        })

@app.route('/api/invoices/<int:invoice_id>', methods=['GET', 'PUT', 'DELETE'])
def invoice_details(invoice_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    current_user = get_user(session['user_id'])
    invoice = active_invoice_or_404(invoice_id)
    if not invoice_allowed_for_user(invoice, current_user):
        return jsonify({'error': 'Unauthorized'}), 403

    if request.method == 'DELETE':
        if current_user.role != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        execute('UPDATE invoice SET deleted_at = %s WHERE id = %s',
                (datetime.utcnow(), invoice.id))
        return jsonify({'success': True})

    if request.method == 'PUT':
        if current_user.role != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        data = request.get_json(silent=True) or {}
        if not data:
            return jsonify({'error': 'No invoice changes were provided'}), 400

        financial_fields = {
            'amount', 'discount_type', 'discount_value', 'received_amount',
            'service_description', 'workflow_status'
        }
        if financial_fields.intersection(data):
            if invoice.workflow_status not in ('draft', 'pending_review') or invoice.delivery_status in ('sending', 'sent'):
                return jsonify({'error': 'Only invoices awaiting review can be edited'}), 409
            if 'workflow_status' in data:
                workflow_status = data['workflow_status']
                if workflow_status not in ('draft', 'pending_review'):
                    return jsonify({'error': 'Invoice must remain a draft or pending review'}), 400
                invoice.workflow_status = workflow_status
            if 'service_description' in data:
                description = data['service_description']
                if not isinstance(description, str) or not description.strip():
                    return jsonify({'error': 'Service description is required'}), 400
                invoice.service_description = description.strip()[:250]
            amount = Decimal(str(invoice.amount))
            if 'amount' in data:
                try:
                    amount = Decimal(str(data['amount']))
                    if not amount.is_finite() or amount <= 0:
                        raise InvalidOperation
                    amount = amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                except (InvalidOperation, TypeError, ValueError):
                    return jsonify({'error': 'Enter a valid invoice amount greater than zero'}), 400
            discount_type = data.get('discount_type', invoice.discount_type or 'percentage')
            if discount_type in ('fixed_amount', 'fixed amount'):
                discount_type = 'fixed'
            elif discount_type in ('percent', '%'):
                discount_type = 'percentage'
            try:
                discount_type, discount_value, discount_amount = calculate_invoice_discount(
                    amount,
                    discount_type or 'percentage',
                    data.get('discount_value', invoice.discount_value or 0)
                )
            except ValueError as error:
                return jsonify({'error': str(error)}), 400
            invoice.amount = float(amount)
            invoice.fees = 0
            invoice.discount_type = discount_type
            invoice.discount_value = float(discount_value)
            invoice.discount_amount = float(discount_amount)
            total = invoice_total(invoice)
            try:
                received = Decimal(str(data.get('received_amount', invoice.received_amount or 0)))
                if not received.is_finite() or received < 0 or received > total:
                    raise InvalidOperation
                received = received.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            except (InvalidOperation, TypeError, ValueError):
                return jsonify({'error': 'Received amount must be between zero and the invoice total'}), 400
            invoice.received_amount = float(received)
            requested_status = data.get('status', invoice.status)
            if requested_status not in ('pending', 'paid'):
                return jsonify({'error': 'Payment status must be Paid or Pending'}), 400
            if requested_status == 'paid' and received < total:
                return jsonify({'error': 'A paid invoice must have the full amount received'}), 400
            invoice.status = 'paid' if received == total else requested_status
        else:
            status = data.get('status')
            if status not in ('pending', 'paid'):
                return jsonify({'error': 'Payment status must be Paid or Pending'}), 400
            invoice.status = status
            if status == 'paid':
                invoice.received_amount = float(invoice_total(invoice))

        execute(
            'UPDATE invoice SET amount = %s, fees = %s, discount_type = %s, '
            'discount_value = %s, discount_amount = %s, service_description = %s, '
            'workflow_status = %s, received_amount = %s, status = %s WHERE id = %s',
            (invoice.amount, invoice.fees, invoice.discount_type, invoice.discount_value,
             invoice.discount_amount, invoice.service_description, invoice.workflow_status,
             invoice.received_amount, invoice.status, invoice.id)
        )

    return jsonify(invoice_json(invoice))


@app.route('/api/invoices/<int:invoice_id>/approve', methods=['POST'])
def approve_invoice(invoice_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    current_user = get_user(session['user_id'])
    if current_user is None or current_user.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    invoice = active_invoice_or_404(invoice_id)
    if invoice.workflow_status == 'approved' and invoice.pdf_filename:
        return jsonify({'success': True, 'invoice': invoice_json(invoice)})
    if invoice.workflow_status not in ('draft', 'pending_review'):
        return jsonify({'error': 'Only invoices pending review can be approved'}), 409
    if invoice.delivery_status in ('sending', 'sent'):
        return jsonify({'error': 'This invoice has already entered delivery'}), 409

    pdf_path = None
    try:
        _, pdf_path = save_approved_invoice_pdf(invoice)
        invoice.workflow_status = 'approved'
        invoice.approved_at = datetime.utcnow()
        invoice.approved_by_id = current_user.id
        invoice.delivery_error = None
        execute(
            'UPDATE invoice SET workflow_status = %s, approved_at = %s, '
            'approved_by_id = %s, delivery_error = NULL, pdf_filename = %s, '
            'pdf_sha256 = %s WHERE id = %s',
            ('approved', invoice.approved_at, current_user.id, invoice.pdf_filename,
             invoice.pdf_sha256, invoice.id)
        )
    except Exception:
        if pdf_path:
            try:
                os.remove(pdf_path)
            except FileNotFoundError:
                pass
        app.logger.exception('Could not approve invoice %s', invoice_id)
        return jsonify({'error': 'The invoice could not be approved and stored securely'}), 500
    return jsonify({'success': True, 'invoice': invoice_json(invoice)})


@app.route('/api/invoices/<int:invoice_id>/share-whatsapp', methods=['POST'])
def share_invoice_whatsapp(invoice_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    current_user = get_user(session['user_id'])
    if current_user is None or current_user.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    invoice = active_invoice_or_404(invoice_id)
    if invoice.workflow_status != 'approved':
        return jsonify({'error': 'Approve the invoice before sharing it'}), 409
    try:
        invoice_whatsapp_recipient(invoice)
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

    data = request.get_json(silent=True) or {}
    if invoice.delivery_status == 'manual_required':
        return jsonify({
            'success': True,
            'delivery_status': 'manual_required',
            'message': 'WhatsApp is open-in-chat only. Download the PDF and attach it manually.',
            'whatsapp_url': whatsapp_fallback_url(invoice),
            'download_url': url_for('invoice_pdf_download', invoice_id=invoice.id)
        })
    if invoice.delivery_status == 'legacy_unknown':
        return jsonify({'error': 'Delivery history for this older invoice is unknown; automatic sending is blocked to prevent duplicates'}), 409
    if invoice.delivery_status in ('sending', 'sent'):
        return jsonify({
            'error': 'This invoice has already been submitted for delivery.',
            'delivery_status': invoice.delivery_status
        }), 409
    if invoice.delivery_status == 'failed' and data.get('retry') is not True:
        return jsonify({
            'error': 'Delivery previously failed. Confirm a deliberate retry to avoid duplicate messages.',
            'delivery_status': 'failed'
        }), 409

    if not whatsapp_cloud_is_configured():
        execute(
            'UPDATE invoice SET delivery_status = %s, delivery_error = NULL WHERE id = %s',
            ('manual_required', invoice.id)
        )
        return jsonify({
            'success': True,
            'delivery_status': 'manual_required',
            'message': 'WhatsApp Cloud API is not configured. Download the PDF and attach it in the opened client chat.',
            'whatsapp_url': whatsapp_fallback_url(invoice),
            'download_url': url_for('invoice_pdf_download', invoice_id=invoice.id)
        })

    claim = execute(
        'UPDATE invoice SET delivery_status = %s, delivery_attempted_at = %s, '
        'delivery_error = NULL WHERE id = %s AND workflow_status = %s '
        'AND deleted_at IS NULL AND delivery_status IN (%s, %s) RETURNING id',
        ('sending', datetime.utcnow(), invoice.id, 'approved', 'not_sent', 'failed')
    )
    if claim is None:
        return jsonify({'error': 'This invoice is already being delivered or has already been sent'}), 409

    invoice = active_invoice_or_404(invoice_id)
    try:
        pdf_bytes = get_invoice_pdf(invoice)
        message_id = send_invoice_pdf_via_whatsapp(invoice, pdf_bytes)
        execute('UPDATE invoice SET wa_message_id = %s WHERE id = %s',
                (message_id, invoice.id))
        return jsonify({
            'success': True,
            'delivery_status': 'sending',
            'message': 'WhatsApp accepted the invoice document. Delivery will be confirmed by its status webhook.'
        })
    except (RuntimeError, ValueError, OSError) as error:
        invoice = active_invoice_or_404(invoice_id)
        execute(
            'UPDATE invoice SET delivery_status = %s, delivery_error = %s WHERE id = %s',
            ('failed', str(error)[:1000], invoice.id)
        )
        app.logger.warning('WhatsApp invoice delivery failed for invoice %s: %s', invoice_id, error)
        return jsonify({'error': 'Invoice delivery failed: ' + str(error), 'delivery_status': 'failed'}), 502


@app.route('/api/invoices/<int:invoice_id>/mark-manual-sent', methods=['POST'])
def mark_invoice_manually_sent(invoice_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    current_user = get_user(session['user_id'])
    if current_user is None or current_user.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    invoice = active_invoice_or_404(invoice_id)
    if invoice.workflow_status != 'approved' or invoice.delivery_status != 'manual_required':
        return jsonify({'error': 'Only an approved invoice awaiting manual WhatsApp sharing can be marked sent'}), 409
    data = request.get_json(silent=True) or {}
    if data.get('confirmed') is not True:
        return jsonify({'error': 'Confirm that the PDF was manually sent through WhatsApp'}), 400

    execute(
        'UPDATE invoice SET delivery_status = %s, sent_at = %s, delivery_error = NULL '
        'WHERE id = %s',
        ('sent', datetime.utcnow(), invoice.id)
    )
    return jsonify({'success': True, 'invoice': invoice_json(invoice)})


def whatsapp_fallback_url(invoice):
    recipient = invoice_whatsapp_recipient(invoice)
    business_name = invoice_business_details()['name']
    total = invoice_total(invoice)
    received = invoice_received(invoice)
    balance = max(total - received, Decimal('0.00'))
    message = (
        f'Dear {invoice.client_name},\n\nGreetings from {business_name}.\n\n'
        f'Please find attached your invoice {invoice.invoice_number} for the services provided.\n\n'
        f'Total Amount: INR {total:,.2f}\nReceived Amount: INR {received:,.2f}\n'
        f'Balance Amount: INR {balance:,.2f}\n\nThank you for choosing our services.\n\n'
        f'Regards,\n{business_name}'
    )
    return f'https://wa.me/{recipient}?text={urllib.parse.quote(message)}'


@app.route('/api/whatsapp/webhook', methods=['GET', 'POST'])
def whatsapp_webhook():
    if request.method == 'GET':
        verify_token = os.getenv('WHATSAPP_WEBHOOK_VERIFY_TOKEN')
        if (verify_token and request.args.get('hub.mode') == 'subscribe'
                and request.args.get('hub.verify_token') == verify_token):
            return request.args.get('hub.challenge', ''), 200
        return jsonify({'error': 'Webhook verification failed'}), 403

    app_secret = os.getenv('WHATSAPP_APP_SECRET')
    signature = request.headers.get('X-Hub-Signature-256', '')
    if not app_secret or not signature.startswith('sha256='):
        return jsonify({'error': 'Webhook signature verification is unavailable'}), 403
    expected = 'sha256=' + hmac.new(
        app_secret.encode('utf-8'), request.get_data(cache=True), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return jsonify({'error': 'Invalid webhook signature'}), 403

    payload = request.get_json(silent=True) or {}
    changes = [
        change
        for entry in payload.get('entry', [])
        for change in entry.get('changes', [])
    ]
    for change in changes:
        for status_event in change.get('value', {}).get('statuses', []):
            message_id = status_event.get('id')
            status = status_event.get('status')
            if not message_id:
                continue
            invoice = fetch_one(
                'SELECT * FROM invoice WHERE wa_message_id = %s AND deleted_at IS NULL',
                (message_id,)
            )
            if invoice is None or invoice.delivery_status != 'sending':
                continue
            if status in ('delivered', 'read'):
                execute(
                    'UPDATE invoice SET delivery_status = %s, sent_at = %s, '
                    'delivery_error = NULL WHERE id = %s AND delivery_status = %s',
                    ('sent', datetime.utcnow(), invoice.id, 'sending')
                )
            elif status == 'failed':
                errors = status_event.get('errors') or []
                message = errors[0].get('title') or errors[0].get('message') if errors else 'WhatsApp reported a delivery failure.'
                execute(
                    'UPDATE invoice SET delivery_status = %s, delivery_error = %s '
                    'WHERE id = %s AND delivery_status = %s',
                    ('failed', str(message)[:1000], invoice.id, 'sending')
                )
    return jsonify({'success': True})

@app.route('/api/dashboard')
def dashboard_stats():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    current_user = get_user(session['user_id'])
    counts = fetch_one(
        "SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE status = 'pending') AS pending, "
        "COUNT(*) FILTER (WHERE status = 'found') AS found, "
        "COUNT(*) FILTER (WHERE status = 'not_found') AS not_found FROM client"
    )
    
    return jsonify({
        'total': counts.total,
        'pending': counts.pending,
        'found': counts.found,
        'not_found': counts.not_found,
        'user_id': current_user.id,
        'username': current_user.username,
        'role': current_user.role
    })

@app.route('/api/staff/add', methods=['POST'])
def add_staff():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Check if current user is admin
    current_user = get_user(session['user_id'])
    if current_user.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    data = request.get_json(silent=True) or {}
    email = data.get('email', data.get('username', ''))
    full_name = data.get('full_name', '')
    contact_number = data.get('contact_number', '')
    password = data.get('password')
    confirm_password = data.get('confirm_password')

    if not isinstance(email, str) or not validate_staff_email(email.strip()):
        return jsonify({'error': 'Enter a valid staff email address'}), 400
    email = email.strip().lower()
    if fetch_one('SELECT id FROM "user" WHERE username = %s', (email,)):
        return jsonify({'error': 'Email address is already in use'}), 409
    if not isinstance(full_name, str) or not full_name.strip():
        return jsonify({'error': 'Staff full name is required'}), 400
    if not isinstance(contact_number, str):
        return jsonify({'error': 'Contact number must be text'}), 400
    if not isinstance(password, str) or len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400
    if password != confirm_password:
        return jsonify({'error': 'Passwords do not match'}), 400

    try:
        new_staff = execute(
            'INSERT INTO "user" (username, full_name, contact_number, password_hash, role, is_active) '
            'VALUES (%s, %s, %s, %s, %s, TRUE) RETURNING id',
            (email, full_name.strip(), contact_number.strip(),
             generate_password_hash(password), 'staff')
        )
    except IntegrityError:
        if fetch_one('SELECT id FROM "user" WHERE username = %s', (email,)):
            return jsonify({'error': 'Email address is already in use'}), 409
        raise
    return jsonify({'success': True, 'message': 'Staff account created successfully', 'staff_id': new_staff.id})

# Task Management Routes
@app.route('/api/tasks', methods=['GET', 'POST'])
def tasks():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    current_user = get_user(session['user_id'])
    
    if request.method == 'GET':
        if current_user.role == 'admin':
            tasks_list = fetch_all('SELECT * FROM task ORDER BY id')
        else:
            # Staff members see only their assigned tasks
            tasks_list = fetch_all(
                'SELECT * FROM task WHERE assigned_to = %s ORDER BY id',
                (current_user.id,)
            )
        
        tasks_data = []
        for task in tasks_list:
            client = get_client(task.client_id) if task.client_id else None
            if current_user.role == 'staff' and client and client.assigned_to != current_user.id:
                client = None
            
            task_data = {
                'id': task.id,
                'title': task.title,
                'description': task.description,
                'client_id': client.id if client else None,
                'client_name': client.client_name if client else 'General Task',
                'status': task.status,
                'priority': task.priority,
                'due_date': task.due_date.strftime('%Y-%m-%d') if task.due_date else 'N/A',
                'created_at': task.created_at.strftime('%Y-%m-%d %H:%M')
            }
            
            if current_user.role == 'admin':
                assigned_user = get_user(task.assigned_to)
                assigned_by_user = get_user(task.assigned_by)
                task_data['assigned_to'] = assigned_user.username if assigned_user else 'Unassigned'
                task_data['assigned_to_id'] = task.assigned_to
                task_data['assigned_by'] = assigned_by_user.username if assigned_by_user else 'Admin'
            
            tasks_data.append(task_data)
        return jsonify({'tasks': tasks_data})
    
    elif request.method == 'POST':
        if current_user.role != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        
        data = request.get_json()
        assigned_staff = fetch_one(
            'SELECT id FROM "user" WHERE id = %s AND role = %s AND is_active = TRUE',
            (data.get('assigned_to'), 'staff')
        )
        if assigned_staff is None:
            return jsonify({'error': 'Select an active staff account'}), 400
        new_task = execute(
            'INSERT INTO task (title, description, client_id, assigned_to, assigned_by, '
            'status, priority, due_date) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id',
            (data['title'], data.get('description', ''), data.get('client_id'),
             data['assigned_to'], current_user.id, data.get('status', 'pending'),
             data.get('priority', 'medium'),
             datetime.fromisoformat(data['due_date']) if data.get('due_date') else None)
        )
        return jsonify({'success': True, 'message': 'Task assigned successfully', 'task_id': new_task.id})

@app.route('/api/tasks/<int:task_id>', methods=['GET', 'PUT', 'DELETE'])
def task_operations(task_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    current_user = get_user(session['user_id'])
    task = get_task(task_id)
    if task is None:
        return jsonify({'error': 'Task not found'}), 404
    
    # Check authorization
    if current_user.role != 'admin' and task.assigned_to != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    if request.method == 'GET':
        client = get_client(task.client_id) if task.client_id else None
        if current_user.role == 'staff' and client and client.assigned_to != current_user.id:
            client = None
        
        response_data = {
            'id': task.id,
            'title': task.title,
            'description': task.description,
            'client_id': client.id if client else None,
            'client_name': client.client_name if client else 'General Task',
            'status': task.status,
            'priority': task.priority,
            'due_date': task.due_date.strftime('%Y-%m-%d') if task.due_date else '',
            'created_at': task.created_at.strftime('%Y-%m-%d %H:%M')
        }
        
        if current_user.role == 'admin':
            assigned_user = get_user(task.assigned_to)
            assigned_by_user = get_user(task.assigned_by)
            response_data['assigned_to'] = assigned_user.username if assigned_user else 'Unassigned'
            response_data['assigned_to_id'] = task.assigned_to
            response_data['assigned_by'] = assigned_by_user.username if assigned_by_user else 'Admin'
        
        return jsonify(response_data)
    
    elif request.method == 'PUT':
        if current_user.role != 'admin' and task.assigned_to != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        data = request.get_json()
        old_status = task.status
        task.title = data.get('title', task.title)
        task.description = data.get('description', task.description)
        task.status = data.get('status', task.status)
        task.priority = data.get('priority', task.priority)
        
        if data.get('due_date'):
            task.due_date = datetime.fromisoformat(data['due_date'])
        
        if data.get('status') == 'completed' and old_status != 'completed':
            task.completion_date = datetime.utcnow()
        
        execute(
            'UPDATE task SET title = %s, description = %s, status = %s, priority = %s, '
            'due_date = %s, completion_date = %s, updated_at = %s WHERE id = %s',
            (task.title, task.description, task.status, task.priority, task.due_date,
             task.completion_date, datetime.utcnow(), task.id)
        )
        return jsonify({'success': True, 'message': 'Task updated successfully'})
    
    elif request.method == 'DELETE':
        if current_user.role != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        
        execute('DELETE FROM task WHERE id = %s', (task.id,))
        return jsonify({'success': True, 'message': 'Task deleted successfully'})

@app.route('/api/task-stats')
def task_stats():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    current_user = get_user(session['user_id'])
    
    if current_user.role == 'admin':
        counts = fetch_one(
            "SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE status = 'pending') AS pending, "
            "COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress, "
            "COUNT(*) FILTER (WHERE status = 'completed') AS completed FROM task"
        )
    else:
        counts = fetch_one(
            "SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE status = 'pending') AS pending, "
            "COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress, "
            "COUNT(*) FILTER (WHERE status = 'completed') AS completed "
            'FROM task WHERE assigned_to = %s',
            (current_user.id,)
        )
    
    return jsonify({
        'total': counts.total,
        'pending': counts.pending,
        'in_progress': counts.in_progress,
        'completed': counts.completed
    })

def download_invoice(invoice_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    current_user = get_user(session['user_id'])
    invoice = active_invoice_or_404(invoice_id)
    if not invoice_allowed_for_user(invoice, current_user):
        return jsonify({'error': 'Unauthorized'}), 403
    client = get_client(invoice.client_id)
    client_details = invoice_client_details(invoice)
    client_name = escape(client_details['name'])
    client_email = escape(client_details['email'])
    client_phone = escape(client_details['phone'])
    client_pan = escape(client_details['pan'])
    service_description = escape(invoice.service_description)
    business = invoice_business_details()
    logo_url = url_for(
        'static', filename='images/tushar-borse-and-co-logo.jpeg'
    )
    discount_amount = Decimal(str(invoice.discount_amount or 0))
    discount_label = escape(invoice_discount_label(invoice))
    final_total = invoice_total(invoice)
    
    # Generate HTML invoice
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta name="application-name" content="Tushar Borse And Co.">
        <title>Tushar Borse And Co. | Invoice {escape(invoice.invoice_number)}</title>
        <link rel="icon" type="image/jpeg" href="{logo_url}">
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 20px;
                background-color: #F7F7F8;
            }}
            .invoice-container {{
                background-color: white;
                padding: 40px;
                border-radius: 8px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                max-width: 900px;
                margin: 0 auto;
            }}
            .header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 3px solid #C90016;
                padding-bottom: 20px;
                margin-bottom: 30px;
            }}
            .company-info {{
                flex: 1;
                display: flex;
                align-items: center;
                gap: 16px;
                min-width: 0;
            }}
            .company-info img {{
                display: block;
                width: 120px;
                max-width: 30%;
                height: auto;
                object-fit: contain;
            }}
            .company-info h1 {{
                color: #171717;
                margin: 0;
                font-size: 28px;
            }}
            .company-info p {{
                color: #666;
                margin: 5px 0 0 0;
            }}
            .invoice-title {{
                text-align: right;
                flex: 1;
            }}
            .invoice-title h2 {{
                color: #A80012;
                margin: 0;
                font-size: 24px;
            }}
            .invoice-meta {{
                color: #666;
                font-size: 14px;
            }}
            .invoice-details {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 40px;
                margin: 30px 0;
                padding: 20px 0;
                border-top: 1px solid #E8E8E8;
                border-bottom: 1px solid #E8E8E8;
            }}
            .detail-section h3 {{
                color: #171717;
                margin-bottom: 15px;
                font-size: 14px;
                text-transform: uppercase;
                border-bottom: 2px solid #C90016;
                padding-bottom: 10px;
            }}
            .detail-section p {{
                margin: 8px 0;
                color: #555;
                line-height: 1.6;
            }}
            .items-table {{
                width: 100%;
                border-collapse: collapse;
                margin: 30px 0;
            }}
            .items-table th {{
                background-color: #171717;
                color: white;
                padding: 12px;
                text-align: left;
                font-weight: bold;
            }}
            .items-table td {{
                padding: 12px;
                border-bottom: 1px solid #E8E8E8;
            }}
            .items-table tr:nth-child(even) {{
                background-color: #FCFCFC;
            }}
            .summary {{
                display: flex;
                justify-content: flex-end;
                margin: 30px 0;
            }}
            .summary-box {{
                background-color: #FAF1F2;
                padding: 20px;
                border-left: 4px solid #C90016;
                min-width: 250px;
            }}
            .summary-row {{
                display: flex;
                justify-content: space-between;
                padding: 8px 0;
                color: #555;
            }}
            .summary-total {{
                display: flex;
                justify-content: space-between;
                padding: 12px 0;
                border-top: 2px solid #C90016;
                font-size: 18px;
                font-weight: bold;
                color: #171717;
                margin-top: 10px;
            }}
            .footer {{
                margin-top: 40px;
                padding-top: 20px;
                border-top: 1px solid #E8E8E8;
                color: #666;
                font-size: 12px;
                text-align: center;
            }}
            .status-badge {{
                display: inline-block;
                padding: 6px 12px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: bold;
            }}
            .status-paid {{
                background-color: #d4edda;
                color: #155724;
            }}
            .status-pending {{
                background-color: #fff3cd;
                color: #856404;
            }}
            @media print {{
                body {{
                    background-color: white;
                }}
                .invoice-container {{
                    box-shadow: none;
                    max-width: 100%;
                }}
            }}
            @media (max-width: 560px) {{
                .header {{ align-items: flex-start; gap: 12px; }}
                .company-info {{ gap: 8px; }}
                .company-info img {{ width: 78px; }}
                .company-info h1 {{ font-size: 17px; }}
                .invoice-title h2 {{ font-size: 18px; }}
            }}
        </style>
    </head>
    <body>
        <div class="invoice-container">
            <div class="header">
                <div class="company-info">
                    <img src="{logo_url}" alt="Tushar Borse And Co. — Tax Consultant">
                    <div><h1>{escape(business['name'])}</h1>
                    <p>Tax Consultant</p></div>
                </div>
                <div class="invoice-title">
                    <h2>INVOICE</h2>
                    <div class="invoice-meta">
                        <p>Invoice #: <strong>{invoice.invoice_number}</strong></p>
                        <p>Date: <strong>{invoice.date.strftime('%d-%m-%Y')}</strong></p>
                    </div>
                </div>
            </div>

            <div class="invoice-details">
                <div class="detail-section">
                    <h3>Bill To</h3>
                    <p><strong>{client_name}</strong></p>
                    <p>Email: {client_email}</p>
                    <p>Phone: {client_phone}</p>
                    <p>PAN: {client_pan}</p>
                </div>
                <div class="detail-section">
                    <h3>Payment Details</h3>
                    <p>Status: <span class="status-badge status-{invoice.status}">{invoice.status.upper()}</span></p>
                    <p>Invoice Date: {invoice.date.strftime('%d-%m-%Y')}</p>
                    <p>Amount: <strong>₹{invoice.amount:,.2f}</strong></p>
                </div>
            </div>

            <table class="items-table">
                <thead>
                    <tr>
                        <th>Description</th>
                        <th>Quantity</th>
                        <th style="text-align: right;">Unit Price</th>
                        <th style="text-align: right;">Amount</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>{service_description}</td>
                        <td>1</td>
                        <td style="text-align: right;">₹{invoice.amount:,.2f}</td>
                        <td style="text-align: right;">₹{invoice.amount:,.2f}</td>
                    </tr>
                </tbody>
            </table>

            <div class="summary">
                <div class="summary-box">
                    <div class="summary-row">
                        <span>Subtotal:</span>
                        <span>₹{invoice.amount:,.2f}</span>
                    </div>
                    <div class="summary-row">
                        <span>{discount_label}:</span>
                        <span>-₹{discount_amount:,.2f}</span>
                    </div>
                    <div class="summary-total">
                        <span>Grand Total:</span>
                        <span>₹{final_total:,.2f}</span>
                    </div>
                </div>
            </div>

            <div class="footer">
                <p>Thank you for your business!</p>
                <p>This is a computer-generated invoice. No signature required.</p>
                <p>{escape(business['name'])} - Tax Consultant</p>
            </div>
        </div>
        <script>
            window.onload = function() {{
                window.print();
            }};
        </script>
    </body>
    </html>
    """
    
    # Create a BytesIO object
    file_data = BytesIO(html_content.encode('utf-8'))
    
    return send_file(
        file_data,
        mimetype='text/html',
        as_attachment=True,
        download_name=f'{invoice.invoice_number}.html'
    )

def print_invoice(invoice_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    current_user = get_user(session['user_id'])
    invoice = active_invoice_or_404(invoice_id)
    if not invoice_allowed_for_user(invoice, current_user):
        return jsonify({'error': 'Unauthorized'}), 403

    client = invoice_client_details(invoice)
    detail_rows = ''.join(
        f'<tr><th>{label}</th><td>{escape(value)}</td></tr>'
        for label, value in (
            ('Client Name', client['name']),
            ('Email', client['email']),
            ('PAN', client['pan']),
            ('Phone', client['phone'])
        )
    )
    business = invoice_business_details()
    logo_url = url_for(
        'static', filename='images/tushar-borse-and-co-logo.jpeg'
    )
    discount_amount = Decimal(str(invoice.discount_amount or 0))
    discount_label = escape(invoice_discount_label(invoice))
    total = invoice_total(invoice)
    html_content = f"""<!doctype html>
    <html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="application-name" content="Tushar Borse And Co.">
    <title>Tushar Borse And Co. | Invoice {escape(invoice.invoice_number)}</title>
    <link rel="icon" type="image/jpeg" href="{logo_url}">
    <style>
      body{{font-family:Arial,sans-serif;color:#202020;margin:32px;background:#F7F7F8}}
      main{{max-width:800px;margin:auto;padding:28px;background:#fff;border:1px solid #E8E8E8;border-radius:12px;box-shadow:0 12px 32px rgba(0,0,0,.08)}}header{{display:flex;align-items:center;justify-content:space-between;gap:18px;border-bottom:3px solid #C90016;padding-bottom:16px}}
      .invoice-brand{{display:flex;align-items:center;gap:12px;min-width:0}}.invoice-brand img{{width:110px;max-width:30%;height:auto;object-fit:contain}}
      h1{{margin:0}}table{{width:100%;border-collapse:collapse;margin:24px 0}}
      th,td{{border:1px solid #E8E8E8;padding:12px;text-align:left}}th{{background:#FAF1F2;color:#171717}}
      .total{{font-size:20px;font-weight:bold;text-align:right;color:#A80012}}button{{padding:10px 18px;background:linear-gradient(120deg,#C90016,#A80012);color:white;border:0;border-radius:7px;cursor:pointer}}
      @media print{{button{{display:none}}body{{margin:0;padding:0;background:#fff}}main{{max-width:none;padding:0;border:0;border-radius:0;box-shadow:none}}}}
      @media (max-width:560px){{body{{margin:12px}}main{{padding:18px}}header{{align-items:flex-start;flex-direction:column}}.invoice-brand{{gap:8px}}.invoice-brand img{{width:75px}}h1{{font-size:18px}}}}
    </style></head><body><main>
      <header><div class="invoice-brand"><img src="{logo_url}" alt="Tushar Borse And Co. — Tax Consultant"><div>
      <h1>{escape(business['name'])}</h1><p>Tax Consultant</p></div></div>
      <div><h2>INVOICE</h2><p>{escape(invoice.invoice_number)}</p><p>{invoice.date:%d-%m-%Y}</p></div></header>
      <h3>Bill To</h3><table>{detail_rows}</table>
      <table><tr><th>Description</th><th>Amount</th></tr>
      <tr><td>{escape(invoice.service_description)}</td><td>₹{invoice.amount:,.2f}</td></tr></table>
      <table><tr><th>Subtotal</th><td>₹{invoice.amount:,.2f}</td></tr>
      <tr><th>{discount_label}</th><td>-₹{discount_amount:,.2f}</td></tr>
      <tr><th>Grand Total</th><td>₹{total:,.2f}</td></tr></table>
      <p>Payment Status: {escape(invoice.status.upper())}</p>
      <p class="total">Grand Total: ₹{total:,.2f}</p>
      <button onclick="window.print()">Print Invoice</button>
    </main></body></html>"""
    return make_response(html_content)

def invoice_pdf(invoice_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    current_user = get_user(session['user_id'])
    invoice = active_invoice_or_404(invoice_id)
    if not invoice_allowed_for_user(invoice, current_user):
        return jsonify({'error': 'Unauthorized'}), 403

    client = invoice_client_details(invoice)
    business = invoice_business_details()
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm
    )
    styles = getSampleStyleSheet()
    story = []
    if business['logo_path'] and os.path.isfile(business['logo_path']):
        try:
            story.append(Image(
                business['logo_path'], width=38 * mm, height=25 * mm,
                kind='proportional'
            ))
        except (OSError, ValueError):
            app.logger.exception('Configured invoice logo could not be read.')
    story.extend([
        Paragraph(escape(business['name']), styles['Title']),
        Paragraph('Tax Consultant', styles['Normal']),
        Spacer(1, 5 * mm),
        Paragraph('INVOICE', styles['Heading1']),
        Paragraph(f'Invoice Number: {escape(invoice.invoice_number)}', styles['Normal']),
        Paragraph(f'Invoice Date: {invoice.date:%d-%m-%Y}', styles['Normal']),
        Spacer(1, 6 * mm),
        Paragraph('Bill To', styles['Heading2'])
    ])
    client_table = Table([
        ['Client Name', client['name']],
        ['Email', client['email']],
        ['PAN Number', client['pan']],
        ['Phone', client['phone']]
    ], colWidths=[42 * mm, 118 * mm])
    client_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#FAF1F2')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E8E8E8')),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'TOP')
    ]))
    story.extend([client_table, Spacer(1, 8 * mm)])
    discount_amount = Decimal(str(invoice.discount_amount or 0))
    invoice_table = Table([
        ['Description', 'Amount'],
        [Paragraph(escape(invoice.service_description), styles['Normal']), f'INR {invoice.amount:,.2f}'],
        ['Subtotal', f'INR {invoice.amount:,.2f}'],
        [invoice_discount_label(invoice), f'-INR {discount_amount:,.2f}'],
        ['Grand Total', f'INR {invoice_total(invoice):,.2f}'],
        ['Payment Status', invoice.status.upper()]
    ], colWidths=[110 * mm, 50 * mm])
    invoice_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#171717')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E8E8E8')),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 4), (-1, 4), 'Helvetica-Bold')
    ]))
    story.extend([invoice_table, Spacer(1, 8 * mm), Paragraph('Thank you for your business.', styles['Normal'])])
    document.build(story)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'{invoice.invoice_number}.pdf'
    )


def _authorized_invoice_pdf(invoice_id, as_attachment):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    current_user = get_user(session['user_id'])
    invoice = active_invoice_or_404(invoice_id)
    if current_user is None or not invoice_allowed_for_user(invoice, current_user):
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        pdf_bytes = get_invoice_pdf(invoice)
    except (OSError, ValueError):
        app.logger.exception('Could not read invoice PDF %s', invoice_id)
        return jsonify({'error': 'Invoice PDF is unavailable; contact an administrator'}), 500
    return send_file(
        BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=as_attachment,
        download_name=f'{invoice.invoice_number}.pdf',
        conditional=False
    )


@app.route('/api/invoices/<int:invoice_id>/download')
def download_invoice_pdf(invoice_id):
    return _authorized_invoice_pdf(invoice_id, True)


@app.route('/api/invoices/<int:invoice_id>/pdf')
def invoice_pdf_download(invoice_id):
    return _authorized_invoice_pdf(invoice_id, True)


@app.route('/api/invoices/<int:invoice_id>/preview')
def preview_invoice_pdf(invoice_id):
    return _authorized_invoice_pdf(invoice_id, False)


@app.route('/api/invoices/<int:invoice_id>/print')
def print_invoice_preview(invoice_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    current_user = get_user(session['user_id'])
    invoice = active_invoice_or_404(invoice_id)
    if current_user is None or not invoice_allowed_for_user(invoice, current_user):
        return jsonify({'error': 'Unauthorized'}), 403

    client = invoice_client_details(invoice)
    business = invoice_business_details()
    logo_url = url_for(
        'static', filename='images/tushar-borse-and-co-logo.jpeg'
    )
    total = invoice_total(invoice)
    discount_amount = Decimal(str(invoice.discount_amount or 0))
    discount_label = escape(invoice_discount_label(invoice))
    received = invoice_received(invoice)
    balance = max(total - received, Decimal('0.00'))
    business_details = ''.join(
        f'<p>{escape(value)}</p>'
        for value in (business['address'], business['mobile'], business['email'])
        if value
    )
    payment_details = ''.join(
        f'<tr><th>{escape(label)}</th><td>{escape(value)}</td></tr>'
        for label, value in INVOICE_PAYMENT_DETAILS
    )
    payment_app_logos = ''.join(
        f'<span class="payment-app"><img src="{url_for("static", filename="images/" + app_filename)}" '
        f'alt="{escape(app_name)} logo"><span>{escape(app_name)}</span></span>'
        for app_name, app_filename in INVOICE_PAYMENT_APPS
    )
    upi_cards = ''.join(
        f'<article class="upi-card"><h4>{escape(bank_name)}</h4>'
        f'<img class="qr-code" src="{url_for("static", filename="images/" + filename)}" '
        f'alt="{escape(bank_name)} UPI payment QR code">'
        f'<div class="payment-app-logos" aria-label="Accepted payment apps">{payment_app_logos}</div>'
        f'<p><span>UPI ID</span><strong>{escape(upi_id)}</strong></p></article>'
        for bank_name, upi_id, filename in INVOICE_UPI_ACCOUNTS
    )
    signature_url = url_for('static', filename='images/tbsign-invoice.png')
    stamp_url = url_for('static', filename='images/tbstamp-invoice.png')
    html_content = f"""<!doctype html>
    <html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="application-name" content="Tushar Borse And Co.">
    <title>Invoice {escape(invoice.invoice_number)}</title>
    <link rel="icon" type="image/jpeg" href="{logo_url}">
    <style>
      *{{box-sizing:border-box}}body{{margin:0;padding:32px;background:#F7F7F8;color:#202020;font:14px/1.5 Arial,sans-serif}}
      main{{max-width:900px;margin:auto;padding:34px;background:#fff;border:1px solid #E8E8E8;border-radius:14px;box-shadow:0 14px 36px rgba(0,0,0,.08)}}
      header{{display:flex;justify-content:space-between;gap:24px;padding-bottom:22px;border-bottom:3px solid #C90016}}
      .invoice-brand{{display:flex;align-items:center;gap:14px;min-width:0}}
      .invoice-brand img{{display:block;width:125px;max-width:34vw;height:auto;object-fit:contain}}
      h1{{margin:0;color:#171717;font-size:25px}}h2{{margin:0;color:#A80012;text-align:right}}p{{margin:5px 0;color:#777}}
      .original{{display:inline-block;margin-top:8px;padding:4px 9px;border-radius:20px;background:#FAF1F2;color:#A80012;font-size:11px}}
      h3{{margin:24px 0 10px;color:#171717;font-size:13px;text-transform:uppercase;letter-spacing:.06em}}
      table{{width:100%;border-collapse:collapse;margin:15px 0}}th,td{{padding:10px 12px;border:1px solid #E8E8E8;text-align:left}}
      th{{background:#FAF1F2;color:#171717}}.items th{{background:#171717;color:white}}.right{{text-align:right}}
      .summary{{width:min(360px,100%);margin-left:auto}}.grand{{background:#FAF1F2;color:#A80012;font-size:17px;font-weight:bold}}
      .words{{padding:12px;background:#F7F7F8;color:#777}}footer{{margin-top:26px;padding-top:18px;border-top:1px solid #E8E8E8;color:#777;text-align:center}}
      .payment-layout{{display:grid;grid-template-columns:minmax(260px,.78fr) minmax(0,1.22fr);gap:16px;align-items:stretch}}
      .bank-card,.upi-panel,.shop-address,.authorization-card{{min-width:0;padding:15px;border:1px solid #E8E8E8;border-radius:11px;background:#fff}}
      .bank-card h4,.upi-panel h4,.authorization-card h4{{margin:0 0 10px;color:#171717;font-size:13px}}
      .bank-card table{{margin:0;font-size:12px}}
      .bank-card th,.bank-card td{{padding:7px 8px;overflow-wrap:anywhere}}
      .bank-card th{{width:42%;color:#555;background:#FAF1F2}}
      .upi-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}
      .upi-card{{display:flex;min-width:0;flex-direction:column;align-items:center;justify-content:flex-start;gap:7px;padding:10px 7px;border:1px solid #E8E8E8;border-radius:9px;text-align:center}}
      .upi-card h4{{margin:0;color:#A80012;font-size:13px}}
      .upi-card img{{display:block;width:min(100%,185px);height:auto;object-fit:contain}}
      .upi-card .qr-code{{width:min(100%,160px);aspect-ratio:1/1;background:#fff}}
      .payment-app-logos{{display:flex;align-items:flex-start;justify-content:center;gap:9px;width:100%}}
      .payment-app{{display:flex;min-width:0;flex-direction:column;align-items:center;gap:2px;color:#777;font-size:8px;line-height:1.1}}
      .upi-card .payment-app img{{width:26px;height:18px;object-fit:contain}}
      .upi-card p{{display:grid;gap:2px;max-width:100%;margin:0;font-size:10px;overflow-wrap:anywhere}}
      .upi-card p span{{color:#777}}.upi-card p strong{{color:#202020;font-size:11px;font-weight:600;overflow-wrap:anywhere}}
      .invoice-closing{{display:grid;grid-template-columns:minmax(0,.92fr) minmax(0,1.08fr);gap:14px;margin-top:14px}}
      .shop-address h3,.authorization-card h3{{margin:0 0 8px;color:#171717;font-size:12px}}
      .shop-address p{{margin:0;color:#555;line-height:1.6}}
      .authorization-card{{display:flex;flex-direction:column;justify-content:space-between}}
      .authorization-card>p{{margin:0 0 7px;color:#777;font-size:11px}}
      .authorization-assets{{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,.8fr);align-items:end;gap:10px}}
      .authorization-assets figure{{display:flex;min-width:0;height:62px;flex-direction:column;align-items:center;justify-content:space-between;margin:0}}
      .authorization-assets img{{display:block;max-width:100%;height:43px;object-fit:contain}}
      .authorization-assets figcaption{{color:#777;font-size:9px}}
      button{{margin-bottom:20px;padding:10px 16px;border:0;border-radius:8px;background:linear-gradient(120deg,#C90016,#A80012);color:white;font-weight:bold;cursor:pointer}}
      @media print{{@page{{margin:12mm}}body{{padding:0;background:#fff}}main{{max-width:none;padding:0;border:0;border-radius:0;box-shadow:none}}button{{display:none}}.payment-layout,.invoice-closing{{break-inside:avoid}}.bank-card,.upi-panel,.shop-address,.authorization-card,.upi-card{{break-inside:avoid}}}}
      @media (max-width:700px){{body{{padding:12px}}main{{padding:18px}}header{{flex-direction:column;gap:12px}}.invoice-brand img{{width:90px}}header>div:last-child{{text-align:left}}h2{{text-align:left}}.payment-layout,.invoice-closing{{grid-template-columns:minmax(0,1fr)}}}}
      @media (max-width:420px){{.upi-grid{{gap:6px}}.upi-card{{gap:5px;padding:7px 4px}}.upi-card img{{width:100%}}.upi-card .payment-app img{{width:22px;height:16px}}.payment-app-logos{{gap:4px}}.payment-app{{font-size:7px}}.upi-card p strong{{font-size:10px}}.authorization-assets{{grid-template-columns:minmax(0,1.3fr) minmax(0,.8fr)}}table{{font-size:12px}}th,td{{padding:8px}}}}
    </style></head><body><main>
      <button onclick="window.print()">Print Invoice</button>
      <header><div class="invoice-brand"><img src="{logo_url}" alt="Tushar Borse And Co. — Tax Consultant"><div>
      <h1>{escape(business['name'])}</h1><p>Tax Consultant</p>{business_details}</div></div>
      <div><h2>TAX INVOICE</h2><p>Invoice No.: <strong>{escape(invoice.invoice_number)}</strong></p>
      <p>Date: <strong>{invoice.date:%d %b %Y}</strong></p><span class="original">Original for Recipient</span></div></header>
      <h3>Bill To</h3><table><tr><th>Client Name</th><td>{escape(client['name'])}</td><th>Mobile</th><td>{escape(client['phone'])}</td></tr>
      <tr><th>Email</th><td>{escape(client['email'])}</td><th>PAN</th><td>{escape(client['pan'])}</td></tr></table>
      <table class="items"><thead><tr><th>Service Description</th><th>Quantity</th><th class="right">Amount (INR)</th></tr></thead>
      <tbody><tr><td>{escape(invoice.service_description)}</td><td>1</td><td class="right">{invoice.amount:,.2f}</td></tr></tbody></table>
      <table class="summary"><tr><th>Subtotal</th><td class="right">INR {invoice.amount:,.2f}</td></tr>
      <tr><th>{discount_label}</th><td class="right">-INR {discount_amount:,.2f}</td></tr>
      <tr class="grand"><th>Grand Total</th><td class="right">INR {total:,.2f}</td></tr>
      <tr><th>Received Amount</th><td class="right">INR {received:,.2f}</td></tr>
      <tr><th>Balance Amount</th><td class="right">INR {balance:,.2f}</td></tr></table>
      <p class="words"><strong>Amount in Words:</strong> {escape(amount_in_words(total))}</p>
      <h3>Payment Details</h3>
      <section class="payment-layout" aria-label="Bank and UPI payment details">
        <div class="bank-card"><h4>IDBI Bank Account</h4><table>{payment_details}</table></div>
        <div class="upi-panel"><h4>Pay by UPI</h4><div class="upi-grid">{upi_cards}</div></div>
      </section>
      <section class="invoice-closing">
        <div class="shop-address"><h3>Shop Address</h3><p>{escape(INVOICE_SHOP_ADDRESS)}</p></div>
        <div class="authorization-card"><h3>Authorised Signature &amp; Company Stamp</h3>
          <p>For {escape(business['name'])}</p>
          <div class="authorization-assets">
            <figure><img src="{signature_url}" alt="Original authorised signature"><figcaption>Authorised Signature</figcaption></figure>
            <figure><img src="{stamp_url}" alt="Original company stamp"><figcaption>Company Stamp</figcaption></figure>
          </div>
        </div>
      </section>
      <footer>Thank you for choosing our professional services.<br>This is a computer-generated invoice.</footer>
    </main></body></html>"""
    response = make_response(html_content)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

if __name__ == '__main__':
    app.run(debug=True)