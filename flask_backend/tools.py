"""YubiLab Tools — Replit-like developer tools for the IDE.
Package manager, SQL executor, code search, workflow manager, secrets checker."""

from flask import Blueprint, request, jsonify
from auth import login_required
from models import get_db
from config import WORKSPACES_DIR
import os
import subprocess
import json
import re
import sqlite3
import glob as glob_mod

tools_bp = Blueprint('tools', __name__)


def _get_project_path(user_id, project_name):
    safe_name = project_name.replace('..', '').replace('/', '_').replace('\\', '_')
    return os.path.join(WORKSPACES_DIR, str(user_id), safe_name)


def _get_project_for_user(user, project_id):
    conn = get_db()
    project = conn.execute(
        'SELECT * FROM projects WHERE id = ? AND user_id = ?',
        (project_id, user['id'])
    ).fetchone()
    conn.close()
    return project


# ══════════════════════════════════════════════════════════════
# 1. PACKAGE MANAGER — install/uninstall packages (pip, npm, etc.)
# ══════════════════════════════════════════════════════════════

@tools_bp.route('/api/tools/packages', methods=['POST'])
@login_required
def package_manager(user):
    """Install or uninstall packages for a project."""
    data = request.get_json()
    project_id = data.get('project_id')
    action = data.get('action', 'install')  # install | uninstall
    language = data.get('language', 'python')  # python | nodejs | system
    packages = data.get('packages', [])

    if not project_id or not packages:
        return jsonify({'error': 'project_id and packages are required'}), 400

    project = _get_project_for_user(user, project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = _get_project_path(user['id'], project['name'])

    results = []
    overall_success = True

    for pkg in packages:
        # Sanitize package name (prevent command injection)
        pkg = re.sub(r'[;&|`$(){}]', '', pkg).strip()
        if not pkg:
            continue

        if language == 'python':
            cmd = f'pip install {pkg}' if action == 'install' else f'pip uninstall -y {pkg}'
        elif language == 'nodejs':
            cmd = f'npm install {pkg}' if action == 'install' else f'npm uninstall {pkg}'
        else:
            results.append({'package': pkg, 'success': False, 'output': 'Unsupported language'})
            overall_success = False
            continue

        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=project_path,
                capture_output=True, text=True, timeout=120
            )
            success = proc.returncode == 0
            output = proc.stdout[-500:] if proc.stdout else ''
            if proc.stderr and not success:
                output += '\n' + proc.stderr[-500:]
            results.append({'package': pkg, 'success': success, 'output': output.strip()})
            if not success:
                overall_success = False
        except subprocess.TimeoutExpired:
            results.append({'package': pkg, 'success': False, 'output': 'Installation timed out (120s)'})
            overall_success = False
        except Exception as e:
            results.append({'package': pkg, 'success': False, 'output': str(e)})
            overall_success = False

    # Update requirements.txt if python
    if language == 'python' and action == 'install' and overall_success:
        try:
            proc = subprocess.run(
                'pip freeze', shell=True, cwd=project_path,
                capture_output=True, text=True, timeout=30
            )
            if proc.returncode == 0:
                req_path = os.path.join(project_path, 'requirements.txt')
                with open(req_path, 'w') as f:
                    f.write(proc.stdout)
        except Exception:
            pass

    return jsonify({
        'success': overall_success,
        'action': action,
        'language': language,
        'results': results
    })


# ══════════════════════════════════════════════════════════════
# 2. SQL EXECUTION TOOL — run SQL queries on project databases
# ══════════════════════════════════════════════════════════════

