from flask import Blueprint, request, jsonify
from auth import login_required
from models import get_db
from config import WORKSPACES_DIR
import os
import subprocess
import signal
import socket as sock

deploy_bp = Blueprint('deploy', __name__)


def find_free_port(start=3000, end=9000):
    """Find a free port in the given range."""
    for port in range(start, end):
        try:
            s = sock.socket(sock.AF_INET, sock.SOCK_STREAM)
            s.bind(('127.0.0.1', port))
            s.close()
            return port
        except OSError:
            continue
    return None


def get_project_path(user_id, project_name):
    safe_name = project_name.replace('..', '').replace('/', '_').replace('\\', '_')
    return os.path.join(WORKSPACES_DIR, str(user_id), safe_name)


def detect_run_command(project_path, language):
    """Auto-detect the run command for a project."""
    files = os.listdir(project_path) if os.path.isdir(project_path) else []

    # Check if requirements.txt exists and needs installing
    needs_install = 'requirements.txt' in files
    install_prefix = 'pip install -q -r requirements.txt && ' if needs_install else ''

    if language == 'python' or any(f.endswith('.py') for f in files):
        # Check for Streamlit apps (check file contents for streamlit import)
        for f in files:
            if f.endswith('.py'):
                try:
                    with open(os.path.join(project_path, f), 'r') as fh:
                        content = fh.read()
                        if 'import streamlit' in content or 'from streamlit' in content:
                            return f'{install_prefix}streamlit run {f} --server.port {{port}} --server.address 0.0.0.0 --server.headless true'
                except Exception:
                    pass

        # Check for Flask/Django/FastAPI apps
        if 'app.py' in files:
            return f'{install_prefix}python3 app.py'
        if 'main.py' in files:
            return f'{install_prefix}python3 main.py'
        if 'manage.py' in files:
            return f'{install_prefix}python3 manage.py runserver 0.0.0.0:{{port}}'
        for f in files:
            if f.endswith('.py'):
                return f'{install_prefix}python3 {f}'

    if language == 'javascript' or 'package.json' in files:
        if 'package.json' in files:
            return 'npm install && npm start'
        if 'server.js' in files:
            return 'node server.js'
        if 'index.js' in files:
            return 'node index.js'
        if 'app.js' in files:
            return 'node app.js'

    if language == 'html':
        return 'python3 -m http.server {port}'

    return None


@deploy_bp.route('/api/deploy/<int:project_id>', methods=['POST'])
@login_required
def deploy_project(user, project_id):
    """Deploy a project - works for all stacks."""
    conn = get_db()
    project = conn.execute(
        'SELECT * FROM projects WHERE id = ? AND user_id = ?',
        (project_id, user['id'])
    ).fetchone()

    if not project:
        conn.close()
        return jsonify({'error': 'Project not found'}), 404

    # Kill any existing deployment for this project
    existing = conn.execute(
        'SELECT deploy_pid FROM deployments WHERE project_id = ? AND user_id = ? AND status = ?',
        (project_id, user['id'], 'running')
    ).fetchone()

    if existing and existing['deploy_pid']:
        try:
            os.kill(existing['deploy_pid'], signal.SIGTERM)
        except ProcessLookupError:
            pass
        conn.execute(
            'UPDATE deployments SET status = ? WHERE project_id = ? AND user_id = ? AND status = ?',
            ('stopped', project_id, user['id'], 'running')
        )
        conn.commit()

    project_path = get_project_path(user['id'], project['name'])

    # Find a free port
    port = find_free_port()
    if not port:
        conn.close()
        return jsonify({'error': 'No free ports available'}), 500

    # Detect run command
    data = request.get_json() or {}
    run_command = data.get('run_command', '')
    if not run_command:
        run_command = detect_run_command(project_path, project['language'])

    if not run_command:
        conn.close()
        return jsonify({'error': 'Could not detect run command. Please provide one.'}), 400

    # Replace {port} placeholder
    run_command = run_command.replace('{port}', str(port))

    # For Flask apps, inject PORT env var
    env = os.environ.copy()
    env['PORT'] = str(port)
    env['FLASK_RUN_PORT'] = str(port)
    env['HOST'] = '0.0.0.0'

    try:
        proc = subprocess.Popen(
            run_command,
            shell=True,
            cwd=project_path,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )

        deploy_url = f'/preview-app/{project_id}'

        conn.execute(
            'INSERT INTO deployments (project_id, user_id, deploy_port, deploy_pid, status, deploy_url) VALUES (?, ?, ?, ?, ?, ?)',
            (project_id, user['id'], port, proc.pid, 'running', deploy_url)
        )
        conn.commit()
        conn.close()

        return jsonify({
            'status': 'deployed',
            'port': port,
            'pid': proc.pid,
            'url': deploy_url,
            'command': run_command,
            'message': f'Project deployed on port {port}',
        })

    except Exception as e:
        conn.close()
        return jsonify({'error': f'Deploy failed: {str(e)}'}), 500


