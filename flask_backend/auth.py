from flask import Blueprint, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from models import get_db
import os
from config import WORKSPACES_DIR

auth_bp = Blueprint('auth', __name__)


def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return user


def login_required(f):
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required'}), 401
        return f(user, *args, **kwargs)

    return decorated


@auth_bp.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')

    if not username or not email or not password:
        return jsonify({'error': 'All fields are required'}), 400

    if len(username) < 3:
        return jsonify({'error': 'Username must be at least 3 characters'}), 400

    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    conn = get_db()
    existing = conn.execute(
        'SELECT id FROM users WHERE username = ? OR email = ?',
        (username, email)
    ).fetchone()

    if existing:
        conn.close()
        return jsonify({'error': 'Username or email already exists'}), 409

    password_hash = generate_password_hash(password)
    cursor = conn.execute(
        'INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)',
        (username, email, password_hash)
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Create user workspace directory
    user_workspace = os.path.join(WORKSPACES_DIR, str(user_id))
    os.makedirs(user_workspace, exist_ok=True)

    session['user_id'] = user_id
    session.permanent = True

    # Seed sample project for new user
    try:
        from seed_sample import seed_sample_project
        seed_sample_project(user_id)
    except Exception as e:
        print(f"Warning: Could not seed sample project: {e}")

    return jsonify({
        'message': 'Registration successful',
        'user': {'id': user_id, 'username': username, 'email': email}
    }), 201


@auth_bp.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'error': 'Username and password are required'}), 400

    conn = get_db()
    user = conn.execute(
        'SELECT * FROM users WHERE username = ? OR email = ?',
        (username, username)
    ).fetchone()
    conn.close()

    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({'error': 'Invalid credentials'}), 401

    session['user_id'] = user['id']
    session.permanent = True

    # Ensure workspace exists
    user_workspace = os.path.join(WORKSPACES_DIR, str(user['id']))
    os.makedirs(user_workspace, exist_ok=True)

    return jsonify({
        'message': 'Login successful',
        'user': {
            'id': user['id'],
            'username': user['username'],
            'email': user['email']
        }
    })


@auth_bp.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Logged out successfully'})


@auth_bp.route('/api/auth/me', methods=['GET'])
def me():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401
    return jsonify({
        'user': {
            'id': user['id'],
            'username': user['username'],
            'email': user['email']
        }
    })


@auth_bp.route('/api/auth/delete-account', methods=['POST'])
def delete_account():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401

    data = request.get_json()
    password = data.get('password', '')

    if not password:
        return jsonify({'error': 'Password is required'}), 400

    # Verify password
    if not check_password_hash(user['password_hash'], password):
        return jsonify({'error': 'Incorrect password'}), 403

    user_id = user['id']
    import shutil

    conn = get_db()
    try:
        # Delete all user data from database
        conn.execute('DELETE FROM deployments WHERE user_id = ?', (user_id,))
        conn.execute('DELETE FROM ai_conversations WHERE user_id = ?', (user_id,))
        conn.execute('DELETE FROM api_keys WHERE user_id = ?', (user_id,))
        conn.execute('DELETE FROM files WHERE project_id IN (SELECT id FROM projects WHERE user_id = ?)', (user_id,))
        conn.execute('DELETE FROM projects WHERE user_id = ?', (user_id,))
        conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({'error': f'Failed to delete account data: {str(e)}'}), 500
    finally:
        conn.close()

    # Delete user workspace directory
    user_workspace = os.path.join(WORKSPACES_DIR, str(user_id))
    if os.path.exists(user_workspace):
        try:
            shutil.rmtree(user_workspace)
        except Exception as e:
            print(f"Warning: Could not delete workspace for user {user_id}: {e}")

    # Clear session
    session.clear()

    return jsonify({'message': 'Account deleted successfully'})
