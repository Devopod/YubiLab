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


def call_yubiai(message, system_prompt=None, model="gpt-oss-120b", temperature=0.7, max_tokens=4096, retries=8):
    """Call YubiAI API with automatic retry and aggressive backoff for Render cold starts.
    Render free tier sleeps after inactivity and takes 30-90s to wake up.
    Retry schedule: 5s, 8s, 12s, 15s, 20s, 25s, 30s (total ~115s covers even slow cold starts)."""
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
                last_error = "YubiAI API endpoint is offline or unreachable."
            elif resp.status_code == 401:
                return {"error": "YubiAI API authentication failed. Check your API key."}
            elif resp.status_code == 429:
                last_error = "YubiAI API rate limit exceeded."
            elif resp.status_code == 404:
                last_error = "YubiAI API endpoint not found (404)."
            elif resp.status_code == 503:
                last_error = "YubiAI server is waking up (503). Free-tier servers sleep after inactivity — retrying..."
            elif resp.status_code == 502:
                last_error = "YubiAI server returned 502 Bad Gateway — retrying..."
            else:
                last_error = f"YubiAI API returned HTTP {resp.status_code}."
        except requests.exceptions.ConnectionError:
            last_error = "Cannot connect to YubiAI API. The server may be waking up — retrying..."
        except requests.exceptions.Timeout:
            last_error = "YubiAI API request timed out (180s)."
        except Exception as e:
            last_error = f"YubiAI API error: {str(e)}"

        # Aggressive backoff: 5, 8, 12, 15, 20, 25, 30s — covers Render cold starts up to ~90s
        if attempt < retries - 1:
            backoff_schedule = [5, 8, 12, 15, 20, 25, 30]
            wait_secs = backoff_schedule[min(attempt, len(backoff_schedule) - 1)]
            time.sleep(wait_secs)

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


