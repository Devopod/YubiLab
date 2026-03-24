from flask import Blueprint, request, jsonify
from auth import login_required
from models import get_db
import requests
import os
import json
import subprocess
import time
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
- Follow best practices for each language/framework
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


def apply_file_changes(project_path, files_list):
    """Apply file changes from agent response to disk."""
    created_files = []
    errors = []

    for file_info in files_list:
        file_rel_path = file_info.get('path', '')
        file_content = file_info.get('content', '')
        action = file_info.get('action', 'create')

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


@ai_bp.route('/api/ai/agent', methods=['POST'])
@login_required
def ai_agent(user):
    """YubiAI Autonomous Agent — fully autonomous multi-loop agent.
    Builds → Installs → Tests → Fixes (up to 3 loops) → Deploys → Verifies.
    Returns all steps and results in a single response."""
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

    def add_step(name, status, detail='', duration=0):
        steps.append({'name': name, 'status': status, 'detail': detail, 'duration': round(duration, 1)})

    # === STEP 1: Understand project ===
    step_start = time.time()
    files_context, file_list = get_project_files_context(project_path)
    add_step('Analyzing project', 'done',
             f'Found {len(file_list)} files' if file_list else 'Empty project',
             time.time() - step_start)

    # === STEP 2: Call AI to plan & build ===
    step_start = time.time()
    if error_context:
        full_prompt = f"""Project: {project['name']} (Language: {project['language']})
Project directory: {', '.join(file_list) if file_list else '(empty)'}

Current project files:
{files_context if files_context else '(empty project)'}

PREVIOUS ERROR OUTPUT:
{error_context}

User request: Fix the error above. {prompt}

IMPORTANT: Only modify files that need fixing. Do NOT regenerate files that are working correctly."""
    else:
        full_prompt = f"""Project: {project['name']} (Language: {project['language']})
Project directory: {', '.join(file_list) if file_list else '(empty)'}

Current project files:
{files_context if files_context else '(empty project)'}

User request: {prompt}"""

    result = call_yubiai(full_prompt, system_prompt=AGENT_SYSTEM_PROMPT, max_tokens=32768)

    if 'error' in result:
        add_step('Calling YubiAI', 'failed', result['error'], time.time() - step_start)
        return jsonify({'error': result['error'], 'steps': steps}), 500

    response_text = result.get('response', '')
    try:
        agent_response = parse_agent_json(response_text)
        if not agent_response:
            add_step('Calling YubiAI', 'failed', 'Non-structured response', time.time() - step_start)
            return jsonify({
                'response': response_text,
                'agent_executed': False,
                'steps': steps,
                'message': 'AI returned non-structured response'
            })
    except json.JSONDecodeError:
        add_step('Calling YubiAI', 'failed', 'JSON parse error', time.time() - step_start)
        return jsonify({
            'response': response_text,
            'agent_executed': False,
            'steps': steps,
            'message': 'Could not parse AI response'
        })

    roadmap = agent_response.get('roadmap', [])
    run_command = agent_response.get('run_command', '')
    add_step('Planning & generating code', 'done',
             f'{len(roadmap)} steps planned, {len(agent_response.get("files", []))} files',
             time.time() - step_start)

    # === STEP 3: Write files to disk ===
    step_start = time.time()
    files_list = agent_response.get('files', [])
    created_files, errors = apply_file_changes(project_path, files_list)
    all_files.extend(created_files)
    all_errors.extend(errors)
    add_step('Writing files', 'done',
             f'{len(created_files)} files written' + (f', {len(errors)} errors' if errors else ''),
             time.time() - step_start)

    # === STEP 4: Install dependencies ===
    install_cmd = agent_response.get('install_command', '')
    install_result = None
    if install_cmd:
        step_start = time.time()
        install_result = execute_test_command(project_path, install_cmd, timeout=120)
        status = 'done' if install_result['success'] else 'failed'
        detail = 'Dependencies installed' if install_result['success'] else (install_result.get('stderr', '') or install_result.get('stdout', ''))[:200]
        add_step('Installing dependencies', status, detail, time.time() - step_start)

    # === STEP 5: Test → Fix loop (up to MAX_FIX_LOOPS) ===
    test_cmd = agent_response.get('test_command', '')
    fix_iterations = []

    if test_cmd and created_files:
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
        if created_files:
            add_step('Testing code', 'skipped', 'No test command provided')

    # === STEP 6: Auto-deploy if tests passed ===
    deploy_result = None
    deploy_ready = agent_response.get('deploy_ready', False) or final_test_passed

    if auto_deploy and deploy_ready and run_command:
        step_start = time.time()
        try:
            # Import deploy function
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
        'phase': agent_response.get('phase', 'build'),
        'roadmap': roadmap,
        'plan': agent_response.get('plan', agent_response.get('message', '')),
        'files': all_files,
        'run_command': run_command,
        'test_command': test_cmd,
        'install_command': install_cmd,
        'deploy_ready': deploy_ready,
        'message': agent_response.get('message', 'Agent completed'),
        'errors': all_errors,
        'model': result.get('model', ''),
        'steps': steps,
        'fix_iterations': fix_iterations,
        'tests_passed': final_test_passed,
        'deploy_result': deploy_result,
    })
