from flask import Blueprint, request, jsonify, send_file
from auth import login_required
from models import get_db
from config import WORKSPACES_DIR
import os
import subprocess
import signal
import socket as sock
import time
import glob as glob_mod

deploy_bp = Blueprint('deploy', __name__)


_NON_PIP_PACKAGES = {
    'bootstrap', 'jquery', 'tailwindcss', 'tailwind', 'font-awesome',
    'fontawesome', 'bulma', 'materialize', 'react', 'vue', 'angular',
    'alpinejs', 'htmx', 'popper.js', 'animate.css', 'sweetalert2',
}


def _sanitize_requirements_file(project_path):
    """Remove non-pip packages (Bootstrap, jQuery, etc.) from requirements.txt."""
    req_path = os.path.join(project_path, 'requirements.txt')
    if not os.path.isfile(req_path):
        return
    try:
        with open(req_path, 'r') as f:
            lines = f.readlines()
        cleaned = []
        for line in lines:
            pkg = line.strip().split('==')[0].split('>=')[0].split('<=')[0].split('~=')[0].strip().lower()
            if pkg and pkg not in _NON_PIP_PACKAGES:
                cleaned.append(line)
        with open(req_path, 'w') as f:
            f.writelines(cleaned)
    except Exception:
        pass


def find_free_port(start=3002, end=9000):
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
    if needs_install:
        # Sanitize requirements.txt — remove non-pip packages like Bootstrap
        _sanitize_requirements_file(project_path)
    install_prefix = 'pip install -q --upgrade -r requirements.txt && ' if needs_install else ''

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

        # Check for run.py first (common entry point for refactored Flask apps)
        if 'run.py' in files:
            return f'{install_prefix}python3 run.py'
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

    if language == 'php' or any(f.endswith('.php') for f in files):
        # Check for composer.json
        if 'composer.json' in files:
            return 'composer install --no-interaction && php -S 0.0.0.0:{port} -t .'
        if 'index.php' in files:
            return 'php -S 0.0.0.0:{port} -t .'
        for f in files:
            if f.endswith('.php'):
                return 'php -S 0.0.0.0:{port} -t .'

    if language == 'go' or any(f.endswith('.go') for f in files):
        if 'go.mod' in files:
            return 'go run .'
        if 'main.go' in files:
            return 'go run main.go'
        for f in files:
            if f.endswith('.go'):
                return f'go run {f}'

    if language == 'java' or any(f.endswith('.java') for f in files):
        if 'pom.xml' in files:
            return 'mvn spring-boot:run -Dserver.port={port}'
        if 'build.gradle' in files:
            return 'gradle bootRun --args="--server.port={port}"'
        for f in files:
            if f.endswith('.java'):
                name = f.replace('.java', '')
                return f'javac {f} && java {name}'

    if language == 'ruby' or any(f.endswith('.rb') for f in files):
        if 'Gemfile' in files:
            return 'bundle install && bundle exec ruby app.rb -p {port} -o 0.0.0.0'
        if 'app.rb' in files:
            return 'ruby app.rb'
        if 'config.ru' in files:
            return 'bundle install && bundle exec rackup -p {port} -o 0.0.0.0'
        for f in files:
            if f.endswith('.rb'):
                return f'ruby {f}'

    if language == 'rust' or 'Cargo.toml' in files:
        return 'cargo run'

    if language == 'dart' or 'pubspec.yaml' in files:
        # Flutter/Dart project
        if os.path.isfile(os.path.join(project_path, 'pubspec.yaml')):
            try:
                with open(os.path.join(project_path, 'pubspec.yaml'), 'r') as fh:
                    content = fh.read()
                    if 'flutter' in content:
                        return 'flutter pub get && flutter run -d web --web-port {port} --web-hostname 0.0.0.0'
            except Exception:
                pass
            return 'dart run'

    if language == 'html':
        return 'python3 -m http.server {port}'

    # Fallback: try to detect by file extensions
    for f in files:
        ext = f.rsplit('.', 1)[-1] if '.' in f else ''
        if ext == 'py':
            return f'python3 {f}'
        if ext == 'js':
            return f'node {f}'
        if ext == 'php':
            return 'php -S 0.0.0.0:{port} -t .'
        if ext == 'rb':
            return f'ruby {f}'
        if ext == 'go':
            return f'go run {f}'

    return None