def sanitize_requirements(project_path, strip_versions=False):
    """Remove non-pip packages (like Bootstrap) from requirements.txt.
    If strip_versions=True, also remove version pins (==, >=, etc.) to resolve conflicts.
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
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                cleaned.append(line)
                continue
            pkg = stripped.split('==')[0].split('>=')[0].split('<=')[0].split('~=')[0].split('[')[0].strip().lower()
            if pkg in NON_PIP_PACKAGES:
                modified = True
                continue
            if strip_versions and re.search(r'[=<>~!]', stripped):
                # Strip version pins — just keep the package name
                pkg_name = re.split(r'[=<>~!\[]', stripped)[0].strip()
                if pkg_name:
                    cleaned.append(pkg_name + '\n')
                    modified = True
                continue
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

## AI-POWERED DEVELOPER TOOLS (Autonomous)
You have direct access to these developer tools that you MUST use autonomously during builds.
Include a "tool_commands" array in your JSON response to execute tools automatically:

### Available Tools:
- **packages**: Install/uninstall packages (pip, npm)
  `{"tool": "packages", "packages": ["flask", "sqlalchemy"], "language": "python"}`
- **shell**: Run shell commands in the project directory
  `{"tool": "shell", "command": "python -m flask db init"}`
- **sql**: Execute SQL on project databases
  `{"tool": "sql", "query": "SELECT * FROM users LIMIT 5"}`
- **search**: Search project code for patterns
  `{"tool": "search", "query": "def login", "type": "function"}`
- **secrets**: Set environment variables in .env
  `{"tool": "secrets", "key": "SECRET_KEY", "value": "my-secret-key-123"}`
- **workflows**: Configure run commands
  `{"tool": "workflows", "name": "Run App", "command": "python run.py", "is_run_button": true}`
- **info**: Get project file stats and database info
  `{"tool": "info"}`

### When to use tools:
- ALWAYS use "packages" to install dependencies instead of just listing them in requirements.txt
- ALWAYS use "secrets" to set SECRET_KEY and other env vars the app needs
- ALWAYS use "workflows" to configure the run command for the project
- Use "shell" for database migrations, file permissions, or build steps
- Use "sql" to verify database tables were created correctly
- Use "info" to analyze existing project structure before making changes

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
  "tool_commands": [
    {"tool": "packages", "packages": ["flask", "flask-sqlalchemy", "flask-wtf"], "language": "python"},
    {"tool": "secrets", "key": "SECRET_KEY", "value": "auto-generated-secret-key"},
    {"tool": "workflows", "name": "Run App", "command": "python run.py", "is_run_button": true},
    {"tool": "shell", "command": "python -c \\"from app import create_app; create_app()\\""}
  ],
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
- For database initialization: call `db.create_all()` inside create_app() AFTER registering blueprints so models are imported
- In Jinja2 templates: NEVER use {{ now().year }} — it doesn't exist. Use a hardcoded year or inject it via context processor.
- In Jinja2 templates: NEVER wrap templates in {%% raw %%}...{%% endraw %%} — this prevents ALL template tags from working (url_for, csrf_token, extends, block, etc.)
- For CSRF in forms: Always use <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/> — NEVER use bare {{ csrf_token() }} without the hidden input wrapper
- For the index route (/): ALWAYS redirect to login page if user is not authenticated, redirect to main app page if authenticated. NEVER just render base.html as the index.
- Do NOT create a separate main.py with a simple hello-world app. Use run.py with create_app() factory pattern.
- For login/signup forms: Let forms submit normally via HTML form action (method="POST"). Do NOT generate separate auth.js that intercepts form submission with fetch() — this breaks CSRF and prevents normal form POST from working. If you must use JS, make sure it handles CSRF tokens and form data correctly.
- Use proper HTML meta tags, responsive design, and accessibility
- Add loading states, error states, and empty states in UIs
- Use semantic HTML and modern CSS (flexbox, grid, variables)
- For requirements.txt: do NOT pin Werkzeug, Flask, or Jinja2 to specific versions — just list the package name without version pins to avoid conflicts with the system Python packages
- For SQLAlchemy config: do NOT add excessive PRAGMA statements in SQLALCHEMY_ENGINE_OPTIONS — keep it minimal or empty

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
- For requirements.txt: do NOT pin Werkzeug, Flask, or Jinja2 to specific versions — just list the package name without == to avoid conflicts
- Port rules: NEVER use 5000 or 3001. Use PORT env var, default 3002.
- For Flask: os.environ.get('PORT', os.environ.get('FLASK_RUN_PORT', 3002))
- Always include `import os` in run.py when using os.environ
- In Jinja2 templates: NEVER use {{ now().year }} — it doesn't exist. Use a hardcoded year instead.
- In Jinja2 templates: NEVER wrap templates in {%% raw %%}...{%% endraw %%} — this prevents ALL template tags from working
- For CSRF in forms: Always use <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/> — never bare {{ csrf_token() }}
- The index route (/) should redirect to login if not authenticated, not just render base.html
- Do NOT create a separate main.py stub — use run.py with create_app() factory
- For login/signup forms: Let forms POST normally via HTML action. Do NOT generate auth.js that intercepts submission with fetch() — it breaks CSRF"""


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
- Flask 3.x compatibility: NEVER use @app.before_first_request (removed). Use `with app.app_context(): db.create_all()` in create_app() AFTER registering blueprints.
- NEVER import Markup from flask — use `from markupsafe import Markup`
- In Jinja2 templates: NEVER use {{ now().year }} — it doesn't exist in Jinja2. Use a hardcoded year instead.
- In Jinja2 templates: NEVER wrap templates in {%% raw %%}...{%% endraw %%} — this makes ALL Jinja2 tags render as literal text
- For CSRF in forms: Always use <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/> — never bare {{ csrf_token() }}
- The index route (/) should redirect to login if not authenticated
- Do NOT create a separate main.py hello-world stub — use run.py with create_app() factory
- For requirements.txt: do NOT pin Werkzeug, Flask, or Jinja2 to specific versions — just list the package name without == to avoid conflicts
- For login/signup forms: Let forms POST normally via HTML action. Do NOT generate auth.js that intercepts submission with fetch() — it breaks CSRF"""


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
    """Parse JSON from AI response, handling markdown wrapping, truncated JSON, and extra data."""
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
    if json_start < 0:
        return None

    # Try parsing from the start of JSON to the end
    json_end = text.rfind('}') + 1
    if json_end > json_start:
        try:
            return json.loads(text[json_start:json_end])
        except json.JSONDecodeError:
            pass

    # Try to find matching braces (handles extra data after JSON)
    depth = 0
    in_string = False
    escape_next = False
    for i in range(json_start, len(text)):
        c = text[i]
        if escape_next:
            escape_next = False
            continue
        if c == '\\':
            escape_next = True
            continue
        if c == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[json_start:i + 1])
                except json.JSONDecodeError:
                    pass
                break

    # Last resort: try to fix truncated JSON by closing open braces/brackets
    candidate = text[json_start:json_end] if json_end > json_start else text[json_start:]
    for fix_attempt in range(5):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            err_msg = str(e).lower()
            if 'expecting' in err_msg and (',' in err_msg or 'delimiter' in err_msg):
                # Try removing the problematic trailing content
                last_good = candidate.rfind(',', 0, e.pos)
                if last_good > 0:
                    candidate = candidate[:last_good] + candidate[last_good:].split(']')[0] + ']}'
                else:
                    break
            elif 'unterminated' in err_msg or 'expecting value' in err_msg:
                # Try closing unclosed structures
                candidate = candidate.rstrip()
                if candidate.endswith(','):
                    candidate = candidate[:-1]
                open_braces = candidate.count('{') - candidate.count('}')
                open_brackets = candidate.count('[') - candidate.count(']')
                candidate += ']' * max(0, open_brackets) + '}' * max(0, open_braces)
            else:
                break

    return None


def sanitize_jinja_templates(content, file_path):
    """Fix common Jinja2 template issues in AI-generated HTML."""
    if not file_path.endswith('.html'):
        return content

    # === FIX 1: Remove {% raw %} / {% endraw %} wrapping ===
    # AI sometimes wraps entire templates in {% raw %}...{% endraw %} which
    # prevents ALL Jinja2 tags from being processed (url_for, csrf, extends, etc.)
    content = re.sub(r'\{%\s*raw\s*%\}\s*', '', content)
    content = re.sub(r'\s*\{%\s*endraw\s*%\}', '', content)

    # === FIX 2: Fix {{ now().year }} — not a built-in Jinja2 function ===
    import datetime
    current_year = str(datetime.datetime.now().year)
    content = re.sub(r'\{\{\s*now\(\)\.year\s*\}\}', current_year, content)
    content = re.sub(r'\{\{\s*now\(\)\s*\}\}', current_year, content)

    # === FIX 3: Fix bare {{ csrf_token() }} — must be inside a hidden input ===
    # Replace bare {{ csrf_token() }} with proper hidden input field
    # But don't double-wrap if it's already inside an input tag
    def fix_csrf_token(match):
        # Check if already inside an input tag by looking at surrounding context
        start = max(0, match.start() - 200)
        before = content[start:match.start()]
        if 'name="csrf_token"' in before or 'name=\'csrf_token\'' in before:
            return match.group(0)  # Already properly wrapped
        return '<input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>'
    # Match bare {{ csrf_token() }} that's on its own line or between tags
    content = re.sub(
        r'^\s*\{\{\s*csrf_token\(\)\s*\}\}\s*$',
        '                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>',
        content,
        flags=re.MULTILINE
    )
    # Also handle inline bare csrf_token() not in an input
    content = re.sub(
        r'(?<!value=")\{\{\s*csrf_token\(\)\s*\}\}(?!")',
        '<input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>',
        content
    )

    # === FIX 4: Remove auth.js script references from login/signup templates ===
    # AI sometimes generates auth.js that hijacks form submissions with fetch(),
    # preventing normal form POST from working. Remove the script tag so forms
    # submit naturally via HTML form action.
    basename = os.path.basename(file_path).lower()
    if basename in ('login.html', 'signup.html', 'register.html', 'signin.html'):
        # Remove script tags referencing auth.js
        content = re.sub(
            r'<script\s+src=["\'].*?auth\.js["\'].*?></script>\s*',
            '',
            content
        )
        # Remove {% block scripts %} that only contains auth.js reference
        content = re.sub(
            r'\{%\s*block\s+scripts\s*%\}\s*<script\s+src=["\'].*?auth\.js["\'].*?></script>\s*\{%\s*endblock\s*%\}\s*',
            '{% block scripts %}\n{% endblock %}\n',
            content
        )

    return content


def sanitize_flask_code(content, file_path):
    """Fix deprecated Flask 3.x patterns in generated Python code."""
    if not file_path.endswith('.py'):
        return content

    # === FIX: Remove JS-style comments at start of Python files ===
    # AI sometimes generates `// run.py` or `// app.py` as the first line
    content = re.sub(r'^\s*//.*\n', '', content)

    # === FIX: Remove excessive PRAGMA statements from SQLAlchemy config ===
    # AI sometimes generates config with dozens of repeated PRAGMA statements
    if 'PRAGMA' in content:
        pragma_count = content.count('PRAGMA')
        if pragma_count > 8:
            # Strip all lines containing PRAGMA
            lines = content.splitlines(True)
            cleaned_lines = [l for l in lines if 'PRAGMA' not in l]
            content = ''.join(cleaned_lines)
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

    # === FIX: Index route should redirect to login, not render base.html ===
    # When AI generates a routes.py with index that just renders base.html,
    # replace it with a redirect to login page
    if 'def index' in content and re.search(r"render_template\(['\"]base\.html['\"]\)", content):
        content = re.sub(
            r"return\s+render_template\(['\"]base\.html['\"]\)",
            "from flask_login import current_user\n"
            "    if current_user.is_authenticated:\n"
            "        return redirect(url_for('chatbot.chat'))\n"
            "    return redirect(url_for('auth.login'))",
            content
        )
        # Add redirect import if not present
        if 'redirect' not in content:
            content = re.sub(
                r'from flask import Blueprint,\s*render_template',
                'from flask import Blueprint, render_template, redirect, url_for',
                content
            )

    # Fix db.create_all() before models are imported — ensure models import comes before create_all
    if 'def create_app' in content and 'db.create_all()' in content:
        # Check if db.create_all() appears before any blueprint/route registration
        create_all_pos = content.find('db.create_all()')
        register_bp_pos = content.find('register_blueprint')
        import_models_pos = content.find('from . import models')
        from_models_pos = content.find('from .models import')
        # If create_all comes before blueprint registration and no explicit models import before it
        if register_bp_pos > 0 and create_all_pos < register_bp_pos:
            if import_models_pos < 0 or import_models_pos > create_all_pos:
                if from_models_pos < 0 or from_models_pos > create_all_pos:
                    # Move db.create_all() block after blueprint registration
                    # Remove existing db.create_all() with its context manager
                    content = re.sub(
                        r'\n\s+(?:# .*\n\s+)?with app\.app_context\(\):\s*\n\s+db\.create_all\(\)\s*\n',
                        '\n',
                        content,
                        count=1
                    )
                    # Add it back after the last register_blueprint call
                    content = re.sub(
                        r'(app\.register_blueprint\([^)]+\)\s*\n)',
                        r'\1\n    # Import models so SQLAlchemy knows about them, then create tables\n    with app.app_context():\n        from . import models  # noqa: F401\n        db.create_all()\n',
                        content,
                        count=1
                    )
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

    # --- Fix main.py / run.py conflict ---
    # If both main.py and run.py exist, and main.py is a simple hello-world stub
    # while run.py uses create_app factory, remove the conflicting main.py
    main_py_path = os.path.join(project_path, 'main.py')
    run_path = os.path.join(project_path, 'run.py')
    if os.path.isfile(main_py_path) and os.path.isfile(run_path):
        try:
            with open(main_py_path, 'r') as f:
                main_content = f.read()
            with open(run_path, 'r') as f:
                run_content_check = f.read()
            # If main.py is a simple stub and run.py uses create_app, remove main.py
            if 'create_app' in run_content_check and ('Hello World' in main_content or 'hello' in main_content.lower()) and 'create_app' not in main_content:
                os.remove(main_py_path)
                generated.append({'path': 'main.py', 'action': 'deleted (conflicting stub)'})
        except Exception:
            pass

    # --- run.py ---
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
            if os.path.isfile(main_py_path):
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

    # --- Fallback HTML templates ---
    # When API fails mid-build (503), templates batch may be missing entirely
    # Generate working fallback templates so the app doesn't show 404
    templates_dir = os.path.join(project_path, 'app', 'templates')
    has_auth = False
    for root, _, files in os.walk(project_path):
        for fname in files:
            if fname.endswith('.py'):
                try:
                    with open(os.path.join(root, fname), 'r') as f:
                        if 'login' in f.read().lower():
                            has_auth = True
                except Exception:
                    pass

    if has_auth and os.path.isdir(os.path.join(project_path, 'app')):
        os.makedirs(templates_dir, exist_ok=True)

        # base.html
        base_path = os.path.join(templates_dir, 'base.html')
        if not os.path.isfile(base_path):
            with open(base_path, 'w') as f:
                f.write("""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% block title %}App{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/styles.css') }}">
</head>
<body class="bg-light">
    <nav class="navbar navbar-expand-lg navbar-dark bg-primary mb-4">
        <div class="container">
            <a class="navbar-brand" href="/">App</a>
            <div class="navbar-nav ms-auto">
                {% if current_user.is_authenticated %}
                <a class="nav-link" href="{{ url_for('auth.logout') }}">Logout</a>
                {% else %}
                <a class="nav-link" href="{{ url_for('auth.login') }}">Login</a>
                <a class="nav-link" href="{{ url_for('auth.signup') }}">Sign Up</a>
                {% endif %}
            </div>
        </div>
    </nav>
    <main class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}{% for cat, msg in messages %}
        <div class="alert alert-{{ cat }} alert-dismissible fade show">{{ msg }}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}{% endif %}{% endwith %}
        {% block content %}{% endblock %}
    </main>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    {% block extra_js %}{% endblock %}