@tools_bp.route('/api/tools/sql', methods=['POST'])
@login_required
def execute_sql(user):
    """Execute SQL queries on a project's SQLite database."""
    data = request.get_json()
    project_id = data.get('project_id')
    sql_query = data.get('query', '').strip()
    db_name = data.get('db_name', '')  # optional: specific db file

    if not project_id or not sql_query:
        return jsonify({'error': 'project_id and query are required'}), 400

    # Block dangerous operations
    sql_upper = sql_query.upper().strip()
    if any(sql_upper.startswith(cmd) for cmd in ['DROP DATABASE', 'DROP SCHEMA']):
        return jsonify({'error': 'Dangerous operation blocked'}), 403

    project = _get_project_for_user(user, project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = _get_project_path(user['id'], project['name'])

    # Find SQLite database files in the project
    db_files = []
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in ('node_modules', '__pycache__', '.git', 'venv')]
        for f in files:
            if f.endswith(('.db', '.sqlite', '.sqlite3')):
                db_files.append(os.path.relpath(os.path.join(root, f), project_path))

    if not db_files:
        return jsonify({'error': 'No SQLite database found in project', 'databases': []}), 404

    # Use specified db or first found
    target_db = db_name if db_name in db_files else db_files[0]
    db_path = os.path.join(project_path, target_db)

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(sql_query)

        if sql_upper.startswith('SELECT') or sql_upper.startswith('PRAGMA') or sql_upper.startswith('EXPLAIN'):
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            data_rows = [dict(row) for row in rows]
            conn.close()
            return jsonify({
                'success': True,
                'columns': columns,
                'rows': data_rows[:500],  # limit to 500 rows
                'total_rows': len(data_rows),
                'database': target_db,
                'databases': db_files
            })
        else:
            conn.commit()
            affected = cursor.rowcount
            conn.close()
            return jsonify({
                'success': True,
                'affected_rows': affected,
                'message': f'{affected} row(s) affected',
                'database': target_db,
                'databases': db_files
            })
    except sqlite3.Error as e:
        return jsonify({'error': f'SQL error: {str(e)}', 'databases': db_files}), 400
    except Exception as e:
        return jsonify({'error': str(e), 'databases': db_files}), 500