def deploy_project_internal(user, project_id, project_path, run_command_override=None):
    """Internal deploy function callable from agent without HTTP context.
    Returns dict with success, port, url, etc."""
    conn = get_db()
    project = conn.execute(
        'SELECT * FROM projects WHERE id = ? AND user_id = ?',
        (project_id, user['id'])
    ).fetchone()

    if not project:
        conn.close()
        return {'success': False, 'error': 'Project not found'}

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

    port = find_free_port()
    if not port:
        conn.close()
        return {'success': False, 'error': 'No free ports available'}

    run_command = run_command_override or detect_run_command(project_path, project['language'])
    if not run_command:
        conn.close()
        return {'success': False, 'error': 'Could not detect run command'}

    run_command = run_command.replace('{port}', str(port))

    env = os.environ.copy()
    env['PORT'] = str(port)
    env['FLASK_RUN_PORT'] = str(port)
    env['HOST'] = '0.0.0.0'
    env['FLASK_DEBUG'] = '0'
    env['FLASK_APP'] = 'app.py'
    env.pop('WERKZEUG_SERVER_FD', None)
    env.pop('WERKZEUG_RUN_MAIN', None)
    # Ensure Flutter and Android SDK are in PATH for Flutter projects
    flutter_bin = os.path.expanduser('~/flutter/bin')
    android_tools = os.path.expanduser('~/android-sdk/cmdline-tools/latest/bin')
    android_platform = os.path.expanduser('~/android-sdk/platform-tools')
    if os.path.isdir(flutter_bin):
        env['PATH'] = f"{flutter_bin}:{android_tools}:{android_platform}:{env.get('PATH', '')}"
        env['ANDROID_HOME'] = os.path.expanduser('~/android-sdk')

    try:
        log_file = os.path.join(project_path, '.deploy.log')
        log_fd = open(log_file, 'w')
        proc = subprocess.Popen(
            run_command, shell=True, cwd=project_path, env=env,
            stdin=subprocess.DEVNULL, stdout=log_fd, stderr=log_fd,
            start_new_session=True,
        )

        deploy_url = f'/preview-app/{project_id}'
        conn.execute(
            'INSERT INTO deployments (project_id, user_id, deploy_port, deploy_pid, status, deploy_url) VALUES (?, ?, ?, ?, ?, ?)',
            (project_id, user['id'], port, proc.pid, 'running', deploy_url)
        )
        conn.commit()
        conn.close()

        # Wait for the app to be ready (up to 30 seconds — pip install can take a while)
        ready = False
        for _ in range(60):
            time.sleep(0.5)
            try:
                s = sock.socket(sock.AF_INET, sock.SOCK_STREAM)
                s.settimeout(1)
                s.connect(('127.0.0.1', port))
                s.close()
                ready = True
                break
            except (ConnectionRefusedError, OSError):
                if proc.poll() is not None:
                    break
                continue

        return {
            'success': True,
            'port': port,
            'pid': proc.pid,
            'url': deploy_url,
            'command': run_command,
            'ready': ready,
        }
    except Exception as e:
        conn.close()
        return {'success': False, 'error': str(e)}


@deploy_bp.route('/api/deploy/<int:project_id>', methods=['POST'])
@login_required
def deploy_project(user, project_id):
    """Deploy a project - works for all stacks."""
    conn = get_db()
    project = conn.execute(
        'SELECT * FROM projects WHERE id = ? AND user_id = ?',
        (project_id, user['id'])
    ).fetchone()
    conn.close()

    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = get_project_path(user['id'], project['name'])

    data = request.get_json() or {}
    run_command = data.get('run_command', '')

    result = deploy_project_internal(user, project_id, project_path, run_command or None)

    if not result['success']:
        return jsonify({'error': result['error']}), 500

    return jsonify({
        'status': 'deployed',
        'port': result['port'],
        'pid': result['pid'],
        'url': result['url'],
        'command': result['command'],
        'ready': result['ready'],
        'message': f'Project deployed on port {result["port"]}' + (' and ready!' if result['ready'] else ' (starting up...)'),
    })


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