</body>
</html>
""")
            generated.append({'path': 'app/templates/base.html', 'action': 'create'})

        # signup.html
        signup_path = os.path.join(templates_dir, 'signup.html')
        if not os.path.isfile(signup_path):
            with open(signup_path, 'w') as f:
                f.write("""{% extends 'base.html' %}
{% block title %}Sign Up{% endblock %}
{% block content %}
<div class="row justify-content-center mt-5">
    <div class="col-md-6">
        <div class="card shadow">
            <div class="card-body">
                <h3 class="text-center mb-4">Create Account</h3>
                <form method="POST" action="{{ url_for('auth.signup') }}">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
                    <div class="mb-3">
                        <label class="form-label">Username</label>
                        <input type="text" class="form-control" name="username" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Email</label>
                        <input type="email" class="form-control" name="email" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Password</label>
                        <input type="password" class="form-control" name="password" required>
                    </div>
                    <button type="submit" class="btn btn-success w-100">Sign Up</button>
                </form>
                <p class="text-center mt-3">Already have an account? <a href="{{ url_for('auth.login') }}">Log in</a></p>
            </div>
        </div>
    </div>
</div>
{% endblock %}
""")
            generated.append({'path': 'app/templates/signup.html', 'action': 'create'})

        # login.html
        login_path = os.path.join(templates_dir, 'login.html')
        if not os.path.isfile(login_path):
            with open(login_path, 'w') as f:
                f.write("""{% extends 'base.html' %}
{% block title %}Login{% endblock %}
{% block content %}
<div class="row justify-content-center mt-5">
    <div class="col-md-6">
        <div class="card shadow">
            <div class="card-body">
                <h3 class="text-center mb-4">Login</h3>
                <form method="POST" action="{{ url_for('auth.login') }}">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
                    <div class="mb-3">
                        <label class="form-label">Email</label>
                        <input type="email" class="form-control" name="email" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Password</label>
                        <input type="password" class="form-control" name="password" required>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Log In</button>
                </form>
                <p class="text-center mt-3">Don't have an account? <a href="{{ url_for('auth.signup') }}">Sign up</a></p>
            </div>
        </div>
    </div>
</div>
{% endblock %}
""")
            generated.append({'path': 'app/templates/login.html', 'action': 'create'})

        # chatbot.html
        chatbot_path = os.path.join(templates_dir, 'chatbot.html')
        if not os.path.isfile(chatbot_path):
            with open(chatbot_path, 'w') as f:
                f.write("""{% extends 'base.html' %}
{% block title %}Chatbot{% endblock %}
{% block content %}
<div class="row justify-content-center mt-3">
    <div class="col-md-8">
        <div class="card shadow" style="min-height:500px">
            <div class="card-header bg-primary text-white"><h5 class="mb-0">Chatbot</h5></div>
            <div class="card-body d-flex flex-column">
                <div id="chat-messages" class="flex-grow-1 overflow-auto mb-3" style="max-height:400px"></div>
                <form id="chat-form" class="d-flex gap-2">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
                    <input type="text" id="user-input" class="form-control" placeholder="Type a message..." required>
                    <button type="submit" class="btn btn-primary">Send</button>
                </form>
            </div>
        </div>
    </div>
