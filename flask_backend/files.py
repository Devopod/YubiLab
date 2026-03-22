from flask import Blueprint, request, jsonify
from auth import login_required
from models import get_db
import os
from config import WORKSPACES_DIR

files_bp = Blueprint('files', __name__)


def get_project_path(user_id, project_name):
    safe_name = project_name.replace('..', '').replace('/', '_').replace('\\', '_')
    return os.path.join(WORKSPACES_DIR, str(user_id), safe_name)


def validate_path(base_path, target_path):
    """Ensure the target path is within the base path (prevent directory traversal)."""
    real_base = os.path.realpath(base_path)
    real_target = os.path.realpath(target_path)
    return real_target.startswith(real_base)


def build_file_tree(path, base_path=""):
    """Recursively build a file tree structure."""
    tree = []
    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return tree

    dirs = []
    files = []

    for entry in entries:
        if entry.startswith('.'):
            continue
        full_path = os.path.join(path, entry)
        rel_path = os.path.join(base_path, entry) if base_path else entry

        if os.path.isdir(full_path):
            dirs.append({
                'name': entry,
                'path': rel_path,
                'type': 'directory',
                'children': build_file_tree(full_path, rel_path)
            })
        else:
            size = os.path.getsize(full_path)
            files.append({
                'name': entry,
                'path': rel_path,
                'type': 'file',
                'size': size
            })

    return dirs + files


@files_bp.route('/api/projects/<int:project_id>/files', methods=['GET'])
@login_required
def get_files(user, project_id):
    conn = get_db()
    project = conn.execute(
        'SELECT * FROM projects WHERE id = ? AND user_id = ?',
        (project_id, user['id'])
    ).fetchone()
    conn.close()

    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = get_project_path(user['id'], project['name'])
    if not os.path.exists(project_path):
        os.makedirs(project_path, exist_ok=True)

    tree = build_file_tree(project_path)
    return jsonify({'files': tree, 'project': project['name']})


@files_bp.route('/api/projects/<int:project_id>/files/content', methods=['GET'])
@login_required
def get_file_content(user, project_id):
    file_path = request.args.get('path', '')
    if not file_path:
        return jsonify({'error': 'File path is required'}), 400

    conn = get_db()
    project = conn.execute(
        'SELECT * FROM projects WHERE id = ? AND user_id = ?',
        (project_id, user['id'])
    ).fetchone()
    conn.close()

    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = get_project_path(user['id'], project['name'])
    full_path = os.path.join(project_path, file_path)

    if not validate_path(project_path, full_path):
        return jsonify({'error': 'Invalid file path'}), 403

    if not os.path.isfile(full_path):
        return jsonify({'error': 'File not found'}), 404

    try:
        with open(full_path, 'r', errors='replace') as f:
            content = f.read()
        return jsonify({'content': content, 'path': file_path})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@files_bp.route('/api/projects/<int:project_id>/files/save', methods=['POST'])
@login_required
def save_file(user, project_id):
    data = request.get_json()
    file_path = data.get('path', '')
    content = data.get('content', '')

    if not file_path:
        return jsonify({'error': 'File path is required'}), 400

    conn = get_db()
    project = conn.execute(
        'SELECT * FROM projects WHERE id = ? AND user_id = ?',
        (project_id, user['id'])
    ).fetchone()

    if not project:
        conn.close()
        return jsonify({'error': 'Project not found'}), 404

    # Update project timestamp
    conn.execute(
        'UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?',
        (project_id,)
    )
    conn.commit()
    conn.close()

    project_path = get_project_path(user['id'], project['name'])
    full_path = os.path.join(project_path, file_path)

    if not validate_path(project_path, full_path):
        return jsonify({'error': 'Invalid file path'}), 403

    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w') as f:
            f.write(content)
        return jsonify({'message': 'File saved', 'path': file_path})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@files_bp.route('/api/projects/<int:project_id>/files/create', methods=['POST'])
@login_required
def create_file(user, project_id):
    data = request.get_json()
    file_path = data.get('path', '')
    file_type = data.get('type', 'file')  # 'file' or 'directory'

    if not file_path:
        return jsonify({'error': 'Path is required'}), 400

    conn = get_db()
    project = conn.execute(
        'SELECT * FROM projects WHERE id = ? AND user_id = ?',
        (project_id, user['id'])
    ).fetchone()
    conn.close()

    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = get_project_path(user['id'], project['name'])
    full_path = os.path.join(project_path, file_path)

    if not validate_path(project_path, full_path):
        return jsonify({'error': 'Invalid path'}), 403

    if os.path.exists(full_path):
        return jsonify({'error': 'Path already exists'}), 409

    try:
        if file_type == 'directory':
            os.makedirs(full_path, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w') as f:
                f.write('')
        return jsonify({'message': f'{file_type.capitalize()} created', 'path': file_path})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@files_bp.route('/api/projects/<int:project_id>/files/delete', methods=['POST'])
@login_required
def delete_file(user, project_id):
    data = request.get_json()
    file_path = data.get('path', '')

    if not file_path:
        return jsonify({'error': 'Path is required'}), 400

    conn = get_db()
    project = conn.execute(
        'SELECT * FROM projects WHERE id = ? AND user_id = ?',
        (project_id, user['id'])
    ).fetchone()
    conn.close()

    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = get_project_path(user['id'], project['name'])
    full_path = os.path.join(project_path, file_path)

    if not validate_path(project_path, full_path):
        return jsonify({'error': 'Invalid path'}), 403

    if not os.path.exists(full_path):
        return jsonify({'error': 'Path not found'}), 404

    try:
        import shutil
        if os.path.isdir(full_path):
            shutil.rmtree(full_path)
        else:
            os.remove(full_path)
        return jsonify({'message': 'Deleted successfully', 'path': file_path})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@files_bp.route('/api/projects/<int:project_id>/files/rename', methods=['POST'])
@login_required
def rename_file(user, project_id):
    data = request.get_json()
    old_path = data.get('old_path', '')
    new_path = data.get('new_path', '')

    if not old_path or not new_path:
        return jsonify({'error': 'Both old and new paths are required'}), 400

    conn = get_db()
    project = conn.execute(
        'SELECT * FROM projects WHERE id = ? AND user_id = ?',
        (project_id, user['id'])
    ).fetchone()
    conn.close()

    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = get_project_path(user['id'], project['name'])
    full_old = os.path.join(project_path, old_path)
    full_new = os.path.join(project_path, new_path)

    if not validate_path(project_path, full_old) or not validate_path(project_path, full_new):
        return jsonify({'error': 'Invalid path'}), 403

    if not os.path.exists(full_old):
        return jsonify({'error': 'Source path not found'}), 404

    if os.path.exists(full_new):
        return jsonify({'error': 'Destination already exists'}), 409

    try:
        os.makedirs(os.path.dirname(full_new), exist_ok=True)
        os.rename(full_old, full_new)
        return jsonify({'message': 'Renamed successfully', 'old_path': old_path, 'new_path': new_path})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