def _get_flutter_env():
    """Return env dict with Flutter and Android SDK in PATH."""
    env = os.environ.copy()
    flutter_bin = os.path.expanduser('~/flutter/bin')
    android_tools = os.path.expanduser('~/android-sdk/cmdline-tools/latest/bin')
    android_platform = os.path.expanduser('~/android-sdk/platform-tools')
    if os.path.isdir(flutter_bin):
        env['PATH'] = f"{flutter_bin}:{android_tools}:{android_platform}:{env.get('PATH', '')}"
        env['ANDROID_HOME'] = os.path.expanduser('~/android-sdk')
    return env


@deploy_bp.route('/api/flutter/build/<int:project_id>', methods=['POST'])
@login_required
def flutter_build(user, project_id):
    """Build a Flutter project (web or APK)."""
    conn = get_db()
    project = conn.execute(
        'SELECT * FROM projects WHERE id = ? AND user_id = ?',
        (project_id, user['id'])
    ).fetchone()
    conn.close()

    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = get_project_path(user['id'], project['name'])
    pubspec = os.path.join(project_path, 'pubspec.yaml')
    if not os.path.isfile(pubspec):
        return jsonify({'error': 'Not a Flutter project (no pubspec.yaml)'}), 400

    data = request.get_json() or {}
    build_type = data.get('type', 'web')  # 'web' or 'apk'

    env = _get_flutter_env()

    # For APK builds: ensure android/ scaffold exists (auto-generate if missing)
    if build_type == 'apk':
        android_dir = os.path.join(project_path, 'android')
        if not os.path.isdir(android_dir):
            from projects import ensure_flutter_android_scaffold
            scaffold_ok = ensure_flutter_android_scaffold(project_path)
            if not scaffold_ok:
                return jsonify({
                    'error': 'Failed to generate Android scaffold. The android/ directory is missing and could not be auto-created.',
                    'details': 'Try creating a new Flutter project or run "flutter create ." in the project directory.'
                }), 500

    # First run flutter pub get
    try:
        pub_result = subprocess.run(
            'flutter pub get', shell=True, cwd=project_path, env=env,
            capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'flutter pub get timed out'}), 500

    if pub_result.returncode != 0:
        return jsonify({
            'error': 'flutter pub get failed',
            'details': pub_result.stderr[-2000:] if pub_result.stderr else 'Unknown error'
        }), 500

    # Build
    if build_type == 'apk':
        build_cmd = 'flutter build apk --release'
    else:
        build_cmd = 'flutter build web --release'

    try:
        result = subprocess.run(
            build_cmd, shell=True, cwd=project_path, env=env,
            capture_output=True, text=True, timeout=600
        )
    except subprocess.TimeoutExpired:
        return jsonify({'error': f'Flutter {build_type} build timed out (10 min limit)'}), 500

    if result.returncode != 0:
        return jsonify({
            'error': f'Flutter {build_type} build failed',
            'details': result.stderr[-2000:] if result.stderr else result.stdout[-2000:]
        }), 500

    if build_type == 'apk':
        # Find the APK file
        apk_path = os.path.join(project_path, 'build', 'app', 'outputs', 'flutter-apk', 'app-release.apk')
        if not os.path.isfile(apk_path):
            # Try alternate path
            apk_files = glob_mod.glob(os.path.join(project_path, 'build', '**', '*.apk'), recursive=True)
            apk_path = apk_files[0] if apk_files else None

        if not apk_path or not os.path.isfile(apk_path):
            return jsonify({'error': 'APK build succeeded but file not found', 'output': result.stdout[-1000:]}), 500

        apk_size = os.path.getsize(apk_path)
        return jsonify({
            'success': True,
            'type': 'apk',
            'message': 'APK built successfully!',
            'size': apk_size,
            'size_human': f'{apk_size / (1024*1024):.1f} MB',
            'download_url': f'/api/flutter/download/{project_id}/apk',
        })
    else:
        # Web build — serve via a static file server
        web_dir = os.path.join(project_path, 'build', 'web')
        if not os.path.isdir(web_dir):
            return jsonify({'error': 'Web build succeeded but output directory not found'}), 500

        # Deploy the web build using python http.server
        port = find_free_port()
        if not port:
            return jsonify({'error': 'No free ports available'}), 500

        log_file = os.path.join(project_path, '.deploy.log')
        log_fd = open(log_file, 'w')
        proc = subprocess.Popen(
            f'python3 -m http.server {port}',
            shell=True, cwd=web_dir, env=env,
            stdin=subprocess.DEVNULL, stdout=log_fd, stderr=log_fd,
            start_new_session=True,
        )

        deploy_url = f'/preview-app/{project_id}'
        conn = get_db()
        # Kill existing running deployment if any
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

        conn.execute(
            'INSERT INTO deployments (project_id, user_id, deploy_port, deploy_pid, status, deploy_url) VALUES (?, ?, ?, ?, ?, ?)',
            (project_id, user['id'], port, proc.pid, 'running', deploy_url)
        )
        conn.commit()
        conn.close()

        # Wait for server to be ready
        for _ in range(10):
            time.sleep(0.3)
            try:
                s = sock.socket(sock.AF_INET, sock.SOCK_STREAM)
                s.settimeout(1)
                s.connect(('127.0.0.1', port))
                s.close()
                break
            except (ConnectionRefusedError, OSError):
                continue

        return jsonify({
            'success': True,
            'type': 'web',
            'message': 'Flutter web app built and deployed!',
            'port': port,
            'url': deploy_url,
            'pid': proc.pid,
            'ready': True,
        })