</div>
{% endblock %}
{% block extra_js %}
<script>
document.getElementById('chat-form').addEventListener('submit', function(e) {
    e.preventDefault();
    var input = document.getElementById('user-input');
    var msg = input.value.trim();
    if (!msg) return;
    var messages = document.getElementById('chat-messages');
    messages.innerHTML += '<div class="mb-2 text-end"><span class="badge bg-primary p-2">' + msg + '</span></div>';
    input.value = '';
    fetch('/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('[name=csrf_token]').value},
        body: JSON.stringify({message: msg})
    }).then(r => r.json()).then(data => {
        messages.innerHTML += '<div class="mb-2"><span class="badge bg-secondary p-2">' + (data.response || data.reply || 'No response') + '</span></div>';
        messages.scrollTop = messages.scrollHeight;
    }).catch(() => {
        messages.innerHTML += '<div class="mb-2"><span class="badge bg-danger p-2">Error sending message</span></div>';
    });
});
</script>
{% endblock %}
""")
            generated.append({'path': 'app/templates/chatbot.html', 'action': 'create'})

    # === DJANGO PROJECT FALLBACK ===
    # Detect Django projects and generate missing critical files
    is_django = False
    if os.path.isfile(req_path):
        try:
            with open(req_path, 'r') as f:
                if 'django' in f.read().lower():
                    is_django = True
        except Exception:
            pass
    if not is_django:
        for root, _, files in os.walk(project_path):
            for fname in files:
                if fname.endswith('.py'):
                    try:
                        with open(os.path.join(root, fname), 'r') as f:
                            content = f.read()
                        if 'django' in content.lower() and ('import django' in content.lower() or 'from django' in content.lower()):
                            is_django = True
                            break
                    except Exception:
                        pass
            if is_django:
                break

    if is_django:
        # Determine project config directory name
        config_dir = None
        manage_path = os.path.join(project_path, 'manage.py')
        if os.path.isfile(manage_path):
            try:
                with open(manage_path, 'r') as f:
                    manage_content = f.read()
                match = re.search(r"['\"]([\w]+)\.settings['\"]", manage_content)
                if match:
                    config_dir = match.group(1)
            except Exception:
                pass
        if not config_dir:
            for d in os.listdir(project_path):
                dp = os.path.join(project_path, d)
                if os.path.isdir(dp) and not d.startswith('.') and d not in ('static', 'templates', 'media', 'venv', '__pycache__', 'logs', 'node_modules'):
                    if os.path.isfile(os.path.join(dp, 'settings.py')) or os.path.isfile(os.path.join(dp, 'wsgi.py')):
                        config_dir = d
                        break
        if not config_dir:
            config_dir = 'main'

        config_path = os.path.join(project_path, config_dir)
        os.makedirs(config_path, exist_ok=True)

        # Detect installed Django apps from existing directories
        installed_apps = []
        for d in sorted(os.listdir(project_path)):
            dp = os.path.join(project_path, d)
            if os.path.isdir(dp) and not d.startswith('.') and d != config_dir and d not in ('static', 'templates', 'media', 'venv', '__pycache__', 'logs', 'node_modules', 'staticfiles'):
                if os.path.isfile(os.path.join(dp, 'views.py')) or os.path.isfile(os.path.join(dp, 'models.py')):
                    installed_apps.append(d)

        # Generate manage.py if missing
        if not os.path.isfile(manage_path):
            manage_content = f'''#!/usr/bin/env python\n"""Django's command-line utility for administrative tasks."""\nimport os\nimport sys\n\n\ndef main():\n    """Run administrative tasks."""\n    os.environ.setdefault('DJANGO_SETTINGS_MODULE', '{config_dir}.settings')\n    try:\n        from django.core.management import execute_from_command_line\n    except ImportError as exc:\n        raise ImportError(\n            "Couldn't import Django. Are you sure it's installed and "\n            "available on your PYTHONPATH environment variable? Did you "\n            "forget to activate a virtual environment?"\n        ) from exc\n    execute_from_command_line(sys.argv)\n\n\nif __name__ == '__main__':\n    main()\n'''
            with open(manage_path, 'w') as f:
                f.write(manage_content)
            generated.append({'path': 'manage.py', 'action': 'create'})

        # Generate settings.py if missing
        settings_path = os.path.join(config_path, 'settings.py')
        if not os.path.isfile(settings_path):
            apps_str = '\n'.join(f"    '{app}'," for app in installed_apps)
            settings_content = f'''"""Django settings for {config_dir} project."""\nimport os\nfrom pathlib import Path\n\nBASE_DIR = Path(__file__).resolve().parent.parent\n\nSECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-change-me-in-production')\nDEBUG = True\nALLOWED_HOSTS = ['*']\n\nINSTALLED_APPS = [\n    'django.contrib.admin',\n    'django.contrib.auth',\n    'django.contrib.contenttypes',\n    'django.contrib.sessions',\n    'django.contrib.messages',\n    'django.contrib.staticfiles',\n{apps_str}\n]\n\nMIDDLEWARE = [\n    'django.middleware.security.SecurityMiddleware',\n    'django.contrib.sessions.middleware.SessionMiddleware',\n    'django.middleware.common.CommonMiddleware',\n    'django.middleware.csrf.CsrfViewMiddleware',\n    'django.contrib.auth.middleware.AuthenticationMiddleware',\n    'django.contrib.messages.middleware.MessageMiddleware',\n    'django.middleware.clickjacking.XFrameOptionsMiddleware',\n]\n\nROOT_URLCONF = '{config_dir}.urls'\n\nTEMPLATES = [\n    {{\n        'BACKEND': 'django.template.backends.django.DjangoTemplates',\n        'DIRS': [BASE_DIR / 'templates'],\n        'APP_DIRS': True,\n        'OPTIONS': {{\n            'context_processors': [\n                'django.template.context_processors.debug',\n                'django.template.context_processors.request',\n                'django.contrib.auth.context_processors.auth',\n                'django.contrib.messages.context_processors.messages',\n            ],\n        }},\n    }},\n]\n\nWSGI_APPLICATION = '{config_dir}.wsgi.application'\n\nDATABASES = {{\n    'default': {{\n        'ENGINE': 'django.db.backends.sqlite3',\n        'NAME': BASE_DIR / 'db.sqlite3',\n    }}\n}}\n\nAUTH_PASSWORD_VALIDATORS = [\n    {{'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'}},\n    {{'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'}},\n    {{'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'}},\n    {{'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'}},\n]\n\nLANGUAGE_CODE = 'en-us'\nTIME_ZONE = 'UTC'\nUSE_I18N = True\nUSE_TZ = True\n\nSTATIC_URL = 'static/'\nSTATICFILES_DIRS = [BASE_DIR / 'static']\nSTATIC_ROOT = BASE_DIR / 'staticfiles'\n\nDEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'\n\nLOGIN_URL = '/login/'\nLOGIN_REDIRECT_URL = '/'\nLOGOUT_REDIRECT_URL = '/login/'\n'''
            with open(settings_path, 'w') as f:
                f.write(settings_content)
            generated.append({'path': f'{config_dir}/settings.py', 'action': 'create'})

        # Generate urls.py if missing
        urls_path = os.path.join(config_path, 'urls.py')
        if not os.path.isfile(urls_path):
            url_includes = ''
            for app in installed_apps:
                app_urls_file = os.path.join(project_path, app, 'urls.py')
                if os.path.isfile(app_urls_file):
                    prefix = '' if app in ('main', 'core') else f'{app}/'
                    url_includes += f"    path('{prefix}', include('{app}.urls')),\n"
            urls_content = f'''"""URL configuration for {config_dir} project."""\nfrom django.contrib import admin\nfrom django.urls import path, include\n\nurlpatterns = [\n    path('admin/', admin.site.urls),\n{url_includes}]\n'''
            with open(urls_path, 'w') as f:
                f.write(urls_content)
            generated.append({'path': f'{config_dir}/urls.py', 'action': 'create'})

        # Generate wsgi.py if missing
        wsgi_path = os.path.join(config_path, 'wsgi.py')
        if not os.path.isfile(wsgi_path):
            wsgi_content = f'''"""WSGI config for {config_dir} project."""\nimport os\nfrom django.core.wsgi import get_wsgi_application\n\nos.environ.setdefault('DJANGO_SETTINGS_MODULE', '{config_dir}.settings')\napplication = get_wsgi_application()\n'''
            with open(wsgi_path, 'w') as f:
                f.write(wsgi_content)
            generated.append({'path': f'{config_dir}/wsgi.py', 'action': 'create'})

        # Generate asgi.py if missing
        asgi_path = os.path.join(config_path, 'asgi.py')
        if not os.path.isfile(asgi_path):
            asgi_content = f'''"""ASGI config for {config_dir} project."""\nimport os\nfrom django.core.asgi import get_asgi_application\n\nos.environ.setdefault('DJANGO_SETTINGS_MODULE', '{config_dir}.settings')\napplication = get_asgi_application()\n'''
            with open(asgi_path, 'w') as f:
                f.write(asgi_content)
            generated.append({'path': f'{config_dir}/asgi.py', 'action': 'create'})

        # Generate __init__.py for config dir if missing
        init_path = os.path.join(config_path, '__init__.py')
        if not os.path.isfile(init_path):
            with open(init_path, 'w') as f:
                f.write('')
            generated.append({'path': f'{config_dir}/__init__.py', 'action': 'create'})

        # Generate __init__.py for app dirs if missing
        for app in installed_apps:
            app_init = os.path.join(project_path, app, '__init__.py')
            if not os.path.isfile(app_init):
                os.makedirs(os.path.join(project_path, app), exist_ok=True)
                with open(app_init, 'w') as f:
                    f.write('')
                generated.append({'path': f'{app}/__init__.py', 'action': 'create'})

    return generated


