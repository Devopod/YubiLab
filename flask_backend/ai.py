from flask import Blueprint, request, jsonify
from auth import login_required
from models import get_db
import requests
import os
import json
import subprocess
import time
import re
from config import WORKSPACES_DIR, YUBIAI_API_URL, YUBIAI_API_KEY

ai_bp = Blueprint('ai', __name__)


def get_project_path(user_id, project_name):
    safe_name = project_name.replace('..', '').replace('/', '_').replace('\\', '_')
    return os.path.join(WORKSPACES_DIR, str(user_id), safe_name)


def call_yubiai(message, system_prompt=None, model="gpt-oss-120b", temperature=0.7, max_tokens=4096, retries=3):
    """Call YubiAI API with automatic retry and exponential backoff."""
    if not YUBIAI_API_KEY:
        return {"error": "YubiAI API key not configured. Set YUBIAI_API_KEY environment variable."}
    if not YUBIAI_API_URL:
        return {"error": "YubiAI API URL not configured. Set YUBIAI_API_URL environment variable."}

    payload = {
        "message": message,
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": 0.9,
    }
    if system_prompt:
        payload["system_prompt"] = system_prompt

    last_error = None
    for attempt in range(retries):
        try:
            resp = requests.post(
                YUBIAI_API_URL,
                headers={
                    "Authorization": f"Bearer {YUBIAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=180,
            )
            if resp.status_code == 200:
                return resp.json()
            error_text = resp.text
            if 'ngrok' in error_text.lower() or 'offline' in error_text.lower():
                last_error = "YubiAI API endpoint is offline. The ngrok tunnel may have disconnected."
            elif resp.status_code == 401:
                return {"error": "YubiAI API authentication failed. Check your API key."}
            elif resp.status_code == 429:
                last_error = "YubiAI API rate limit exceeded."
            elif resp.status_code == 404:
                last_error = "YubiAI API endpoint not found (404)."
            else:
                last_error = f"YubiAI API returned HTTP {resp.status_code}."
        except requests.exceptions.ConnectionError:
            last_error = "Cannot connect to YubiAI API. The server appears to be offline."
        except requests.exceptions.Timeout:
            last_error = "YubiAI API request timed out (180s)."
        except Exception as e:
            last_error = f"YubiAI API error: {str(e)}"

        # Exponential backoff: 2s, 4s, 8s
        if attempt < retries - 1:
            time.sleep(2 ** (attempt + 1))

    return {"error": f"{last_error} (failed after {retries} retries)"}


def get_project_files_context(project_path, max_file_size=10000):
    """Read all project files and return as context string."""
    files_context = ""
    file_list = []
    if not os.path.isdir(project_path):
        return files_context, file_list

    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__', '.git', 'venv', 'env')]
        for f in files:
            if f.startswith('.') or f.endswith(('.pyc', '.pyo', '.class', '.o')):
                continue
            rel_path = os.path.relpath(os.path.join(root, f), project_path)
            file_list.append(rel_path)
            try:
                with open(os.path.join(root, f), 'r', errors='replace') as fh:
                    content = fh.read()
                if len(content) <= max_file_size:
                    files_context += f"\n=== FILE: {rel_path} ===\n{content}\n"
                else:
                    files_context += f"\n=== FILE: {rel_path} === (truncated, {len(content)} chars)\n{content[:2000]}...\n"
            except Exception:
                file_list.append(f"{rel_path} (binary/unreadable)")
    return files_context, file_list


# Non-pip packages that AI sometimes puts in requirements.txt
NON_PIP_PACKAGES = {
    'bootstrap', 'jquery', 'tailwindcss', 'tailwind', 'font-awesome',
    'fontawesome', 'bulma', 'materialize', 'react', 'vue', 'angular',
    'alpinejs', 'htmx', 'popper.js', 'animate.css', 'sweetalert2',
}


def sanitize_requirements(project_path):
    """Remove non-pip packages (like Bootstrap) from requirements.txt.
    Returns True if the file was modified."""
    req_path = os.path.join(project_path, 'requirements.txt')
    if not os.path.isfile(req_path):
        return False
    try:
        with open(req_path, 'r') as f:
            lines = f.readlines()
        cleaned = []
        modified = False
        for line in lines:
            pkg = line.strip().split('==')[0].split('>=')[0].split('<=')[0].split('~=')[0].strip().lower()
            if pkg in NON_PIP_PACKAGES:
                modified = True
            else:
                cleaned.append(line)
        if modified:
            with open(req_path, 'w') as f:
                f.writelines(cleaned)
        return modified
    except Exception:
        return False


def execute_test_command(project_path, command, timeout=30):
    """Execute a test command in the project directory and return output."""
    env = os.environ.copy()
    env['PORT'] = '3099'
    env['FLASK_RUN_PORT'] = '3099'
    env['PYTHONDONTWRITEBYTECODE'] = '1'

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=project_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            'returncode': result.returncode,
            'stdout': result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout,
            'stderr': result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
            'success': result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {'returncode': -1, 'stdout': '', 'stderr': 'Command timed out', 'success': True}
    except Exception as e:
        return {'returncode': -1, 'stdout': '', 'stderr': str(e), 'success': False}


# The powerful autonomous agent system prompt
AGENT_SYSTEM_PROMPT = """You are YubiAI, an elite autonomous AI software engineer inside YubiLab Cloud IDE — comparable to Devin AI. You think step by step, plan meticulously before coding, write production-quality code, and iterate relentlessly until the project works perfectly. You have a 32k token context window.

## YOUR CAPABILITIES
- Create, modify, and delete project files across any language/framework
- Architect and build entire full-stack projects from scratch
- Debug and fix errors by analyzing error output and stack traces
- Incrementally update code (only change what's needed, never rewrite working code)
- Generate run commands, test commands, and install commands
- Set up proper project structure with config files, dependencies, and scripts
- Create responsive, modern UIs with CSS animations and glassmorphism
- Build REST APIs, WebSocket servers, database integrations
- Handle environment variables, port configuration, and deployment setup
- Write unit tests and integration tests
- Optimize performance and fix memory leaks
- Implement authentication, form validation, error handling
- Work with Flask, Django, Express, React, Vue, PHP, Go, Java, Ruby, Rust, and more

## RESPONSE FORMAT
You MUST respond with ONLY a valid JSON object. No markdown, no explanation outside JSON.

{
  "phase": "plan|build|fix|update",
  "roadmap": [
    "Step 1: Description of what to do first",
    "Step 2: Description of next step",
    "Step 3: ..."
  ],
  "files": [
    {
      "path": "relative/path/to/file.ext",
      "content": "complete file content",
      "action": "create|modify|delete"
    }
  ],
  "run_command": "command to run the app (e.g., python app.py)",
  "test_command": "command to verify the app works (e.g., python -c \\"import app\\" or python -m py_compile app.py)",
  "install_command": "pip install -r requirements.txt (if needed)",
  "deploy_ready": false,
  "message": "Brief summary of what was done"
}

## CRITICAL RULES

### Planning
- ALWAYS include a detailed roadmap showing your step-by-step plan
- Think about the project structure, architecture, and file relationships BEFORE writing code
- Consider dependencies, imports, data flow, and edge cases
- For large projects, break into logical modules and components

### Incremental Changes
- When the project already has files, ONLY modify files that need changes
- DO NOT regenerate files that don't need changes
- For the "action" field:
  - "create" = new file that doesn't exist
  - "modify" = existing file that needs changes (provide COMPLETE new content)
  - "delete" = remove this file
- If no file changes are needed (e.g., just a config question), return empty files array

### Code Quality
- Write clean, production-ready code with proper error handling
- Include all necessary imports at the top of files
- Add requirements.txt with pinned versions when using pip packages
- NEVER put CSS/JS frameworks (Bootstrap, jQuery, Tailwind, etc.) in requirements.txt — they are loaded via CDN in HTML, not pip
- Follow best practices for each language/framework
- Always include `import os` in run.py when using os.environ

### Flask Compatibility (CRITICAL — we use Flask 3.x)
- NEVER use @app.before_first_request — it was REMOVED in Flask 2.3. Use `with app.app_context(): db.create_all()` inside create_app() instead.
- NEVER import `from flask import Markup` — use `from markupsafe import Markup`
- NEVER import `from flask import _request_ctx_stack` — it was removed
- Use `app.app_context()` pattern for initialization, NOT before_first_request
- For database initialization: call `db.create_all()` inside create_app() after registering blueprints
- Use proper HTML meta tags, responsive design, and accessibility
- Add loading states, error states, and empty states in UIs
- Use semantic HTML and modern CSS (flexbox, grid, variables)

### Port Configuration
- NEVER use port 5000 (YubiLab backend uses it)
- NEVER use port 3001 (Node engine uses it)
- For Flask apps: use os.environ.get('PORT', os.environ.get('FLASK_RUN_PORT', 3002))
- For Streamlit: use --server.port with PORT env var
- For Node.js: use process.env.PORT || 3002
- For any web server: read PORT from environment, default to 3002

### Testing
- Always provide a test_command that can verify the code compiles/imports correctly
- For Python: python -m py_compile <main_file> or python -c "import <module>"
- For Node.js: node -c <file> or node -e "require('./<file>')"
- For compilable languages: the compile command itself

### Deployment
- Set deploy_ready=true ONLY when the app is fully functional and tested
- Set deploy_ready=false during initial build, debugging, or partial updates

### Bug Fixing
- When given error output, analyze the EXACT error message and traceback
- Fix the ROOT CAUSE, not just the symptom
- Only modify files that have the bug — don't rewrite everything
- Explain what the bug was and how you fixed it in the message

### UI/UX Best Practices
- Use modern, dark-themed designs with glassmorphism effects
- Add smooth animations and transitions
- Make all layouts fully responsive (mobile, tablet, desktop)
- Use gradient colors, subtle shadows, and rounded corners
- Add hover effects on interactive elements
- Include proper loading spinners and skeleton screens"""


# Planning-only system prompt for multi-request agent
AGENT_PLAN_PROMPT = """You are YubiAI, an elite autonomous AI software engineer. Your task is to PLAN a project — list ALL files that need to be created, but DO NOT write the code yet.

You MUST respond with ONLY a valid JSON object:
{
  "phase": "plan",
  "roadmap": ["Step 1: ...", "Step 2: ..."],
  "file_groups": [
    {
      "group_name": "Backend Core",
      "description": "Main application files, models, routes",
      "files": ["app/__init__.py", "app/models.py", "app/routes.py", "app/auth.py"]
    },
    {
      "group_name": "Templates",
      "description": "HTML templates for all pages",
      "files": ["app/templates/base.html", "app/templates/login.html", "app/templates/signup.html", "app/templates/chatbot.html"]
    },
    {
      "group_name": "Static Assets & Config",
      "description": "CSS, JavaScript, and configuration files",
      "files": ["app/static/css/styles.css", "app/static/js/chatbot.js", "requirements.txt", "run.py", "README.md"]
    }
  ],
  "run_command": "python run.py",
  "test_command": "python -m py_compile run.py",
  "install_command": "pip install -r requirements.txt",
  "deploy_ready": true,
  "message": "Planning complete: X files in Y groups"
}

RULES:
- Group related files together (e.g., backend, templates, static, config)
- Each group should have 2-5 files max (for token efficiency)
- List EVERY file the project needs — don't skip any
- Include config files (requirements.txt, package.json, etc.)
- Include proper run_command, test_command, and install_command
- NEVER put CSS/JS frameworks (Bootstrap, jQuery, Tailwind) in requirements.txt — use CDN links in HTML
- Port rules: NEVER use 5000 or 3001. Use PORT env var, default 3002.
- For Flask: os.environ.get('PORT', os.environ.get('FLASK_RUN_PORT', 3002))
- Always include `import os` in run.py when using os.environ"""


# Batch generation prompt for multi-request agent
AGENT_BATCH_PROMPT = """You are YubiAI, an elite autonomous AI software engineer. Generate the COMPLETE code for the specified files ONLY.

You MUST respond with ONLY a valid JSON object:
{
  "phase": "build",
  "files": [
    {
      "path": "relative/path/to/file.ext",
      "content": "COMPLETE file content — every line, every import",
      "action": "create"
    }
  ],
  "message": "Generated X files for [group name]"
}

RULES:
- Generate ONLY the files listed in the request — no extras
- Each file must have COMPLETE content — no placeholders, no "..." or "TODO"
- Include ALL imports, ALL functions, ALL HTML, ALL CSS — everything
- Code must be production-ready, clean, and well-commented
- Follow PEP-8 for Python, standard conventions for other languages
- Port rules: NEVER use 5000 or 3001. Use PORT env var, default 3002.
- For Flask: os.environ.get('PORT', os.environ.get('FLASK_RUN_PORT', 3002))
- Use modern, responsive UI with gradients, shadows, and glassmorphism
- Include proper error handling in every file
- Make sure cross-file imports are correct (e.g., from app.models import User)
- Flask 3.x compatibility: NEVER use @app.before_first_request (removed). Use `with app.app_context(): db.create_all()` in create_app() instead.
- NEVER import Markup from flask — use `from markupsafe import Markup`"""


@ai_bp.route('/api/ai/conversations/<int:project_id>', methods=['GET'])
@login_required
def get_conversations(user, project_id):
    """Load saved AI conversations for a project."""
    conn = get_db()
    messages = conn.execute(
        'SELECT role, content, msg_type, created_at FROM ai_conversations WHERE project_id = ? AND user_id = ? ORDER BY created_at ASC',
        (project_id, user['id'])
    ).fetchall()
    conn.close()
    return jsonify([dict(m) for m in messages])


@ai_bp.route('/api/ai/conversations/<int:project_id>', methods=['POST'])
@login_required
def save_conversation(user, project_id):
    """Save an AI conversation message."""
    data = request.get_json()
    role = data.get('role', '')
    content = data.get('content', '')
    msg_type = data.get('msg_type', 'text')

    if not role or not content:
        return jsonify({'error': 'role and content required'}), 400

    conn = get_db()
    conn.execute(
        'INSERT INTO ai_conversations (project_id, user_id, role, content, msg_type) VALUES (?, ?, ?, ?, ?)',
        (project_id, user['id'], role, content, msg_type)
    )
    conn.commit()
    conn.close()
    return jsonify({'status': 'saved'})


@ai_bp.route('/api/ai/conversations/<int:project_id>', methods=['DELETE'])
@login_required
def clear_conversations(user, project_id):
    """Clear AI conversations for a project."""
    conn = get_db()
    conn.execute(
        'DELETE FROM ai_conversations WHERE project_id = ? AND user_id = ?',
        (project_id, user['id'])
    )
    conn.commit()
    conn.close()
    return jsonify({'status': 'cleared'})


@ai_bp.route('/api/ai/generate', methods=['POST'])
@login_required
def ai_generate(user):
    data = request.get_json()
    prompt = data.get('prompt', '')
    code_context = data.get('code_context', '')
    language = data.get('language', 'python')
    action = data.get('action', 'generate')  # generate, debug, explain, complete
    project_id = data.get('project_id')

    if not prompt:
        return jsonify({'error': 'Prompt is required'}), 400

    # Always read full project source code for context
    project_files_context = ''
    if project_id:
        conn = get_db()
        project = conn.execute(
            'SELECT * FROM projects WHERE id = ? AND user_id = ?',
            (project_id, user['id'])
        ).fetchone()
        conn.close()
        if project:
            project_path = get_project_path(user['id'], project['name'])
            project_files_context, _ = get_project_files_context(project_path)

    system_prompts = {
        'generate': f"You are YubiAI, an expert coding assistant built into YubiLab IDE. You have access to the full project source code. Generate clean, well-commented {language} code based on the user's request. Return ONLY the code without markdown code blocks unless the user asks for explanation.",
        'debug': f"You are YubiAI, a debugging expert in YubiLab IDE. You have access to the full project source code. Analyze the following {language} code and identify bugs, then provide the fixed version. Explain what was wrong briefly.",
        'explain': f"You are YubiAI, a code explanation assistant in YubiLab IDE. You have access to the full project source code. Explain the code thoroughly — describe its structure, purpose, and how the individual pieces work together.",
        'complete': f"You are YubiAI, an autocomplete assistant in YubiLab IDE. You have access to the full project source code. Complete the following {language} code naturally. Return ONLY the completed code.",
    }

    system_prompt = system_prompts.get(action, system_prompts['generate'])

    # Build full prompt with project source code
    parts = []
    if project_files_context:
        parts.append(f"Full project source code:\n{project_files_context}")
    if code_context:
        parts.append(f"Currently open file in editor:\n```{language}\n{code_context}\n```")
    parts.append(f"User request: {prompt}")
    full_prompt = '\n\n'.join(parts)

    result = call_yubiai(full_prompt, system_prompt=system_prompt, max_tokens=32768)

    if 'error' in result:
        return jsonify({'error': result['error'], 'action': action}), 500

    return jsonify({
        'response': result.get('response', ''),
        'model': result.get('model', 'gpt-oss-120b'),
        'usage': result.get('usage', {}),
        'action': action,
    })


def parse_agent_json(response_text):
    """Parse JSON from AI response, handling markdown wrapping."""
    # Strip markdown code blocks if present
    text = response_text.strip()
    if text.startswith('```'):
        lines = text.split('\n')
        lines = lines[1:]  # Remove opening ```json or ```
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        text = '\n'.join(lines)

    # Find JSON object
    json_start = text.find('{')
    json_end = text.rfind('}') + 1
    if json_start >= 0 and json_end > json_start:
        return json.loads(text[json_start:json_end])
    return None


def sanitize_flask_code(content, file_path):
    """Fix deprecated Flask 3.x patterns in generated Python code."""
    if not file_path.endswith('.py'):
        return content
    # Replace @app.before_first_request with app_context pattern
    if 'before_first_request' in content:
        # Remove the decorator line
        content = re.sub(r'\s*@\w+\.before_first_request\s*\n', '\n', content)
        # Remove the decorated function (e.g. def create_tables(): db.create_all())
        content = re.sub(
            r'\s*def\s+\w*(?:create_tables|init_db|setup_db)\w*\(\):\s*\n\s+db\.create_all\(\)\s*\n',
            '\n',
            content
        )
        # Ensure db.create_all() is in create_app with app_context
        if 'def create_app' in content and 'db.create_all()' not in content:
            # Find the return app line and add db.create_all() before it
            content = re.sub(
                r'(\n(\s+))(return\s+app)',
                r'\1with app.app_context():\n\2    db.create_all()\n\1\3',
                content,
                count=1
            )
        elif 'def create_app' in content and 'db.create_all()' in content and 'app_context' not in content:
            # db.create_all() exists but not wrapped in app_context — wrap it
            content = re.sub(
                r'(\s+)(db\.create_all\(\))',
                '\\1with app.app_context():\n\\1    db.create_all()',
                content,
                count=1
            )
    # Fix Markup import — handle both standalone and comma-separated imports
    content = content.replace('from flask import Markup', 'from markupsafe import Markup')
    # Handle comma-separated: from flask import Flask, Markup, ...
    content = re.sub(
        r'(from flask import .+),\s*Markup',
        r'\1\nfrom markupsafe import Markup',
        content
    )
    content = re.sub(
        r'from flask import Markup,\s*',
        'from markupsafe import Markup\nfrom flask import ',
        content
    )
    # Fix _request_ctx_stack import
    content = content.replace('from flask import _request_ctx_stack', '# _request_ctx_stack removed in Flask 2.3+')
    return content


def generate_fallback_files(project_path, language='python'):
    """Auto-generate missing critical files (requirements.txt, run.py, static CSS)
    by scanning existing generated code. Called when API fails mid-build."""
    generated = []

    # --- requirements.txt ---
    req_path = os.path.join(project_path, 'requirements.txt')
    if not os.path.isfile(req_path):
        # Scan all .py files for import statements to detect needed packages
        pip_packages = set()
        # Map of import names to pip package names
        import_to_pip = {
            'flask': 'Flask', 'flask_sqlalchemy': 'Flask-SQLAlchemy',
            'flask_login': 'flask-login', 'flask_wtf': 'Flask-WTF',
            'flask_bcrypt': 'Flask-Bcrypt', 'flask_cors': 'Flask-Cors',
            'flask_migrate': 'Flask-Migrate', 'flask_mail': 'Flask-Mail',
            'flask_restful': 'Flask-RESTful', 'flask_socketio': 'Flask-SocketIO',
            'wtforms': 'WTForms', 'sqlalchemy': 'SQLAlchemy',
            'bcrypt': 'bcrypt', 'werkzeug': 'Werkzeug',
            'markupsafe': 'MarkupSafe', 'jinja2': 'Jinja2',
            'requests': 'requests', 'gunicorn': 'gunicorn',
            'python_dotenv': 'python-dotenv', 'dotenv': 'python-dotenv',
            'PIL': 'Pillow', 'celery': 'celery', 'redis': 'redis',
            'jwt': 'PyJWT', 'marshmallow': 'marshmallow',
            'email_validator': 'email-validator',
        }
        for root, _, files in os.walk(project_path):
            for fname in files:
                if not fname.endswith('.py'):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, 'r') as f:
                        content = f.read()
                    for line in content.splitlines():
                        line = line.strip()
                        if line.startswith('import ') or line.startswith('from '):
                            # Extract module name
                            parts = line.split()
                            if parts[0] == 'from':
                                mod = parts[1].split('.')[0]
                            else:
                                mod = parts[1].split('.')[0]
                            if mod in import_to_pip:
                                pip_packages.add(import_to_pip[mod])
                except Exception:
                    continue
        if pip_packages:
            with open(req_path, 'w') as f:
                f.write('\n'.join(sorted(pip_packages)) + '\n')
            generated.append({'path': 'requirements.txt', 'action': 'create'})

    # --- run.py ---
    run_path = os.path.join(project_path, 'run.py')
    if not os.path.isfile(run_path):
        # Detect app structure to generate appropriate run.py
        has_create_app = False
        app_init = os.path.join(project_path, 'app', '__init__.py')
        if os.path.isfile(app_init):
            try:
                with open(app_init, 'r') as f:
                    content = f.read()
                if 'def create_app' in content:
                    has_create_app = True
            except Exception:
                pass

        if has_create_app:
            run_content = """import os
from app import create_app

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', os.environ.get('FLASK_RUN_PORT', 3002)))
    app.run(host='0.0.0.0', port=port, debug=False)
"""
        else:
            # Check for main.py with app object
            main_py = os.path.join(project_path, 'main.py')
            if os.path.isfile(main_py):
                run_content = None  # main.py already exists, don't overwrite
            else:
                run_content = """import os
from app import create_app

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', os.environ.get('FLASK_RUN_PORT', 3002)))
    app.run(host='0.0.0.0', port=port, debug=False)
"""
        if run_content:
            with open(run_path, 'w') as f:
                f.write(run_content)
            generated.append({'path': 'run.py', 'action': 'create'})

    # --- Static CSS fallback ---
    css_dir = os.path.join(project_path, 'app', 'static', 'css')
    css_path = os.path.join(css_dir, 'styles.css')
    if os.path.isdir(os.path.join(project_path, 'app', 'templates')) and not os.path.isfile(css_path):
        os.makedirs(css_dir, exist_ok=True)
        css_content = """/* Auto-generated fallback styles */
:root {
    --primary: #667eea;
    --primary-dark: #5a67d8;
    --bg-dark: #0f0f23;
    --bg-card: #1a1a2e;
    --text: #e2e8f0;
    --text-muted: #a0aec0;
    --border: #2d3748;
    --success: #48bb78;
    --danger: #fc8181;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Segoe UI', system-ui, sans-serif;
    background: linear-gradient(135deg, var(--bg-dark), #16213e);
    color: var(--text);
    min-height: 100vh;
}
.container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
.card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 2rem;
    margin-bottom: 1.5rem;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
}
.btn {
    padding: 0.75rem 1.5rem;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    font-weight: 600;
    transition: all 0.3s;
}
.btn-primary {
    background: linear-gradient(135deg, var(--primary), #764ba2);
    color: white;
}
.btn-primary:hover { transform: translateY(-2px); box-shadow: 0 4px 15px rgba(102,126,234,0.4); }
.btn-danger { background: var(--danger); color: white; }
.form-control {
    width: 100%;
    padding: 0.75rem 1rem;
    background: var(--bg-dark);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    font-size: 1rem;
    margin-bottom: 1rem;
}
.form-control:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(102,126,234,0.2); }
.alert { padding: 1rem; border-radius: 8px; margin-bottom: 1rem; }
.alert-success { background: rgba(72,187,120,0.15); border: 1px solid var(--success); color: var(--success); }
.alert-danger { background: rgba(252,129,129,0.15); border: 1px solid var(--danger); color: var(--danger); }
h1, h2, h3 { background: linear-gradient(135deg, var(--primary), #764ba2); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
a { color: var(--primary); text-decoration: none; }
a:hover { text-decoration: underline; }
.navbar {
    background: var(--bg-card);
    padding: 1rem 2rem;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
}
@media (max-width: 768px) {
    .container { padding: 1rem; }
    .card { padding: 1.5rem; }
}
"""
        with open(css_path, 'w') as f:
            f.write(css_content)
        generated.append({'path': 'app/static/css/styles.css', 'action': 'create'})

    # --- Static JS fallback ---
    js_dir = os.path.join(project_path, 'app', 'static', 'js')
    js_path = os.path.join(js_dir, 'main.js')
    if os.path.isdir(os.path.join(project_path, 'app', 'templates')) and not os.path.isfile(js_path):
        os.makedirs(js_dir, exist_ok=True)
        js_content = """// Auto-generated fallback JS
document.addEventListener('DOMContentLoaded', function() {
    // Auto-dismiss alerts after 5 seconds
    document.querySelectorAll('.alert').forEach(function(alert) {
        setTimeout(function() { alert.style.opacity = '0'; setTimeout(function() { alert.remove(); }, 300); }, 5000);
    });
    // Form validation feedback
    document.querySelectorAll('form').forEach(function(form) {
        form.addEventListener('submit', function(e) {
            var btn = form.querySelector('button[type=\"submit\"]');
            if (btn) { btn.disabled = true; btn.textContent = 'Processing...'; }
        });
    });
});
"""
        with open(js_path, 'w') as f:
            f.write(js_content)
        generated.append({'path': 'app/static/js/main.js', 'action': 'create'})

    return generated