@deploy_bp.route('/api/flutter/download/<int:project_id>/<string:artifact>', methods=['GET'])
@login_required
def flutter_download(user, project_id, artifact):
    """Download a Flutter build artifact (APK, etc.)."""
    conn = get_db()
    project = conn.execute(
        'SELECT * FROM projects WHERE id = ? AND user_id = ?',
        (project_id, user['id'])
    ).fetchone()
    conn.close()

    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = get_project_path(user['id'], project['name'])

    if artifact == 'apk':
        apk_path = os.path.join(project_path, 'build', 'app', 'outputs', 'flutter-apk', 'app-release.apk')
        if not os.path.isfile(apk_path):
            apk_files = glob_mod.glob(os.path.join(project_path, 'build', '**', '*.apk'), recursive=True)
            apk_path = apk_files[0] if apk_files else None

        if not apk_path or not os.path.isfile(apk_path):
            return jsonify({'error': 'APK not found. Build the project first.'}), 404

        project_name = project['name'].replace(' ', '_').replace('-', '_')
        return send_file(apk_path, as_attachment=True, download_name=f'{project_name}.apk')

    elif artifact == 'web':
        # Download web build as zip
        import shutil
        web_dir = os.path.join(project_path, 'build', 'web')
        if not os.path.isdir(web_dir):
            return jsonify({'error': 'Web build not found. Build the project first.'}), 404

        zip_path = os.path.join(project_path, 'build', 'web-build')
        shutil.make_archive(zip_path, 'zip', web_dir)
        project_name = project['name'].replace(' ', '_').replace('-', '_')
        return send_file(f'{zip_path}.zip', as_attachment=True, download_name=f'{project_name}_web.zip')

    return jsonify({'error': f'Unknown artifact type: {artifact}'}), 400


@deploy_bp.route('/api/flutter/status/<int:project_id>', methods=['GET'])
@login_required
def flutter_status(user, project_id):
    """Check if a project is a Flutter project and what builds are available."""
    conn = get_db()
    project = conn.execute(
        'SELECT * FROM projects WHERE id = ? AND user_id = ?',
        (project_id, user['id'])
    ).fetchone()
    conn.close()

    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = get_project_path(user['id'], project['name'])
    pubspec = os.path.join(project_path, 'pubspec.yaml')

    if not os.path.isfile(pubspec):
        return jsonify({'is_flutter': False})

    # Check if it's actually a Flutter project (not just a Dart project)
    is_flutter = False
    try:
        with open(pubspec, 'r') as f:
            content = f.read()
            is_flutter = 'flutter' in content
    except Exception:
        pass

    # Check available builds
    web_built = os.path.isdir(os.path.join(project_path, 'build', 'web'))
    apk_path = os.path.join(project_path, 'build', 'app', 'outputs', 'flutter-apk', 'app-release.apk')
    apk_built = os.path.isfile(apk_path)
    apk_size = os.path.getsize(apk_path) if apk_built else 0

    return jsonify({
        'is_flutter': is_flutter,
        'web_built': web_built,
        'apk_built': apk_built,
        'apk_size': apk_size,
        'apk_size_human': f'{apk_size / (1024*1024):.1f} MB' if apk_built else None,
    })