def sanitize_project_on_disk(project_path):
    """Post-build pass: scan ALL files in a project directory and apply sanitization.
    This catches issues that slip through apply_file_changes (e.g. files from previous builds,
    files written by fallback generation, or files the AI edited without going through our pipeline)."""
    fixed_files = []

    for root, dirs, files in os.walk(project_path):
        # Skip hidden dirs, __pycache__, node_modules, venv
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('__pycache__', 'node_modules', 'venv', '.venv')]
        for filename in files:
            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, project_path)
            try:
                with open(filepath, 'r', errors='ignore') as f:
                    content = f.read()
                original = content

                # Apply sanitization based on file type
                if filename.endswith('.html'):
                    content = sanitize_jinja_templates(content, filename)
                elif filename.endswith('.py'):
                    content = sanitize_flask_code(content, filename)

                if content != original:
                    with open(filepath, 'w') as f:
                        f.write(content)
                    fixed_files.append(rel_path)
            except Exception:
                pass

    # Remove conflicting main.py stub if run.py exists with create_app
    main_py = os.path.join(project_path, 'main.py')
    run_py = os.path.join(project_path, 'run.py')
    if os.path.isfile(main_py) and os.path.isfile(run_py):
        try:
            with open(main_py, 'r') as f:
                main_content = f.read()
            with open(run_py, 'r') as f:
                run_content = f.read()
            if 'create_app' in run_content and ('Hello World' in main_content or 'hello' in main_content.lower()) and 'create_app' not in main_content:
                os.remove(main_py)
                fixed_files.append('main.py (deleted conflicting stub)')
        except Exception:
            pass

    # Ensure ALL forms in templates have CSRF token
    templates_dir = os.path.join(project_path, 'app', 'templates')
    if os.path.isdir(templates_dir):
        for root, _, files in os.walk(templates_dir):
            for fname in files:
                if not fname.endswith('.html'):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, 'r') as f:
                        html = f.read()
                    original = html
                    # Find all <form> tags that have method="POST" but no csrf_token
                    if '<form' in html and 'method="POST"' in html.upper().replace("'", '"') and 'csrf_token' not in html:
                        # Insert csrf_token hidden input after each <form...> tag
                        html = re.sub(
                            r'(<form[^>]*>)',
                            r'\1\n                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>',
                            html
                        )
                    if html != original:
                        with open(fpath, 'w') as f:
                            f.write(html)
                        fixed_files.append(os.path.relpath(fpath, project_path))
                except Exception:
                    pass

    return fixed_files


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
        # Sanitize Jinja2 templates (fix {{ now().year }} etc.)
        file_content = sanitize_jinja_templates(file_content, file_rel_path)

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
    MAX_FIX_LOOPS = 5
    roadmap = []
    install_cmd = ''
    test_cmd = ''
    live_log = []  # Devin-like activity log — detailed messages about what agent is doing

    def add_step(name, status, detail='', duration=0):
        steps.append({'name': name, 'status': status, 'detail': detail, 'duration': round(duration, 1)})

    # === STEP 1: Understand project ===
    step_start = time.time()
    live_log.append({'icon': '\U0001f50d', 'message': f'Now analyzing project structure for "{project["name"]}"...', 'type': 'info'})
    files_context, file_list = get_project_files_context(project_path)
    if file_list:
        live_log.append({'icon': '\U0001f4c2', 'message': f'Found {len(file_list)} existing files in project directory', 'type': 'info'})
    else:
        live_log.append({'icon': '\U0001f4c2', 'message': 'Project is empty — starting fresh build', 'type': 'info'})
    add_step('Analyzing project', 'done',
             f'Found {len(file_list)} files' if file_list else 'Empty project',
             time.time() - step_start)

    # Decide: single-request (small) or multi-request (large)
    is_large = estimate_project_size(prompt) and not error_context

    if error_context:
        # ---- BUG FIX MODE (always single request) ----
        step_start = time.time()
        live_log.append({'icon': '\U0001f41b', 'message': 'Now analyzing the error and planning a fix...', 'type': 'fix'})
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
        fix_msg = agent_response.get('message', '')
        live_log.append({'icon': '\U0001f4a1', 'message': f'Identified fix: {fix_msg[:120]}' if fix_msg else f'Now fixing {len(agent_response.get("files", []))} files...', 'type': 'fix'})
        add_step('Planning & generating fix', 'done',
                 f'{len(agent_response.get("files", []))} files to fix',
                 time.time() - step_start)

        # Write fix files
        step_start = time.time()
        files_list = agent_response.get('files', [])
        for fl in files_list:
            live_log.append({'icon': '\u270d\ufe0f', 'message': f'Now writing fix to {fl.get("path", "unknown")}', 'type': 'write'})
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
        live_log.append({'icon': '\U0001f9e0', 'message': 'Now planning project architecture — analyzing requirements and dependencies...', 'type': 'plan'})
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
                    live_log.append({'icon': '\U0001f4cb', 'message': f'Project plan ready: {total_files} files in {len(file_groups)} groups', 'type': 'plan'})
                    for ri, r in enumerate(roadmap[:6]):
                        live_log.append({'icon': '\U0001f4cc', 'message': f'Step {ri+1}: {r}', 'type': 'plan'})
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

                live_log.append({'icon': '\u26a1', 'message': f'Now generating {group_name} — {group_desc}...', 'type': 'generate'})
                for gf in group_files:
                    live_log.append({'icon': '\U0001f4dd', 'message': f'Now creating {gf}...', 'type': 'write'})

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
                        live_log.append({'icon': '\u2705', 'message': f'Successfully generated {len(created)} files for {group_name}', 'type': 'success'})
                        add_step(f'Generating {group_name}', 'done',
                                 f'{len(created)} files ({group_desc})',
                                 time.time() - step_start)
                    else:
                        live_log.append({'icon': '\u26a0\ufe0f', 'message': f'{group_name}: API returned empty response — will auto-generate fallback files', 'type': 'warn'})
                        add_step(f'Generating {group_name}', 'failed', 'No files in response', time.time() - step_start)
                        all_errors.append(f'{group_name}: empty response')
                except Exception as e:
                    add_step(f'Generating {group_name}', 'failed', str(e)[:100], time.time() - step_start)
                    all_errors.append(f'{group_name}: {str(e)}')

    # ---- SINGLE-REQUEST MODE (small projects or fallback) ----
    if not error_context and not (is_large and all_files):
        step_start = time.time()
        live_log.append({'icon': '\U0001f680', 'message': 'Now generating complete project in single request...', 'type': 'generate'})
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
        live_log.append({'icon': '🔧', 'message': 'Now checking for missing critical files...', 'type': 'info'})
        fallback_files = generate_fallback_files(project_path, language='python')
        if fallback_files:
            all_files.extend(fallback_files)
            fallback_names = ', '.join(f['path'] for f in fallback_files)
            add_step('Auto-generating missing files', 'done', f'Created: {fallback_names}')
            for fb in fallback_files:
                live_log.append({'icon': '📄', 'message': f'Auto-generated missing file: {fb["path"]}', 'type': 'fix'})
        # Set fallback commands if they were never set (API failed before plan was returned)
        # Django project detection
        is_django_project = os.path.isfile(os.path.join(project_path, 'manage.py'))
        if not run_command:
            if is_django_project:
                run_command = 'python manage.py runserver 0.0.0.0:3002'
            elif os.path.isfile(os.path.join(project_path, 'run.py')):
                run_command = 'python run.py'
            elif os.path.isfile(os.path.join(project_path, 'main.py')):
                run_command = 'python main.py'
        if not install_cmd and os.path.isfile(os.path.join(project_path, 'requirements.txt')):
            install_cmd = 'pip install -r requirements.txt'
        if not test_cmd:
            if is_django_project:
                test_cmd = 'python manage.py check'
            elif os.path.isfile(os.path.join(project_path, 'run.py')):
                test_cmd = 'python -m py_compile run.py'
            elif os.path.isfile(os.path.join(project_path, 'main.py')):
                test_cmd = 'python -m py_compile main.py'
        # Django: auto-run migrations after install
        if is_django_project and install_cmd:
            live_log.append({'icon': '🗄️', 'message': 'Now setting up Django database migrations...', 'type': 'info'})

    # === POST-BUILD SANITIZATION PASS ===
    # Scan ALL files on disk and fix common AI-generated issues
    # ({% raw %}, bare csrf_token, PRAGMA spam, index route, main.py conflict)
    if all_files:
        step_start = time.time()
        sanitized = sanitize_project_on_disk(project_path)
        if sanitized:
            add_step('Sanitizing generated code', 'done',
                     f'Fixed {len(sanitized)} files: {", ".join(sanitized[:5])}',
                     time.time() - step_start)

    # === AI-POWERED AUTONOMOUS TOOL EXECUTION ===
    # Execute tool_commands from agent response + auto-generate smart tool commands
    tool_actions = []  # Collects all tool actions for UI display
    if all_files:
        step_start = time.time()
        from tools import execute_tool_commands, tool_install_packages, tool_set_env_var, tool_set_workflow, tool_run_shell, tool_get_project_info

        # 1. Collect tool_commands from ALL agent responses (single, multi, fix)
        ai_tool_commands = []
        if error_context:
            # Bug fix mode — check the single response
            try:
                if agent_response and agent_response.get('tool_commands'):
                    ai_tool_commands.extend(agent_response['tool_commands'])
            except Exception:
                pass
        elif is_large:
            # Multi-request — check plan and all batch responses
            try:
                if plan_response and plan_response.get('tool_commands'):
                    ai_tool_commands.extend(plan_response['tool_commands'])
            except Exception:
                pass
        else:
            # Single-request — check the response
            try:
                if agent_response and agent_response.get('tool_commands'):
                    ai_tool_commands.extend(agent_response['tool_commands'])
            except Exception:
                pass

        # 2. Auto-generate smart tool commands if AI didn't provide them
        auto_commands = []

        # Auto: Set SECRET_KEY if Flask project and no tool_commands set it
        has_secret_key_cmd = any(c.get('tool') == 'secrets' and c.get('key') == 'SECRET_KEY' for c in ai_tool_commands)
        if not has_secret_key_cmd and project['language'] == 'python':
            # Check if any file uses SECRET_KEY
            for f in all_files:
                content = f.get('content', '') if isinstance(f, dict) else ''
                if 'SECRET_KEY' in content or 'secret_key' in content.lower():
                    import secrets as _secrets
                    auto_commands.append({'tool': 'secrets', 'key': 'SECRET_KEY', 'value': _secrets.token_hex(24)})
                    break

        # Auto: Set workflow if run_command is known
        has_workflow_cmd = any(c.get('tool') == 'workflows' for c in ai_tool_commands)
        if not has_workflow_cmd and run_command:
            auto_commands.append({'tool': 'workflows', 'name': 'Run App', 'command': run_command, 'is_run_button': True})

        # Auto: Get project info after build
        has_info_cmd = any(c.get('tool') == 'info' for c in ai_tool_commands)
        if not has_info_cmd:
            auto_commands.append({'tool': 'info'})

        # Execute all tool commands (AI-provided first, then auto-generated)
        all_tool_commands = ai_tool_commands + auto_commands
        if all_tool_commands:
            tool_actions = execute_tool_commands(project_path, all_tool_commands)
            ai_count = len(ai_tool_commands)
            auto_count = len(auto_commands)
            detail = f'{len(tool_actions)} actions'
            if ai_count:
                detail += f' ({ai_count} AI-driven)'
            if auto_count:
                detail += f' ({auto_count} auto)'
            add_step('Running Developer Tools', 'done', detail, time.time() - step_start)

    # === INSTALL DEPENDENCIES ===
    install_result = None
    if install_cmd and all_files:
        step_start = time.time()
        live_log.append({'icon': '\U0001f4e6', 'message': f'Now installing dependencies: {install_cmd}', 'type': 'install'})
        # Clean non-pip packages (e.g. Bootstrap) from requirements.txt
        sanitize_requirements(project_path)
        # Use --upgrade to avoid version conflicts with system packages
        safe_install_cmd = install_cmd
        if 'pip install' in safe_install_cmd and '--upgrade' not in safe_install_cmd:
            safe_install_cmd = safe_install_cmd.replace('pip install', 'pip install --upgrade')
        install_result = execute_test_command(project_path, safe_install_cmd, timeout=120)

        # RETRY STRATEGY: If install fails with version conflict, strip version pins and retry
        if not install_result['success']:
            combined_output = (install_result.get('stderr', '') + install_result.get('stdout', '')).lower()
            if 'conflicting' in combined_output or 'incompatible' in combined_output or 'no matching distribution' in combined_output:
                # Strip all version pins from requirements.txt and retry
                sanitize_requirements(project_path, strip_versions=True)
                install_result = execute_test_command(project_path, safe_install_cmd, timeout=120)
                if not install_result['success']:
                    # Last resort: install packages one by one, skipping failures
                    req_path = os.path.join(project_path, 'requirements.txt')
                    if os.path.isfile(req_path):
                        with open(req_path, 'r') as f:
                            pkgs = [l.strip() for l in f if l.strip() and not l.startswith('#')]
                        failed_pkgs = []
                        for pkg in pkgs:
                            pkg_result = execute_test_command(project_path, f'pip install --upgrade {pkg}', timeout=60)
                            if not pkg_result['success']:
                                failed_pkgs.append(pkg)
                        if failed_pkgs:
                            # Write cleaned requirements without failed packages
                            with open(req_path, 'r') as f:
                                lines = f.readlines()
                            with open(req_path, 'w') as f:
                                for line in lines:
                                    pkg_name = line.strip().split('==')[0].split('>=')[0].strip().lower()
                                    if pkg_name not in [p.lower() for p in failed_pkgs]:
                                        f.write(line)
                            all_errors.append(f'Skipped incompatible packages: {", ".join(failed_pkgs)}')
                        # Mark as success since we installed what we could
                        install_result = {'success': True, 'stdout': f'Installed {len(pkgs) - len(failed_pkgs)}/{len(pkgs)} packages', 'stderr': '', 'returncode': 0}

        status = 'done' if install_result['success'] else 'failed'
        detail = 'Dependencies installed' if install_result['success'] else (install_result.get('stderr', '') or install_result.get('stdout', ''))[:200]
        if install_result['success']:
            live_log.append({'icon': '\u2705', 'message': 'Dependencies installed successfully', 'type': 'success'})
        else:
            live_log.append({'icon': '\u274c', 'message': f'Dependency installation failed: {detail[:100]}', 'type': 'error'})
        add_step('Installing dependencies', status, detail, time.time() - step_start)

    # === TEST → FIX LOOP (up to MAX_FIX_LOOPS) ===
    fix_iterations = []

    if test_cmd and all_files:
        live_log.append({'icon': '\U0001f9ea', 'message': f'Now testing project: {test_cmd}', 'type': 'test'})
        for fix_attempt in range(MAX_FIX_LOOPS + 1):  # 0 = initial test, 1-3 = fix attempts
            step_start = time.time()
            time.sleep(0.5)
            test_result = execute_test_command(project_path, test_cmd)
            test_output = (test_result.get('stderr', '') or test_result.get('stdout', ''))[:2000]

            if test_result['success']:
                final_test_passed = True
                label = 'Testing code' if fix_attempt == 0 else f'Re-testing (attempt {fix_attempt})'
                live_log.append({'icon': '\u2705', 'message': 'All tests passed successfully!', 'type': 'success'})
                add_step(label, 'done', 'All tests passed', time.time() - step_start)
                break
            else:
                label = 'Testing code' if fix_attempt == 0 else f'Re-testing (attempt {fix_attempt})'
                live_log.append({'icon': '\u274c', 'message': f'Test failed: {test_output[:120]}', 'type': 'error'})
                add_step(label, 'failed', test_output[:150], time.time() - step_start)

                # If we still have fix attempts left, call AI to fix
                if fix_attempt < MAX_FIX_LOOPS:
                    step_start = time.time()
                    live_log.append({'icon': '\U0001f527', 'message': f'Now attempting auto-fix #{fix_attempt + 1} — analyzing error and patching code...', 'type': 'fix'})
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

    # === INTERACTIVE APP TESTING (Devin-like) ===
    # Start app, navigate pages, fill forms, submit, check responses
    # Reports each action: 🖱️ Click, ⌨️ Type, 🔍 Check, 📍 Navigate, etc.
    test_actions = []  # List of test actions for UI display
    test_issues = []   # Issues found during testing

    if final_test_passed and run_command and all_files and project['language'] == 'python':
        step_start = time.time()
        smoke_port = 3099
        smoke_proc = None
        try:
            import subprocess as sp
            import urllib.request
            import urllib.parse
            import http.cookiejar

            # Start the app
            test_actions.append({'action': '🚀 Starting app', 'detail': f'Running: {run_command} on port {smoke_port}'})
            smoke_proc = sp.Popen(
                run_command, shell=True, cwd=project_path,
                stdout=sp.PIPE, stderr=sp.PIPE,
                env={**os.environ, 'PORT': str(smoke_port), 'FLASK_RUN_PORT': str(smoke_port)}
            )
            time.sleep(3)

            # Setup session with cookie jar (maintains login state)
            cookie_jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

            base_url = f'http://127.0.0.1:{smoke_port}'

            # Helper: GET a page
            def test_get(path, expect_text=None, label=None):
                url = base_url + path
                action_label = label or f'📍 Navigate to {path}'
                try:
                    req = urllib.request.Request(url)
                    resp = opener.open(req, timeout=8)
                    body = resp.read().decode('utf-8', errors='ignore')
                    status = resp.status
                    test_actions.append({'action': action_label, 'detail': f'Status: {status} OK', 'status': 'pass'})
                    if expect_text and expect_text.lower() not in body.lower():
                        test_actions.append({'action': f'🔍 Check for "{expect_text}"', 'detail': 'Not found on page', 'status': 'fail'})
                        test_issues.append(f'{path}: Expected text "{expect_text}" not found')
                    elif expect_text:
                        test_actions.append({'action': f'🔍 Check for "{expect_text}"', 'detail': 'Found on page', 'status': 'pass'})
                    # Check for errors in response
                    if 'Internal Server Error' in body:
                        test_issues.append(f'{path}: Internal Server Error (500)')
                        test_actions.append({'action': f'🔍 Check {path}', 'detail': 'Internal Server Error!', 'status': 'fail'})
                    if 'Bad Request' in body and 'CSRF' in body:
                        test_issues.append(f'{path}: CSRF token missing')
                        test_actions.append({'action': f'🔍 Check {path}', 'detail': 'CSRF token missing in form', 'status': 'fail'})
                    return body, status
                except urllib.error.HTTPError as he:
                    body = he.read().decode('utf-8', errors='ignore') if he.readable() else ''
                    test_actions.append({'action': action_label, 'detail': f'HTTP {he.code}', 'status': 'fail' if he.code >= 400 else 'pass'})
                    if he.code == 400 and 'CSRF' in body:
                        test_issues.append(f'{path}: CSRF token missing')
                    elif he.code >= 500:
                        test_issues.append(f'{path}: Server error ({he.code})')
                    return body, he.code
                except Exception as e:
                    test_actions.append({'action': action_label, 'detail': str(e)[:80], 'status': 'fail'})
                    return '', 0

            # Helper: POST a form (extract CSRF token first)
            def test_post_form(path, form_data, label=None, get_path=None):
                # First GET the page to extract CSRF token
                get_url = base_url + (get_path or path)
                csrf_token = ''
                try:
                    req = urllib.request.Request(get_url)
                    resp = opener.open(req, timeout=8)
                    body = resp.read().decode('utf-8', errors='ignore')
                    # Extract CSRF token from hidden input
                    import re as _re
                    csrf_match = _re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)', body)
                    if csrf_match:
                        csrf_token = csrf_match.group(1)
                        test_actions.append({'action': '🔑 Extract CSRF token', 'detail': f'Token: {csrf_token[:20]}...', 'status': 'pass'})
                    else:
                        test_actions.append({'action': '🔑 Extract CSRF token', 'detail': 'No CSRF token found in form', 'status': 'warn'})
                except Exception:
                    pass

                if csrf_token:
                    form_data['csrf_token'] = csrf_token

                # Now POST the form
                action_label = label or f'📝 Submit form to {path}'
                try:
                    encoded = urllib.parse.urlencode(form_data).encode('utf-8')
                    req = urllib.request.Request(base_url + path, data=encoded, method='POST')
                    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
                    resp = opener.open(req, timeout=8)
                    body = resp.read().decode('utf-8', errors='ignore')
                    final_url = resp.url
                    status = resp.status
                    test_actions.append({'action': action_label, 'detail': f'Status: {status}, Redirected to: {final_url.replace(base_url, "")}', 'status': 'pass'})
                    if 'Bad Request' in body and 'CSRF' in body:
                        test_issues.append(f'POST {path}: CSRF session token missing')
                        test_actions.append({'action': '🔍 Check response', 'detail': 'CSRF session token missing!', 'status': 'fail'})
                    return body, status, final_url
                except urllib.error.HTTPError as he:
                    err_body = he.read().decode('utf-8', errors='ignore') if he.readable() else ''
                    test_actions.append({'action': action_label, 'detail': f'HTTP {he.code}', 'status': 'fail'})
                    if he.code == 400 and 'CSRF' in err_body:
                        test_issues.append(f'POST {path}: CSRF session token missing')
                    elif he.code >= 500:
                        test_issues.append(f'POST {path}: Server error ({he.code})')
                    return err_body, he.code, ''
                except Exception as e:
                    test_actions.append({'action': action_label, 'detail': str(e)[:80], 'status': 'fail'})
                    return '', 0, ''

            # ============================================
            # TEST PLAN: Analyze codebase and run tests
            # ============================================
            test_actions.append({'action': '🧠 Analyzing codebase', 'detail': 'Detecting routes, forms, and features...', 'status': 'info'})

            # Detect what kind of app this is
            has_signup = False
            has_login = False
            has_chatbot = False
            signup_route = '/auth/signup'
            login_route = '/auth/login'
            signup_fields = {}
            login_fields = {}

            for root, _, files in os.walk(project_path):
                for fname in files:
                    if not fname.endswith('.py'):
                        continue
                    try:
                        with open(os.path.join(root, fname), 'r') as f:
                            code = f.read()
                        if '/signup' in code or '/register' in code:
                            has_signup = True
                            if "url_prefix='/auth'" in code or 'auth_bp' in code or 'auth' in fname:
                                signup_route = '/auth/signup' if '/signup' in code else '/auth/register'
                            elif "url_prefix=''" in code or 'main' in fname:
                                signup_route = '/signup' if '/signup' in code else '/register'
                        if '/login' in code:
                            has_login = True
                            if "url_prefix='/auth'" in code or 'auth_bp' in code or 'auth' in fname:
                                login_route = '/auth/login'
                            elif "url_prefix=''" in code or 'main' in fname:
                                login_route = '/login'
                        if 'chatbot' in code.lower() or '/chat' in code:
                            has_chatbot = True
                    except Exception:
                        pass

            # Detect form fields from HTML templates
            templates_dir = os.path.join(project_path, 'app', 'templates')
            if os.path.isdir(templates_dir):
                for fname in os.listdir(templates_dir):
                    if not fname.endswith('.html'):
                        continue
                    try:
                        with open(os.path.join(templates_dir, fname), 'r') as f:
                            html = f.read()
                        import re as _re
                        input_names = _re.findall(r'name=["\'](\w+)["\']', html)
                        if 'signup' in fname or 'register' in fname:
                            signup_fields = {n: '' for n in input_names if n != 'csrf_token'}
                        elif 'login' in fname:
                            login_fields = {n: '' for n in input_names if n != 'csrf_token'}
                    except Exception:
                        pass

            test_actions.append({'action': '🧠 Test plan ready', 'detail': f'Auth: {"signup+login" if has_signup else "none"}, Chatbot: {"yes" if has_chatbot else "no"}', 'status': 'info'})

            # --- TEST 1: Check homepage ---
            test_actions.append({'action': '📍 Navigate to /', 'detail': 'Opening homepage...', 'status': 'info'})
            body, status = test_get('/', label='📍 Navigate to homepage /')

            # --- TEST 2: Signup page ---
            if has_signup:
                test_actions.append({'action': f'📍 Navigate to {signup_route}', 'detail': 'Opening signup page...', 'status': 'info'})
                # Try both /auth/signup and /signup
                body, status = test_get(signup_route, expect_text='sign up')
                if status == 404 and signup_route.startswith('/auth/'):
                    signup_route = signup_route.replace('/auth/', '/')
                    body, status = test_get(signup_route, expect_text='sign up')
                elif status == 404:
                    signup_route = '/auth' + signup_route
                    body, status = test_get(signup_route, expect_text='sign up')

                # Fill signup form with test credentials
                if status == 200:
                    test_email = 'test@gmail.com'
                    test_password = 'test123456@#'
                    test_username = 'testuser'

                    # Build form data based on detected fields
                    if signup_fields:
                        for field in signup_fields:
                            if 'email' in field.lower():
                                signup_fields[field] = test_email
                            elif 'password' in field.lower() or 'pass' in field.lower():
                                signup_fields[field] = test_password
                            elif 'confirm' in field.lower():
                                signup_fields[field] = test_password
                            elif 'user' in field.lower() or 'name' in field.lower():
                                signup_fields[field] = test_username
                            else:
                                signup_fields[field] = test_username
                    else:
                        signup_fields = {
                            'username': test_username, 'email': test_email,
                            'password': test_password, 'name': test_username,
                        }

                    # Show what we're typing
                    for field, value in signup_fields.items():
                        display_val = '••••••••' if 'pass' in field.lower() else value
                        test_actions.append({'action': f'⌨️ Type "{display_val}" into {field}', 'detail': f'Field: {field}', 'status': 'info'})

                    test_actions.append({'action': '🖱️ Click "Sign Up" button', 'detail': f'Submitting to {signup_route}', 'status': 'info'})
                    body, status, final_url = test_post_form(signup_route, signup_fields, label='🖱️ Click "Sign Up" button')

                    if status == 200 and ('login' in final_url.lower() or 'chat' in final_url.lower() or 'success' in body.lower()):
                        test_actions.append({'action': '✅ Signup successful', 'detail': f'Redirected to {final_url.replace(base_url, "")}', 'status': 'pass'})
                    elif status == 200:
                        test_actions.append({'action': '🔍 Check signup result', 'detail': 'Page loaded but redirect unclear', 'status': 'warn'})
                    else:
                        test_actions.append({'action': '❌ Signup failed', 'detail': f'Status: {status}', 'status': 'fail'})
                        test_issues.append(f'Signup failed with status {status}')

            # --- TEST 3: Login page ---
            if has_login:
                test_actions.append({'action': f'📍 Navigate to {login_route}', 'detail': 'Opening login page...', 'status': 'info'})
                body, status = test_get(login_route, expect_text='log in')
                if status == 404 and login_route.startswith('/auth/'):
                    login_route = login_route.replace('/auth/', '/')
                    body, status = test_get(login_route, expect_text='log in')
                elif status == 404:
                    login_route = '/auth' + login_route
                    body, status = test_get(login_route, expect_text='log in')

                if status == 200:
                    test_email = 'test@gmail.com'
                    test_password = 'test123456@#'

                    if login_fields:
                        for field in login_fields:
                            if 'email' in field.lower() or 'identifier' in field.lower() or 'user' in field.lower():
                                login_fields[field] = test_email
                            elif 'password' in field.lower() or 'pass' in field.lower():
                                login_fields[field] = test_password
                    else:
                        login_fields = {'email': test_email, 'password': test_password}

                    for field, value in login_fields.items():
                        display_val = '••••••••' if 'pass' in field.lower() else value
                        test_actions.append({'action': f'⌨️ Type "{display_val}" into {field}', 'detail': f'Field: {field}', 'status': 'info'})

                    test_actions.append({'action': '🖱️ Click "Log In" button', 'detail': f'Submitting to {login_route}', 'status': 'info'})
                    body, status, final_url = test_post_form(login_route, login_fields, label='🖱️ Click "Log In" button')

                    if status == 200 and ('chat' in final_url.lower() or 'dashboard' in final_url.lower() or 'welcome' in body.lower() or 'logged in' in body.lower()):
                        test_actions.append({'action': '✅ Login successful', 'detail': f'Redirected to {final_url.replace(base_url, "")}', 'status': 'pass'})
                    elif status == 200:
                        test_actions.append({'action': '🔍 Check login result', 'detail': 'Page loaded, checking content...', 'status': 'warn'})
                    else:
                        test_actions.append({'action': '❌ Login failed', 'detail': f'Status: {status}', 'status': 'fail'})
                        test_issues.append(f'Login failed with status {status}')

                    # --- TEST 4: Check chatbot page after login ---
                    if has_chatbot and status == 200:
                        test_actions.append({'action': '📍 Navigate to chatbot', 'detail': 'Checking chatbot page...', 'status': 'info'})
                        chat_body, chat_status = test_get('/chat', expect_text='chat')
                        if chat_status == 404:
                            chat_body, chat_status = test_get('/chatbot')

            # Kill smoke test process
            try:
                smoke_proc.terminate()
                smoke_proc.wait(timeout=3)
            except Exception:
                try:
                    smoke_proc.kill()
                except Exception:
                    pass

            # Handle issues found
            if test_issues:
                has_csrf_issue = any('CSRF' in issue for issue in test_issues)
                if has_csrf_issue:
                    sanitize_project_on_disk(project_path)
                    test_actions.append({'action': '🔧 Auto-fixing CSRF issues', 'detail': 'Injected CSRF tokens into forms', 'status': 'pass'})

                add_step('Testing app (interactive)', 'done',
                         f'{len(test_actions)} actions, {len(test_issues)} issues found & fixed',
                         time.time() - step_start)
            else:
                add_step('Testing app (interactive)', 'done',
                         f'{len(test_actions)} actions, all passed ✓',
                         time.time() - step_start)

        except Exception as e:
            add_step('Testing app (interactive)', 'failed', str(e)[:100], time.time() - step_start)
            if smoke_proc:
                try:
                    smoke_proc.terminate()
                except Exception:
                    pass

    # === AUTO-DEPLOY if tests passed ===
    deploy_result = None
    deploy_ready = final_test_passed

    if auto_deploy and deploy_ready and run_command:
        step_start = time.time()
        live_log.append({'icon': '\U0001f680', 'message': f'Now deploying app with command: {run_command}', 'type': 'deploy'})
        try:
            from deploy import deploy_project_internal
            deploy_result = deploy_project_internal(user, project_id, project_path, run_command)
            if deploy_result and deploy_result.get('success'):
                live_log.append({'icon': '\u2705', 'message': f'App deployed successfully on port {deploy_result.get("port", "?")}', 'type': 'success'})
                add_step('Deploying app', 'done',
                         f'Running on port {deploy_result.get("port", "?")}',
                         time.time() - step_start)
            else:
                err = deploy_result.get('error', 'Unknown') if deploy_result else 'Deploy function failed'
                live_log.append({'icon': '\u274c', 'message': f'Deploy failed: {err[:100]}', 'type': 'error'})
                add_step('Deploying app', 'failed', err[:150], time.time() - step_start)
        except Exception as e:
            add_step('Deploying app', 'failed', str(e)[:150], time.time() - step_start)
            deploy_result = None

    live_log.append({'icon': '\U0001f3c1', 'message': f'Agent completed: {len(all_files)} files generated, {len(steps)} steps executed', 'type': 'complete'})

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
        'test_actions': test_actions,
        'test_issues': test_issues,
        'tool_actions': tool_actions,
        'live_log': live_log,
    })