@deploy_bp.route('/api/deploy/<int:project_id>', methods=['DELETE'])
@login_required
def stop_deployment(user, project_id):
    """Stop a running deployment."""
    conn = get_db()
    deployment = conn.execute(
        'SELECT * FROM deployments WHERE project_id = ? AND user_id = ? AND status = ?',
        (project_id, user['id'], 'running')
    ).fetchone()

    if not deployment:
        conn.close()
        return jsonify({'error': 'No running deployment found'}), 404

    try:
        os.killpg(os.getpgid(deployment['deploy_pid']), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass

    conn.execute(
        'UPDATE deployments SET status = ? WHERE id = ?',
        ('stopped', deployment['id'])
    )
    conn.commit()
    conn.close()

    return jsonify({'status': 'stopped', 'message': 'Deployment stopped'})


@deploy_bp.route('/api/deploy/<int:project_id>/status', methods=['GET'])
@login_required
def deployment_status(user, project_id):
    """Check deployment status."""
    conn = get_db()
    deployment = conn.execute(
        'SELECT * FROM deployments WHERE project_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT 1',
        (project_id, user['id'])
    ).fetchone()
    conn.close()

    if not deployment:
        return jsonify({'status': 'none'})

    # Check if process is still running
    if deployment['status'] == 'running' and deployment['deploy_pid']:
        try:
            os.kill(deployment['deploy_pid'], 0)
        except ProcessLookupError:
            conn = get_db()
            conn.execute('UPDATE deployments SET status = ? WHERE id = ?', ('crashed', deployment['id']))
            conn.commit()
            conn.close()
            return jsonify({'status': 'crashed', 'port': deployment['deploy_port']})

    return jsonify({
        'status': deployment['status'],
        'port': deployment['deploy_port'],
        'url': deployment['deploy_url'],
        'pid': deployment['deploy_pid'],
    })


@deploy_bp.route('/api/deployments', methods=['GET'])
@login_required
def list_deployments(user):
    """List all deployments for the current user."""
    conn = get_db()
    deployments = conn.execute(
        '''SELECT d.*, p.name as project_name, p.language as project_language
           FROM deployments d
           JOIN projects p ON d.project_id = p.id
           WHERE d.user_id = ?
           ORDER BY d.created_at DESC''',
        (user['id'],)
    ).fetchall()
    conn.close()

    result = []
    for dep in deployments:
        d = dict(dep)
        # Check if running process is actually alive
        if d['status'] == 'running' and d['deploy_pid']:
            try:
                os.kill(d['deploy_pid'], 0)
            except ProcessLookupError:
                d['status'] = 'crashed'
                conn2 = get_db()
                conn2.execute('UPDATE deployments SET status = ? WHERE id = ?', ('crashed', d['id']))
                conn2.commit()
                conn2.close()
        result.append(d)

    return jsonify(result)


@deploy_bp.route('/api/deploy/<int:deploy_id>/delete', methods=['DELETE'])
@login_required
def delete_deployment(user, deploy_id):
    """Delete a deployment record (and stop it if running)."""
    conn = get_db()
    deployment = conn.execute(
        'SELECT * FROM deployments WHERE id = ? AND user_id = ?',
        (deploy_id, user['id'])
    ).fetchone()

    if not deployment:
        conn.close()
        return jsonify({'error': 'Deployment not found'}), 404

    # Stop if running
    if deployment['status'] == 'running' and deployment['deploy_pid']:
        try:
            os.killpg(os.getpgid(deployment['deploy_pid']), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    conn.execute('DELETE FROM deployments WHERE id = ?', (deploy_id,))
    conn.commit()
    conn.close()

    return jsonify({'status': 'deleted', 'message': 'Deployment removed'})


@deploy_bp.route('/api/deploy/<int:project_id>/restart', methods=['POST'])
@login_required
def restart_deployment(user, project_id):
    """Restart a deployment by stopping and re-deploying."""
    # Stop existing
    conn = get_db()
    existing = conn.execute(
        'SELECT * FROM deployments WHERE project_id = ? AND user_id = ? AND status = ?',
        (project_id, user['id'], 'running')
    ).fetchone()

    if existing and existing['deploy_pid']:
        try:
            os.killpg(os.getpgid(existing['deploy_pid']), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        conn.execute(
            'UPDATE deployments SET status = ? WHERE id = ?',
            ('stopped', existing['id'])
        )
        conn.commit()

    conn.close()

    # Re-deploy by calling the deploy function logic
    return deploy_project(user, project_id)
