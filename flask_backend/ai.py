from flask import Blueprint, request, jsonify
from auth import login_required
from models import get_db
import requests
import os
import json
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
        # Parse error more cleanly
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


@ai_bp.route('/api/ai/agent', methods=['POST'])
@login_required
def ai_agent(user):
    """YubiAI Autonomous Agent - generates project files, executes code, deploys."""
    data = request.get_json()
    prompt = data.get('prompt', '')
    project_id = data.get('project_id')

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

    # Get current project files for context
    files_context = ""
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in files:
            rel_path = os.path.relpath(os.path.join(root, f), project_path)
            try:
                with open(os.path.join(root, f), 'r', errors='replace') as fh:
                    content = fh.read()
                if len(content) < 5000:
                    files_context += f"\n--- {rel_path} ---\n{content}\n"
            except Exception:
                pass

    system_prompt = """You are YubiAI Autonomous Agent inside YubiLab IDE. You can create, modify, and organize project files.

IMPORTANT: Respond ONLY with a valid JSON object (no markdown, no explanation outside JSON). The JSON must have this structure:
{
  "plan": "Brief description of what you will do",
  "files": [
    {
      "path": "relative/path/to/file.ext",
      "content": "full file content here",
      "action": "create"
    }
  ],
  "run_command": "optional command to run after creating files (e.g., python main.py)",
  "message": "Brief message to the user about what was done"
}

Actions can be: "create", "modify", "delete"
Always provide complete file contents, not partial.
Create a well-structured project with proper file organization.
IMPORTANT: If creating a Flask/web app, use port 3000 (NOT 5000) since port 5000 is used by YubiLab itself. Use app.run(port=3000) or os.environ.get('PORT', 3000)."""

    full_prompt = f"""Project: {project['name']} (Language: {project['language']})
Current project files:
{files_context if files_context else '(empty project)'}

User request: {prompt}"""

    result = call_yubiai(full_prompt, system_prompt=system_prompt, max_tokens=8192)

    if 'error' in result:
        return jsonify({'error': result['error']}), 500

    response_text = result.get('response', '')

    # Parse the AI response as JSON
    try:
        # Try to extract JSON from response
        json_start = response_text.find('{')
        json_end = response_text.rfind('}') + 1
        if json_start >= 0 and json_end > json_start:
            agent_response = json.loads(response_text[json_start:json_end])
        else:
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

    # Execute the agent's plan
    created_files = []
    errors = []

    for file_info in agent_response.get('files', []):
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

    return jsonify({
        'agent_executed': True,
        'plan': agent_response.get('plan', ''),
        'files': created_files,
        'run_command': agent_response.get('run_command', ''),
        'message': agent_response.get('message', 'Agent completed'),
        'errors': errors,
        'model': result.get('model', ''),
    })
