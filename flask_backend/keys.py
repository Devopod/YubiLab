from flask import Blueprint, request, jsonify
from auth import login_required
from models import get_db
from werkzeug.security import generate_password_hash, check_password_hash
import secrets

keys_bp = Blueprint('keys', __name__)


def generate_api_key():
    """Generate a random API key with yubi- prefix."""
    raw = secrets.token_hex(24)
    return f"yubi-{raw}"


@keys_bp.route('/api/keys', methods=['GET'])
@login_required
def list_keys(user):
    conn = get_db()
    keys = conn.execute(
        'SELECT id, key_name, key_prefix, usage_count, created_at FROM api_keys WHERE user_id = ? ORDER BY created_at DESC',
        (user['id'],)
    ).fetchall()
    conn.close()
    return jsonify([dict(k) for k in keys])


@keys_bp.route('/api/keys', methods=['POST'])
@login_required
def create_key(user):
    data = request.get_json()
    key_name = data.get('key_name', '').strip()
    if not key_name:
        return jsonify({'error': 'Key name is required'}), 400

    api_key = generate_api_key()
    key_hash = generate_password_hash(api_key)
    key_prefix = api_key[:10]

    conn = get_db()
    conn.execute(
        'INSERT INTO api_keys (user_id, key_name, key_hash, key_prefix) VALUES (?, ?, ?, ?)',
        (user['id'], key_name, key_hash, key_prefix)
    )
    conn.commit()
    conn.close()

    return jsonify({
        'api_key': api_key,
        'key_name': key_name,
        'key_prefix': key_prefix,
        'message': 'API key created successfully'
    }), 201


@keys_bp.route('/api/keys/<int:key_id>', methods=['DELETE'])
@login_required
def delete_key(user, key_id):
    conn = get_db()
    conn.execute(
        'DELETE FROM api_keys WHERE id = ? AND user_id = ?',
        (key_id, user['id'])
    )
    conn.commit()
    conn.close()
    return jsonify({'message': 'API key deleted'})