def apply_file_changes(project_path, files_list):
    """Apply file changes from agent response to disk."""
    created_files = []
    errors = []

    for file_info in files_list:
        file_rel_path = file_info.get('path', '')
        file_content = file_info.get('content', '')
        action = file_info.get('action', 'create')

        # Sanitize Flask code for compatibility
        file_content = sanitize_flask_code(file_content, file_rel_path)

        if not file_rel_path:
            continue

        full_path = os.path.join(project_path, file_rel_path)

        # Security check
        real_base = os.path.realpath(project_path)
        real_target = os.path.realpath(full_path)
        if not real_target.startswith(real_base):
            errors.append(f"Skipped {file_rel_path}: path traversal detected")
            continue

        try:
            if action == 'delete':
                if os.path.exists(full_path):
                    os.remove(full_path)
                    created_files.append({'path': file_rel_path, 'action': 'deleted'})
            else:
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, 'w') as f:
                    f.write(file_content)
                created_files.append({'path': file_rel_path, 'action': action})
        except Exception as e:
            errors.append(f"Error with {file_rel_path}: {str(e)}")

    return created_files, errors


def estimate_project_size(prompt):
    """Estimate if a project is large (needs multi-request) based on the prompt."""
    large_indicators = [
        'registration', 'login', 'signup', 'sign-up', 'authentication',
        'chatbot', 'chat interface', 'dashboard', 'admin',
        'database', 'sqlalchemy', 'models', 'migrations',
        'full-stack', 'fullstack', 'production-ready', 'production ready',
        'responsive', 'mobile', 'tablet', 'desktop',
        'csrf', 'bcrypt', 'jwt', 'session',
        'templates', 'base.html', 'multiple pages',
        'unit test', 'pytest', 'testing',
        'readme', 'documentation',
        'saas', 'e-commerce', 'ecommerce', 'marketplace',
        'api', 'rest api', 'crud',
        'bootstrap', 'tailwind',
    ]
    prompt_lower = prompt.lower()
    matches = sum(1 for indicator in large_indicators if indicator in prompt_lower)
    # If 3+ indicators or prompt is very long, it's a large project
    return matches >= 3 or len(prompt) > 1500