@tools_bp.route('/api/tools/sql/schema', methods=['POST'])
@login_required
def get_db_schema(user):
    """Get the schema of all tables in a project's SQLite database."""
    data = request.get_json()
    project_id = data.get('project_id')
    db_name = data.get('db_name', '')

    if not project_id:
        return jsonify({'error': 'project_id is required'}), 400

    project = _get_project_for_user(user, project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = _get_project_path(user['id'], project['name'])

    # Find database files
    db_files = []
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in ('node_modules', '__pycache__', '.git', 'venv')]
        for f in files:
            if f.endswith(('.db', '.sqlite', '.sqlite3')):
                db_files.append(os.path.relpath(os.path.join(root, f), project_path))

    if not db_files:
        return jsonify({'error': 'No SQLite database found', 'databases': []}), 404

    target_db = db_name if db_name in db_files else db_files[0]
    db_path = os.path.join(project_path, target_db)

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]

        schema = {}
        for table in tables:
            cursor.execute(f"PRAGMA table_info({table})")
            columns = []
            for col in cursor.fetchall():
                columns.append({
                    'cid': col[0], 'name': col[1], 'type': col[2],
                    'notnull': bool(col[3]), 'default': col[4], 'pk': bool(col[5])
                })
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            row_count = cursor.fetchone()[0]
            schema[table] = {'columns': columns, 'row_count': row_count}

        conn.close()
        return jsonify({
            'success': True,
            'database': target_db,
            'databases': db_files,
            'schema': schema
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ══════════════════════════════════════════════════════════════
# 3. CODE SEARCH — search filesystem for code, classes, functions
# ══════════════════════════════════════════════════════════════

@tools_bp.route('/api/tools/search', methods=['POST'])
@login_required
def search_code(user):
    """Search project filesystem for code patterns, functions, classes."""
    data = request.get_json()
    project_id = data.get('project_id')
    query = data.get('query', '').strip()
    search_type = data.get('type', 'text')  # text | function | class | regex
    file_pattern = data.get('file_pattern', '')  # e.g. *.py, *.js

    if not project_id or not query:
        return jsonify({'error': 'project_id and query are required'}), 400

    project = _get_project_for_user(user, project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = _get_project_path(user['id'], project['name'])

    results = []
    skip_dirs = {'node_modules', '__pycache__', '.git', 'venv', 'env', '.venv'}
    skip_exts = {'.pyc', '.pyo', '.class', '.o', '.so', '.db', '.sqlite', '.png', '.jpg', '.gif', '.ico'}
    max_results = 100

    # Build search pattern based on type
    if search_type == 'function':
        # Match function/method definitions across languages
        patterns = [
            rf'def\s+{re.escape(query)}\s*\(',           # Python
            rf'function\s+{re.escape(query)}\s*\(',       # JavaScript
            rf'(const|let|var)\s+{re.escape(query)}\s*=\s*(function|\(|async)',  # JS arrow/const
            rf'(public|private|protected)?\s*(static)?\s*\w+\s+{re.escape(query)}\s*\(',  # Java/C#
        ]
    elif search_type == 'class':
        patterns = [
            rf'class\s+{re.escape(query)}[\s:(]',        # Python/JS/TS
            rf'interface\s+{re.escape(query)}[\s{{]',     # TS/Java
            rf'struct\s+{re.escape(query)}[\s{{]',        # C/Go/Rust
        ]
    elif search_type == 'regex':
        try:
            patterns = [query]
            re.compile(query)  # validate regex
        except re.error:
            return jsonify({'error': 'Invalid regex pattern'}), 400
    else:
        # Plain text search (case-insensitive)
        patterns = [re.escape(query)]

    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in files:
            if len(results) >= max_results:
                break
            ext = os.path.splitext(fname)[1]
            if ext in skip_exts:
                continue
            if file_pattern and not _match_glob(fname, file_pattern):
                continue

            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, project_path)

            try:
                with open(fpath, 'r', errors='replace') as f:
                    lines = f.readlines()
                for i, line in enumerate(lines):
                    if len(results) >= max_results:
                        break
                    for pat in patterns:
                        if re.search(pat, line, re.IGNORECASE if search_type == 'text' else 0):
                            results.append({
                                'file': rel_path,
                                'line': i + 1,
                                'content': line.rstrip()[:200],
                                'match_type': search_type
                            })
                            break
            except Exception:
                continue

    return jsonify({
        'success': True,
        'query': query,
        'type': search_type,
        'results': results,
        'total': len(results),
        'truncated': len(results) >= max_results
    })


def _match_glob(filename, pattern):
    """Simple glob matching for file patterns."""
    import fnmatch
    return fnmatch.fnmatch(filename, pattern)


# ══════════════════════════════════════════════════════════════
# 4. WORKFLOW / RUN CONFIG — configure how projects run
# ══════════════════════════════════════════════════════════════

@tools_bp.route('/api/tools/workflows', methods=['GET'])
@login_required
def list_workflows(user):
    """List all workflows for a project."""
    project_id = request.args.get('project_id')
    if not project_id:
        return jsonify({'error': 'project_id is required'}), 400

    project = _get_project_for_user(user, project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = _get_project_path(user['id'], project['name'])
    config_path = os.path.join(project_path, '.yubilab', 'workflows.json')

    workflows = []
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                workflows = json.load(f)
        except Exception:
            pass

    return jsonify({'success': True, 'workflows': workflows})


@tools_bp.route('/api/tools/workflows', methods=['POST'])
@login_required
def set_workflow(user):
    """Create or update a workflow for a project."""
    data = request.get_json()
    project_id = data.get('project_id')
    name = data.get('name', '').strip()
    command = data.get('command', '').strip()
    wait_for_port = data.get('wait_for_port')
    is_run_button = data.get('is_run_button', False)

    if not project_id or not name or not command:
        return jsonify({'error': 'project_id, name, and command are required'}), 400

    project = _get_project_for_user(user, project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = _get_project_path(user['id'], project['name'])
    config_dir = os.path.join(project_path, '.yubilab')
    config_path = os.path.join(config_dir, 'workflows.json')

    os.makedirs(config_dir, exist_ok=True)

    workflows = []
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                workflows = json.load(f)
        except Exception:
            pass

    # Update or add workflow
    found = False
    for wf in workflows:
        if wf.get('name') == name:
            wf['command'] = command
            wf['wait_for_port'] = wait_for_port
            wf['is_run_button'] = is_run_button
            found = True
            break

    if not found:
        workflows.append({
            'name': name,
            'command': command,
            'wait_for_port': wait_for_port,
            'is_run_button': is_run_button
        })

    # If this is the run button workflow, unset others
    if is_run_button:
        for wf in workflows:
            if wf['name'] != name:
                wf['is_run_button'] = False

    with open(config_path, 'w') as f:
        json.dump(workflows, f, indent=2)

    return jsonify({'success': True, 'workflows': workflows})


@tools_bp.route('/api/tools/workflows', methods=['DELETE'])
@login_required
def remove_workflow(user):
    """Remove a workflow by name."""
    data = request.get_json()
    project_id = data.get('project_id')
    name = data.get('name', '').strip()

    if not project_id or not name:
        return jsonify({'error': 'project_id and name are required'}), 400

    project = _get_project_for_user(user, project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = _get_project_path(user['id'], project['name'])
    config_path = os.path.join(project_path, '.yubilab', 'workflows.json')

    if not os.path.exists(config_path):
        return jsonify({'success': True, 'workflows': []})

    workflows = []
    try:
        with open(config_path) as f:
            workflows = json.load(f)
    except Exception:
        pass

    workflows = [wf for wf in workflows if wf.get('name') != name]

    with open(config_path, 'w') as f:
        json.dump(workflows, f, indent=2)

    return jsonify({'success': True, 'workflows': workflows})


# ══════════════════════════════════════════════════════════════
# 5. SECRETS / ENV VARS — check and manage project env vars
# ══════════════════════════════════════════════════════════════

@tools_bp.route('/api/tools/secrets', methods=['GET'])
@login_required
def list_secrets(user):
    """List all secret/env var names (not values) for a project."""
    project_id = request.args.get('project_id')
    if not project_id:
        return jsonify({'error': 'project_id is required'}), 400

    project = _get_project_for_user(user, project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = _get_project_path(user['id'], project['name'])
    env_path = os.path.join(project_path, '.env')

    secrets = []
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key = line.split('=', 1)[0].strip()
                    secrets.append({'key': key, 'has_value': True})

    return jsonify({'success': True, 'secrets': secrets})


@tools_bp.route('/api/tools/secrets', methods=['POST'])
@login_required
def set_secret(user):
    """Set an environment variable for a project."""
    data = request.get_json()
    project_id = data.get('project_id')
    key = data.get('key', '').strip()
    value = data.get('value', '')

    if not project_id or not key:
        return jsonify({'error': 'project_id and key are required'}), 400

    # Validate key name
    if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', key):
        return jsonify({'error': 'Invalid secret name. Use only letters, numbers, and underscores.'}), 400

    project = _get_project_for_user(user, project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = _get_project_path(user['id'], project['name'])
    env_path = os.path.join(project_path, '.env')

    # Read existing env vars
    env_vars = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env_vars[k.strip()] = v.strip()

    env_vars[key] = value

    # Write back
    with open(env_path, 'w') as f:
        for k, v in env_vars.items():
            f.write(f'{k}={v}\n')

    return jsonify({'success': True, 'message': f'Secret {key} saved'})


@tools_bp.route('/api/tools/secrets', methods=['DELETE'])
@login_required
def delete_secret(user):
    """Delete an environment variable from a project."""
    data = request.get_json()
    project_id = data.get('project_id')
    key = data.get('key', '').strip()

    if not project_id or not key:
        return jsonify({'error': 'project_id and key are required'}), 400

    project = _get_project_for_user(user, project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = _get_project_path(user['id'], project['name'])
    env_path = os.path.join(project_path, '.env')

    if not os.path.exists(env_path):
        return jsonify({'success': True})

    env_vars = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                if k.strip() != key:
                    env_vars[k.strip()] = v.strip()

    with open(env_path, 'w') as f:
        for k, v in env_vars.items():
            f.write(f'{k}={v}\n')

    return jsonify({'success': True, 'message': f'Secret {key} deleted'})


# ══════════════════════════════════════════════════════════════
# 6. PROJECT SHELL — run shell commands in project directory
# ══════════════════════════════════════════════════════════════

@tools_bp.route('/api/tools/shell', methods=['POST'])
@login_required
def run_shell(user):
    """Run a shell command in the project directory. Returns stdout/stderr."""
    data = request.get_json()
    project_id = data.get('project_id')
    command = data.get('command', '').strip()

    if not project_id or not command:
        return jsonify({'error': 'project_id and command are required'}), 400

    # Block dangerous commands
    dangerous = ['rm -rf /', 'mkfs', 'dd if=', ':(){', 'fork bomb']
    if any(d in command.lower() for d in dangerous):
        return jsonify({'error': 'Dangerous command blocked'}), 403

    project = _get_project_for_user(user, project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = _get_project_path(user['id'], project['name'])

    try:
        proc = subprocess.run(
            command, shell=True, cwd=project_path,
            capture_output=True, text=True, timeout=60
        )
        return jsonify({
            'success': proc.returncode == 0,
            'exit_code': proc.returncode,
            'stdout': proc.stdout[-5000:] if proc.stdout else '',
            'stderr': proc.stderr[-2000:] if proc.stderr else ''
        })
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Command timed out (60s)'}), 408
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ══════════════════════════════════════════════════════════════
# 7. PROJECT INFO — get project metadata and stats
# ══════════════════════════════════════════════════════════════

@tools_bp.route('/api/tools/project-info', methods=['GET'])
@login_required
def project_info(user):
    """Get detailed project info: file count, size, languages, dependencies."""
    project_id = request.args.get('project_id')
    if not project_id:
        return jsonify({'error': 'project_id is required'}), 400

    project = _get_project_for_user(user, project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = _get_project_path(user['id'], project['name'])

    file_count = 0
    total_size = 0
    extensions = {}
    skip_dirs = {'node_modules', '__pycache__', '.git', 'venv', 'env', '.venv'}

    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            fpath = os.path.join(root, f)
            file_count += 1
            try:
                total_size += os.path.getsize(fpath)
            except OSError:
                pass
            ext = os.path.splitext(f)[1] or '(no ext)'
            extensions[ext] = extensions.get(ext, 0) + 1

    # Detect dependencies
    deps = {}
    req_path = os.path.join(project_path, 'requirements.txt')
    if os.path.exists(req_path):
        with open(req_path) as f:
            deps['python'] = [l.strip() for l in f if l.strip() and not l.startswith('#')]

    pkg_path = os.path.join(project_path, 'package.json')
    if os.path.exists(pkg_path):
        try:
            with open(pkg_path) as f:
                pkg = json.load(f)
            deps['nodejs'] = list(pkg.get('dependencies', {}).keys())
        except Exception:
            pass

    # Detect databases
    databases = []
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            if f.endswith(('.db', '.sqlite', '.sqlite3')):
                databases.append(os.path.relpath(os.path.join(root, f), project_path))

    return jsonify({
        'success': True,
        'name': project['name'],
        'language': project['language'],
        'file_count': file_count,
        'total_size_bytes': total_size,
        'total_size_human': _human_size(total_size),
        'extensions': extensions,
        'dependencies': deps,
        'databases': databases
    })


def _human_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f'{size_bytes:.1f} {unit}'
        size_bytes /= 1024
    return f'{size_bytes:.1f} TB'


# ══════════════════════════════════════════════════════════════
# 8. DEPLOYMENT CONFIG — configure deploy settings for projects
# ══════════════════════════════════════════════════════════════

@tools_bp.route('/api/tools/deploy-config', methods=['GET'])
@login_required
def get_deploy_config(user):
    """Get deployment configuration for a project."""
    project_id = request.args.get('project_id')
    if not project_id:
        return jsonify({'error': 'project_id is required'}), 400

    project = _get_project_for_user(user, project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = _get_project_path(user['id'], project['name'])
    config_path = os.path.join(project_path, '.yubilab', 'deploy.json')

    config = {
        'run_command': '',
        'install_command': '',
        'build_command': '',
        'port': 3002,
        'env_vars': {},
        'auto_deploy': False
    }

    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                config.update(json.load(f))
        except Exception:
            pass

    return jsonify({'success': True, 'config': config})


@tools_bp.route('/api/tools/deploy-config', methods=['POST'])
@login_required
def set_deploy_config(user):
    """Save deployment configuration for a project."""
    data = request.get_json()
    project_id = data.get('project_id')

    if not project_id:
        return jsonify({'error': 'project_id is required'}), 400

    project = _get_project_for_user(user, project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = _get_project_path(user['id'], project['name'])
    yubilab_dir = os.path.join(project_path, '.yubilab')
    os.makedirs(yubilab_dir, exist_ok=True)
    config_path = os.path.join(yubilab_dir, 'deploy.json')

    config = {
        'run_command': data.get('run_command', ''),
        'install_command': data.get('install_command', ''),
        'build_command': data.get('build_command', ''),
        'port': data.get('port', 3002),
        'env_vars': data.get('env_vars', {}),
        'auto_deploy': data.get('auto_deploy', False)
    }

    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    return jsonify({'success': True, 'config': config, 'message': 'Deploy config saved'})


# ══════════════════════════════════════════════════════════════
# 9. PROGRESS REPORTING — track tool execution progress
# ══════════════════════════════════════════════════════════════

@tools_bp.route('/api/tools/progress', methods=['GET'])
@login_required
def get_progress(user):
    """Get recent tool execution log for a project."""
    project_id = request.args.get('project_id')
    if not project_id:
        return jsonify({'error': 'project_id is required'}), 400

    project = _get_project_for_user(user, project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = _get_project_path(user['id'], project['name'])
    log_path = os.path.join(project_path, '.yubilab', 'tool_log.json')

    entries = []
    if os.path.exists(log_path):
        try:
            with open(log_path) as f:
                entries = json.load(f)
            # Keep last 50 entries
            entries = entries[-50:]
        except Exception:
            pass

    return jsonify({'success': True, 'entries': entries})


@tools_bp.route('/api/tools/progress', methods=['POST'])
@login_required
def log_progress(user):
    """Log a tool execution event."""
    data = request.get_json()
    project_id = data.get('project_id')
    tool = data.get('tool', 'unknown')
    action = data.get('action', '')
    status = data.get('status', 'info')  # info, success, error
    message = data.get('message', '')

    if not project_id:
        return jsonify({'error': 'project_id is required'}), 400

    project = _get_project_for_user(user, project_id)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = _get_project_path(user['id'], project['name'])
    yubilab_dir = os.path.join(project_path, '.yubilab')
    os.makedirs(yubilab_dir, exist_ok=True)
    log_path = os.path.join(yubilab_dir, 'tool_log.json')

    entries = []
    if os.path.exists(log_path):
        try:
            with open(log_path) as f:
                entries = json.load(f)
        except Exception:
            pass

    import datetime
    entries.append({
        'timestamp': datetime.datetime.utcnow().isoformat() + 'Z',
        'tool': tool,
        'action': action,
        'status': status,
        'message': message
    })

    # Keep last 100 entries
    entries = entries[-100:]

    with open(log_path, 'w') as f:
        json.dump(entries, f, indent=2)

    return jsonify({'success': True})
