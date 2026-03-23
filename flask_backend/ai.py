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


def call_yubiai(message, system_prompt=None, model="gpt-oss-120b", temperature=0.7, max_tokens=4096):
    """Call YubiAI API."""
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

    try:
        resp = requests.post(
            YUBIAI_API_URL,
            headers={
                "Authorization": f"Bearer {YUBIAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120,
        )
        if resp.status_code == 200:
            return resp.json()
        error_text = resp.text
        if 'ngrok' in error_text.lower() or 'offline' in error_text.lower():
            return {"error": "YubiAI API endpoint is offline. The ngrok tunnel may have disconnected. Please restart the YubiAI server."}
        if resp.status_code == 404:
            return {"error": "YubiAI API endpoint not found (404). The server may be offline or the URL may be incorrect."}
        if resp.status_code == 401:
            return {"error": "YubiAI API authentication failed. Check your API key."}
        if resp.status_code == 429:
            return {"error": "YubiAI API rate limit exceeded. Please wait and try again."}
        return {"error": f"YubiAI API error (HTTP {resp.status_code}). The server may be temporarily unavailable."}
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot connect to YubiAI API. The server appears to be offline. Check if the ngrok tunnel is running."}
    except requests.exceptions.Timeout:
        return {"error": "YubiAI API request timed out (120s). The server may be overloaded."}
    except Exception as e:
        return {"error": f"YubiAI API error: {str(e)}"}


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
AGENT_SYSTEM_PROMPT = """You are YubiAI, a powerful autonomous AI software engineer inside YubiLab Cloud IDE — similar to Devin AI. You think step by step, plan before coding, write production-quality code, and iterate until the project works perfectly.

## YOUR CAPABILITIES
- Create, modify, and delete project files
- Create entire projects from scratch with proper structure
- Debug and fix errors by analyzing error output
- Incrementally update code (only change what's needed)
- Generate run commands and test commands

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
- ALWAYS include a roadmap showing your step-by-step plan
- Think about the project structure BEFORE writing code
- Consider dependencies, imports, and file relationships

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
- Explain what the bug was and how you fixed it in the message"""


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

    if not prompt:
        return jsonify({'error': 'Prompt is required'}), 400

    system_prompts = {
        'generate': f"You are YubiAI, an expert coding assistant built into YubiLab IDE. Generate clean, well-commented {language} code based on the user's request. Return ONLY the code without markdown code blocks unless the user asks for explanation.",
        'debug': f"You are YubiAI, a debugging expert in YubiLab IDE. Analyze the following {language} code and identify bugs, then provide the fixed version. Explain what was wrong briefly.",
        'explain': f"You are YubiAI, a code explanation assistant in YubiLab IDE. Explain the following {language} code in a clear, concise manner.",
        'complete': f"You are YubiAI, an autocomplete assistant in YubiLab IDE. Complete the following {language} code naturally. Return ONLY the completed code.",
    }

    system_prompt = system_prompts.get(action, system_prompts['generate'])

    if code_context:
        full_prompt = f"Code context:\n```{language}\n{code_context}\n```\n\nUser request: {prompt}"
    else:
        full_prompt = prompt

    result = call_yubiai(full_prompt, system_prompt=system_prompt)

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
    """YubiAI Autonomous Agent — powerful multi-step agent that plans, builds, tests, and fixes."""
    data = request.get_json()
    prompt = data.get('prompt', '')
    project_id = data.get('project_id')
    error_context = data.get('error_context', '')  # Error from previous test run
    phase = data.get('phase', 'auto')  # auto, fix, update

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

    # Get current project files for context
    files_context, file_list = get_project_files_context(project_path)

    # Build the user prompt with full context
    if error_context:
        # Bug fix mode — provide error details
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

    result = call_yubiai(full_prompt, system_prompt=AGENT_SYSTEM_PROMPT, max_tokens=8192)

    if 'error' in result:
        return jsonify({'error': result['error']}), 500

    response_text = result.get('response', '')

    # Parse the AI response
    try:
        agent_response = parse_agent_json(response_text)
        if not agent_response:
            return jsonify({
                'response': response_text,
                'agent_executed': False,
                'message': 'AI returned non-structured response'
            })
    except json.JSONDecodeError:
        return jsonify({
            'response': response_text,
            'agent_executed': False,
            'message': 'Could not parse AI response as structured command'
        })

    # Apply file changes
    files_list = agent_response.get('files', [])
    created_files, errors = apply_file_changes(project_path, files_list)

    # Run install command if provided
    install_cmd = agent_response.get('install_command', '')
    install_result = None
    if install_cmd:
        install_result = execute_test_command(project_path, install_cmd, timeout=60)

    # Run test command to verify the code works
    test_cmd = agent_response.get('test_command', '')
    test_result = None
    if test_cmd and created_files:
        time.sleep(0.5)  # Brief pause for filesystem sync
        test_result = execute_test_command(project_path, test_cmd)

    # Determine if we need auto-fix
    needs_fix = False
    test_output = ''
    if test_result and not test_result['success']:
        needs_fix = True
        test_output = (test_result.get('stderr', '') or test_result.get('stdout', ''))[:2000]

    # If test failed, attempt ONE automatic fix
    fix_result = None
    if needs_fix and test_output:
        fix_prompt = f"""Project: {project['name']} (Language: {project['language']})
Project files: {', '.join(file_list + [f['path'] for f in created_files])}

Current project files:
{get_project_files_context(project_path)[0]}

TEST COMMAND FAILED: {test_cmd}
ERROR OUTPUT:
{test_output}

Fix this error. Only modify the files that have the bug. Do NOT rewrite everything."""

        fix_api_result = call_yubiai(fix_prompt, system_prompt=AGENT_SYSTEM_PROMPT, max_tokens=8192)

        if 'error' not in fix_api_result:
            try:
                fix_response = parse_agent_json(fix_api_result.get('response', ''))
                if fix_response and fix_response.get('files'):
                    fixed_files, fix_errors = apply_file_changes(project_path, fix_response.get('files', []))
                    errors.extend(fix_errors)
                    created_files.extend(fixed_files)

                    # Re-run test
                    if test_cmd:
                        time.sleep(0.5)
                        retest = execute_test_command(project_path, test_cmd)
                        fix_result = {
                            'attempted': True,
                            'fixed_files': fixed_files,
                            'test_passed': retest['success'] if retest else False,
                            'message': fix_response.get('message', ''),
                            'remaining_error': retest.get('stderr', '')[:500] if retest and not retest['success'] else '',
                        }
                    else:
                        fix_result = {
                            'attempted': True,
                            'fixed_files': fixed_files,
                            'test_passed': True,
                            'message': fix_response.get('message', ''),
                        }
            except Exception:
                fix_result = {'attempted': True, 'test_passed': False, 'message': 'Auto-fix parse failed'}

    return jsonify({
        'agent_executed': True,
        'phase': agent_response.get('phase', 'build'),
        'roadmap': agent_response.get('roadmap', []),
        'plan': agent_response.get('plan', agent_response.get('message', '')),
        'files': created_files,
        'run_command': agent_response.get('run_command', ''),
        'test_command': test_cmd,
        'install_command': install_cmd,
        'deploy_ready': agent_response.get('deploy_ready', False),
        'message': agent_response.get('message', 'Agent completed'),
        'errors': errors,
        'model': result.get('model', ''),
        'test_result': {
            'ran': test_result is not None,
            'passed': test_result['success'] if test_result else None,
            'output': test_output[:500] if test_output else '',
        } if test_result else None,
        'auto_fix': fix_result,
        'install_result': {
            'ran': True,
            'success': install_result['success'],
            'output': (install_result.get('stderr', '') or install_result.get('stdout', ''))[:500],
        } if install_result else None,
    })