@ai_bp.route('/api/ai/agent', methods=['POST'])
@login_required
def ai_agent(user):
    """YubiAI Autonomous Agent — fully autonomous multi-request agent.
    For small projects: single API call (plan + build together).
    For large projects: multi-request (plan first, then batch-generate files).
    Then: Install → Test → Fix (up to 3 loops) → Deploy → Verify."""
    data = request.get_json()
    prompt = data.get('prompt', '')
    project_id = data.get('project_id')
    error_context = data.get('error_context', '')
    auto_deploy = data.get('auto_deploy', True)

    if not prompt or not project_id:
        return jsonify({'error': 'Prompt and project_id are required'}), 400

    conn = get_db()
    project = conn.execute(
        'SELECT * FROM projects WHERE id = ? AND user_id = ?',
        (project_id, user['id'])
    ).fetchone()
    conn.close()

    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_path = get_project_path(user['id'], project['name'])
    os.makedirs(project_path, exist_ok=True)

    # Track all steps for the response
    steps = []
    all_files = []
    all_errors = []
    final_test_passed = False
    run_command = ''
    deploy_ready = False
    MAX_FIX_LOOPS = 3
    roadmap = []
    install_cmd = ''
    test_cmd = ''

    def add_step(name, status, detail='', duration=0):
        steps.append({'name': name, 'status': status, 'detail': detail, 'duration': round(duration, 1)})

    # === STEP 1: Understand project ===
    step_start = time.time()
    files_context, file_list = get_project_files_context(project_path)
    add_step('Analyzing project', 'done',
             f'Found {len(file_list)} files' if file_list else 'Empty project',
             time.time() - step_start)

    # Decide: single-request (small) or multi-request (large)
    is_large = estimate_project_size(prompt) and not error_context

    if error_context:
        # ---- BUG FIX MODE (always single request) ----
        step_start = time.time()
        full_prompt = f"""Project: {project['name']} (Language: {project['language']})
Project directory: {', '.join(file_list) if file_list else '(empty)'}

Current project files:
{files_context if files_context else '(empty project)'}

PREVIOUS ERROR OUTPUT:
{error_context}

User request: Fix the error above. {prompt}

IMPORTANT: Only modify files that need fixing. Do NOT regenerate files that are working correctly."""
        result = call_yubiai(full_prompt, system_prompt=AGENT_SYSTEM_PROMPT, max_tokens=32768)

        if 'error' in result:
            add_step('Calling YubiAI', 'failed', result['error'], time.time() - step_start)
            return jsonify({'error': result['error'], 'agent_executed': False, 'steps': steps})

        response_text = result.get('response', '')
        try:
            agent_response = parse_agent_json(response_text)
            if not agent_response:
                add_step('Calling YubiAI', 'failed', 'Non-structured response', time.time() - step_start)
                return jsonify({'response': response_text, 'agent_executed': False, 'steps': steps, 'message': 'AI returned non-structured response'})
        except json.JSONDecodeError:
            add_step('Calling YubiAI', 'failed', 'JSON parse error', time.time() - step_start)
            return jsonify({'response': response_text, 'agent_executed': False, 'steps': steps, 'message': 'Could not parse AI response'})

        roadmap = agent_response.get('roadmap', [])
        run_command = agent_response.get('run_command', '')
        install_cmd = agent_response.get('install_command', '')
        test_cmd = agent_response.get('test_command', '')
        add_step('Planning & generating fix', 'done',
                 f'{len(agent_response.get("files", []))} files to fix',
                 time.time() - step_start)

        # Write fix files
        step_start = time.time()
        files_list = agent_response.get('files', [])
        created_files, errors = apply_file_changes(project_path, files_list)
        all_files.extend(created_files)
        all_errors.extend(errors)
        add_step('Writing files', 'done',
                 f'{len(created_files)} files written',
                 time.time() - step_start)

    elif is_large:
        # ---- MULTI-REQUEST MODE (for big projects) ----
        # Phase 1: Plan only — get file groups
        step_start = time.time()
        plan_prompt = f"""Project: {project['name']} (Language: {project['language']})
Project directory: {', '.join(file_list) if file_list else '(empty)'}

User request: {prompt}

Plan this project. List ALL files needed, grouped into logical batches. Do NOT write any code yet."""

        plan_result = call_yubiai(plan_prompt, system_prompt=AGENT_PLAN_PROMPT, max_tokens=8192)

        if 'error' in plan_result:
            # Don't abort — fall back to single-request mode
            add_step('Planning project', 'failed', f'Fallback: {plan_result["error"][:80]}', time.time() - step_start)
            is_large = False
            plan_response = None

        if is_large:
            try:
                plan_response = parse_agent_json(plan_result.get('response', ''))
                if not plan_response or not plan_response.get('file_groups'):
                    # Fallback: if plan doesn't have file_groups, treat as single-request
                    add_step('Planning project', 'done', 'Falling back to single-request mode', time.time() - step_start)
                    is_large = False  # Will fall through to single-request below
                    plan_response = None
                else:
                    file_groups = plan_response.get('file_groups', [])
                    total_files = sum(len(g.get('files', [])) for g in file_groups)
                    roadmap = plan_response.get('roadmap', [])
                    run_command = plan_response.get('run_command', '')
                    install_cmd = plan_response.get('install_command', '')
                    test_cmd = plan_response.get('test_command', '')
                    add_step('Planning project', 'done',
                             f'{total_files} files in {len(file_groups)} groups, {len(roadmap)} steps',
                             time.time() - step_start)
            except (json.JSONDecodeError, Exception) as e:
                add_step('Planning project', 'done', f'Fallback to single-request: {str(e)[:50]}', time.time() - step_start)
                is_large = False
                plan_response = None

        # Phase 2: Generate files in batches
        if is_large and plan_response:
            for group_idx, group in enumerate(file_groups):
                step_start = time.time()
                group_name = group.get('group_name', f'Batch {group_idx + 1}')
                group_desc = group.get('description', '')
                group_files = group.get('files', [])

                if not group_files:
                    continue

                # Build context of already-generated files for cross-file imports
                existing_files_ctx = ''
                if all_files:
                    existing_files_ctx, _ = get_project_files_context(project_path, max_file_size=3000)

                batch_prompt = f"""Project: {project['name']} (Language: {project['language']})
Full project plan: {json.dumps(roadmap)}
All planned files: {json.dumps([f for g in file_groups for f in g.get('files', [])])}

{'Already generated files (for import references):' + chr(10) + existing_files_ctx if existing_files_ctx else ''}

User request: {prompt}

Now generate COMPLETE code for these files ONLY:
Group: {group_name} — {group_desc}
Files to generate: {json.dumps(group_files)}

Generate each file with full, production-ready code. Make sure imports reference files from other groups correctly."""

                batch_result = call_yubiai(batch_prompt, system_prompt=AGENT_BATCH_PROMPT, max_tokens=32768)

                if 'error' in batch_result:
                    add_step(f'Generating {group_name}', 'failed', batch_result['error'], time.time() - step_start)
                    all_errors.append(f'Failed to generate {group_name}: {batch_result["error"]}')
                    continue

                try:
                    batch_response = parse_agent_json(batch_result.get('response', ''))
                    if batch_response and batch_response.get('files'):
                        batch_files = batch_response.get('files', [])
                        created, errs = apply_file_changes(project_path, batch_files)
                        all_files.extend(created)
                        all_errors.extend(errs)
                        add_step(f'Generating {group_name}', 'done',
                                 f'{len(created)} files ({group_desc})',
                                 time.time() - step_start)
                    else:
                        add_step(f'Generating {group_name}', 'failed', 'No files in response', time.time() - step_start)
                        all_errors.append(f'{group_name}: empty response')
                except Exception as e:
                    add_step(f'Generating {group_name}', 'failed', str(e)[:100], time.time() - step_start)
                    all_errors.append(f'{group_name}: {str(e)}')

    # ---- SINGLE-REQUEST MODE (small projects or fallback) ----
    if not error_context and not (is_large and all_files):
        step_start = time.time()
        full_prompt = f"""Project: {project['name']} (Language: {project['language']})
Project directory: {', '.join(file_list) if file_list else '(empty)'}

Current project files:
{files_context if files_context else '(empty project)'}

User request: {prompt}"""

        result = call_yubiai(full_prompt, system_prompt=AGENT_SYSTEM_PROMPT, max_tokens=32768)

        if 'error' in result:
            add_step('Calling YubiAI', 'failed', result['error'], time.time() - step_start)
            return jsonify({'error': result['error'], 'agent_executed': False, 'steps': steps})

        response_text = result.get('response', '')
        try:
            agent_response = parse_agent_json(response_text)
            if not agent_response:
                add_step('Calling YubiAI', 'failed', 'Non-structured response', time.time() - step_start)
                return jsonify({'response': response_text, 'agent_executed': False, 'steps': steps, 'message': 'AI returned non-structured response'})
        except json.JSONDecodeError:
            add_step('Calling YubiAI', 'failed', 'JSON parse error', time.time() - step_start)
            return jsonify({'response': response_text, 'agent_executed': False, 'steps': steps, 'message': 'Could not parse AI response'})

        roadmap = agent_response.get('roadmap', [])
        run_command = agent_response.get('run_command', '')
        install_cmd = agent_response.get('install_command', '')
        test_cmd = agent_response.get('test_command', '')
        add_step('Planning & generating code', 'done',
                 f'{len(roadmap)} steps planned, {len(agent_response.get("files", []))} files',
                 time.time() - step_start)

        # Write files
        step_start = time.time()
        files_list = agent_response.get('files', [])
        created_files, errors = apply_file_changes(project_path, files_list)
        all_files.extend(created_files)
        all_errors.extend(errors)
        add_step('Writing files', 'done',
                 f'{len(created_files)} files written' + (f', {len(errors)} errors' if errors else ''),
                 time.time() - step_start)

    # === FALLBACK FILE GENERATION ===
    # When API fails mid-build, auto-generate missing critical files
    if all_files and project['language'] == 'python':
        fallback_files = generate_fallback_files(project_path, language='python')
        if fallback_files:
            all_files.extend(fallback_files)
            fallback_names = ', '.join(f['path'] for f in fallback_files)
            add_step('Auto-generating missing files', 'done', f'Created: {fallback_names}')
        # Set fallback commands if they were never set (API failed before plan was returned)
        if not run_command:
            if os.path.isfile(os.path.join(project_path, 'run.py')):
                run_command = 'python run.py'
            elif os.path.isfile(os.path.join(project_path, 'main.py')):
                run_command = 'python main.py'
        if not install_cmd and os.path.isfile(os.path.join(project_path, 'requirements.txt')):
            install_cmd = 'pip install -r requirements.txt'
        if not test_cmd:
            if os.path.isfile(os.path.join(project_path, 'run.py')):
                test_cmd = 'python -m py_compile run.py'
            elif os.path.isfile(os.path.join(project_path, 'main.py')):
                test_cmd = 'python -m py_compile main.py'

    # === INSTALL DEPENDENCIES ===
    install_result = None
    if install_cmd and all_files:
        step_start = time.time()
        # Clean non-pip packages (e.g. Bootstrap) from requirements.txt
        sanitize_requirements(project_path)
        # Use --upgrade to avoid version conflicts with system packages
        safe_install_cmd = install_cmd
        if 'pip install' in safe_install_cmd and '--upgrade' not in safe_install_cmd:
            safe_install_cmd = safe_install_cmd.replace('pip install', 'pip install --upgrade')
        install_result = execute_test_command(project_path, safe_install_cmd, timeout=120)
        status = 'done' if install_result['success'] else 'failed'
        detail = 'Dependencies installed' if install_result['success'] else (install_result.get('stderr', '') or install_result.get('stdout', ''))[:200]
        add_step('Installing dependencies', status, detail, time.time() - step_start)

    # === TEST → FIX LOOP (up to MAX_FIX_LOOPS) ===
    fix_iterations = []

    if test_cmd and all_files:
        for fix_attempt in range(MAX_FIX_LOOPS + 1):  # 0 = initial test, 1-3 = fix attempts
            step_start = time.time()
            time.sleep(0.5)
            test_result = execute_test_command(project_path, test_cmd)
            test_output = (test_result.get('stderr', '') or test_result.get('stdout', ''))[:2000]

            if test_result['success']:
                final_test_passed = True
                label = 'Testing code' if fix_attempt == 0 else f'Re-testing (attempt {fix_attempt})'
                add_step(label, 'done', 'All tests passed', time.time() - step_start)
                break
            else:
                label = 'Testing code' if fix_attempt == 0 else f'Re-testing (attempt {fix_attempt})'
                add_step(label, 'failed', test_output[:150], time.time() - step_start)

                # If we still have fix attempts left, call AI to fix
                if fix_attempt < MAX_FIX_LOOPS:
                    step_start = time.time()
                    current_files_ctx = get_project_files_context(project_path)[0]
                    fix_prompt = f"""Project: {project['name']} (Language: {project['language']})

Current project files:
{current_files_ctx}

TEST COMMAND FAILED: {test_cmd}
ERROR OUTPUT:
{test_output}

Fix this error. Only modify the files that have the bug. Do NOT rewrite everything."""

                    fix_api_result = call_yubiai(fix_prompt, system_prompt=AGENT_SYSTEM_PROMPT, max_tokens=32768)
                    if 'error' in fix_api_result:
                        add_step(f'Auto-fix #{fix_attempt + 1}', 'failed', fix_api_result['error'], time.time() - step_start)
                        fix_iterations.append({'attempt': fix_attempt + 1, 'success': False, 'error': fix_api_result['error']})
                        break

                    try:
                        fix_response = parse_agent_json(fix_api_result.get('response', ''))
                        if fix_response and fix_response.get('files'):
                            fixed_files, fix_errors = apply_file_changes(project_path, fix_response.get('files', []))
                            all_files.extend(fixed_files)
                            all_errors.extend(fix_errors)
                            fix_msg = fix_response.get('message', f'Fixed {len(fixed_files)} files')
                            add_step(f'Auto-fix #{fix_attempt + 1}', 'done',
                                     f'{fix_msg} ({len(fixed_files)} files)',
                                     time.time() - step_start)
                            fix_iterations.append({
                                'attempt': fix_attempt + 1,
                                'success': True,
                                'files': fixed_files,
                                'message': fix_msg,
                            })
                            # Update run/test commands if provided
                            if fix_response.get('run_command'):
                                run_command = fix_response['run_command']
                            if fix_response.get('test_command'):
                                test_cmd = fix_response['test_command']
                        else:
                            add_step(f'Auto-fix #{fix_attempt + 1}', 'failed', 'No file changes in fix', time.time() - step_start)
                            fix_iterations.append({'attempt': fix_attempt + 1, 'success': False, 'error': 'No changes'})
                            break
                    except Exception as e:
                        add_step(f'Auto-fix #{fix_attempt + 1}', 'failed', str(e)[:100], time.time() - step_start)
                        fix_iterations.append({'attempt': fix_attempt + 1, 'success': False, 'error': str(e)})
                        break
    else:
        # No test command — assume code is ready
        final_test_passed = True
        if all_files:
            add_step('Testing code', 'skipped', 'No test command provided')

    # === AUTO-DEPLOY if tests passed ===
    deploy_result = None
    deploy_ready = final_test_passed

    if auto_deploy and deploy_ready and run_command:
        step_start = time.time()
        try:
            from deploy import deploy_project_internal
            deploy_result = deploy_project_internal(user, project_id, project_path, run_command)
            if deploy_result and deploy_result.get('success'):
                add_step('Deploying app', 'done',
                         f'Running on port {deploy_result.get("port", "?")}',
                         time.time() - step_start)
            else:
                err = deploy_result.get('error', 'Unknown') if deploy_result else 'Deploy function failed'
                add_step('Deploying app', 'failed', err[:150], time.time() - step_start)
        except Exception as e:
            add_step('Deploying app', 'failed', str(e)[:150], time.time() - step_start)
            deploy_result = None

    return jsonify({
        'agent_executed': True,
        'phase': 'fix' if error_context else ('multi-build' if is_large and all_files else 'build'),
        'roadmap': roadmap,
        'plan': '',
        'files': all_files,
        'run_command': run_command,
        'test_command': test_cmd,
        'install_command': install_cmd,
        'deploy_ready': deploy_ready,
        'message': f'Agent completed: {len(all_files)} files generated' + (f' in {len([s for s in steps if s["name"].startswith("Generating")])} batches' if is_large else ''),
        'errors': all_errors,
        'model': 'gpt-oss-120b',
        'steps': steps,
        'fix_iterations': fix_iterations,
        'tests_passed': final_test_passed,
        'deploy_result': deploy_result,
    })
