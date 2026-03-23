import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, send_from_directory, session, jsonify, request
from flask_cors import CORS
from config import SECRET_KEY, WORKSPACES_DIR
from models import init_db
from auth import auth_bp
from projects import projects_bp
from files import files_bp
from ai import ai_bp
from keys import keys_bp
from deploy import deploy_bp

app = Flask(__name__, static_folder='../frontend', static_url_path='')
app.secret_key = SECRET_KEY
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 7  # 7 days

CORS(app, supports_credentials=True, origins=["*"])

# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(projects_bp)
app.register_blueprint(files_bp)
app.register_blueprint(ai_bp)
app.register_blueprint(keys_bp)
app.register_blueprint(deploy_bp)

# Initialize database
init_db()


# Serve frontend
@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/login')
def serve_login():
    return send_from_directory(app.static_folder, 'login.html')


@app.route('/editor')
def serve_editor():
    return send_from_directory(app.static_folder, 'editor.html')


@app.route('/docs')
def serve_docs():
    return send_from_directory(app.static_folder, 'docs.html')


@app.route('/api-keys')
def serve_api_keys():
    return send_from_directory(app.static_folder, 'api-keys.html')


@app.route('/settings')
def serve_settings():
    return send_from_directory(app.static_folder, 'settings.html')


@app.route('/css/<path:filename>')
def serve_css(filename):
    return send_from_directory(os.path.join(app.static_folder, 'css'), filename)


@app.route('/js/<path:filename>')
def serve_js(filename):
    return send_from_directory(os.path.join(app.static_folder, 'js'), filename)


@app.route('/assets/<path:filename>')
def serve_assets(filename):
    return send_from_directory(os.path.join(app.static_folder, 'assets'), filename)


# Serve user workspace files for HTML preview
@app.route('/preview/<int:project_id>/<path:filename>')
def serve_preview(project_id, filename):
    from auth import get_current_user
    from models import get_db

    user = get_current_user()
    if not user:
        return "Unauthorized", 401

    conn = get_db()
    project = conn.execute(
        'SELECT * FROM projects WHERE id = ? AND user_id = ?',
        (project_id, user['id'])
    ).fetchone()
    conn.close()

    if not project:
        return "Not found", 404

    safe_name = project['name'].replace('..', '').replace('/', '_').replace('\\', '_')
    project_path = os.path.join(WORKSPACES_DIR, str(user['id']), safe_name)

    full_path = os.path.join(project_path, filename)
    real_base = os.path.realpath(project_path)
    real_target = os.path.realpath(full_path)
    if not real_target.startswith(real_base):
        return "Forbidden", 403

    return send_from_directory(project_path, filename)


@app.route('/api/projects/<int:project_id>/workspace_path', methods=['GET'])
def get_workspace_path(project_id):
    from auth import get_current_user
    from models import get_db

    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401

    conn = get_db()
    project = conn.execute(
        'SELECT * FROM projects WHERE id = ? AND user_id = ?',
        (project_id, user['id'])
    ).fetchone()
    conn.close()

    if not project:
        return jsonify({'error': 'Project not found'}), 404

    safe_name = project['name'].replace('..', '').replace('/', '_').replace('\\', '_')
    project_path = os.path.join(WORKSPACES_DIR, str(user['id']), safe_name)
    os.makedirs(project_path, exist_ok=True)

    return jsonify({'path': project_path})


# Proxy for deployed user apps
@app.route('/preview-app/<int:project_id>', defaults={'path': ''}, methods=['GET', 'POST'])
@app.route('/preview-app/<int:project_id>/<path:path>', methods=['GET', 'POST'])
def preview_app(project_id, path):
    from models import get_db
    import requests as req

    # Allow unauthenticated access to preview - the deploy itself is authenticated
    # This enables iframe embedding and direct URL access to deployed apps
    conn = get_db()
    deployment = conn.execute(
        'SELECT * FROM deployments WHERE project_id = ? AND status = ?',
        (project_id, 'running')
    ).fetchone()
    conn.close()

    if not deployment:
        return "No running deployment", 404

    port = deployment['deploy_port']
    # Include query string in proxied request
    query_string = request.query_string.decode()
    target_url = f'http://127.0.0.1:{port}/{path}'
    if query_string:
        target_url += f'?{query_string}'

    try:
        # Forward the original request method and headers
        headers = {}
        for key in ['Accept', 'Accept-Language', 'Content-Type', 'Cookie', 'Referer']:
            if key in request.headers:
                headers[key] = request.headers[key]
        # Tell the deployed app we're behind a proxy (disables HTTPS redirects in Talisman etc.)
        headers['X-Forwarded-Proto'] = 'https'
        headers['X-Forwarded-For'] = request.remote_addr or '127.0.0.1'

        if request.method == 'POST':
            resp = req.post(target_url, data=request.get_data(), headers=headers, timeout=15, allow_redirects=True, verify=False)
        else:
            resp = req.get(target_url, headers=headers, timeout=15, allow_redirects=True, verify=False)

        from flask import Response
        excluded_headers = ['content-encoding', 'transfer-encoding', 'content-length']
        resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in excluded_headers}

        content = resp.content
        content_type = resp.headers.get('Content-Type', '')

        # For HTML responses, rewrite absolute URLs so static assets load through the proxy
        if 'text/html' in content_type:
            html = content.decode('utf-8', errors='replace')
            prefix = f'/preview-app/{project_id}'
            # Rewrite href="/..." and src="/..." to go through proxy
            import re
            html = re.sub(r'(href|src|action)="/', rf'\1="{prefix}/', html)
            content = html.encode('utf-8')

        return Response(content, status=resp.status_code, headers=resp_headers)
    except req.exceptions.ConnectionError:
        return '''<html><head><meta http-equiv="refresh" content="2"></head>
<body style="background:#0d1117;color:#8b949e;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="text-align:center">
<div style="width:40px;height:40px;border:3px solid #30363d;border-top:3px solid #58a6ff;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 16px;"></div>
<h2 style="color:#58a6ff;margin-bottom:8px;">Starting up...</h2>
<p>Your app is launching. This page will auto-refresh.</p>
<style>@keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}</style>
</div></body></html>''', 503
    except Exception as e:
        return f'''<html><head><meta http-equiv="refresh" content="3"></head>
<body style="background:#0d1117;color:#f85149;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="text-align:center"><h2>Error</h2><p>{str(e)}</p><p style="color:#8b949e;font-size:0.85rem;">Retrying automatically...</p></div></body></html>''', 503


@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': 'YubiLab Flask Backend'})


if __name__ == '__main__':
    print("Starting YubiLab Flask Backend on port 5000...")
    app.run(host='0.0.0.0', port=5000, debug=True)
