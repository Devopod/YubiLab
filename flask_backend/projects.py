from flask import Blueprint, request, jsonify
from auth import login_required
from models import get_db
import os
import shutil
from config import WORKSPACES_DIR

projects_bp = Blueprint('projects', __name__)

LANGUAGE_TEMPLATES = {
    'python': {
        'main.py': '# Welcome to YubiLab!\nprint("Hello, World!")\n',
    },
    'javascript': {
        'index.js': '// Welcome to YubiLab!\nconsole.log("Hello, World!");\n',
    },
    'html': {
        'index.html': '<!DOCTYPE html>\n<html lang="en">\n<head>\n    <meta charset="UTF-8">\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <title>My Project</title>\n    <style>\n        body { font-family: Arial, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #1a1a2e; color: #eee; }\n        h1 { font-size: 2.5rem; }\n    </style>\n</head>\n<body>\n    <h1>Hello, YubiLab!</h1>\n</body>\n</html>\n',
        'style.css': '/* Add your styles here */\n',
        'script.js': '// Add your JavaScript here\nconsole.log("YubiLab project loaded!");\n',
    },
    'c': {
        'main.c': '#include <stdio.h>\n\nint main() {\n    printf("Hello, World!\\n");\n    return 0;\n}\n',
    },
    'cpp': {
        'main.cpp': '#include <iostream>\nusing namespace std;\n\nint main() {\n    cout << "Hello, World!" << endl;\n    return 0;\n}\n',
    },
    'java': {
        'Main.java': 'public class Main {\n    public static void main(String[] args) {\n        System.out.println("Hello, World!");\n    }\n}\n',
    },
    'go': {
        'main.go': 'package main\n\nimport "fmt"\n\nfunc main() {\n    fmt.Println("Hello, World!")\n}\n',
    },
    'php': {
        'index.php': '<?php\necho "Hello, World!\\n";\n?>\n',
    },
    'rust': {
        'main.rs': 'fn main() {\n    println!("Hello, World!");\n}\n',
    },
}


def get_project_path(user_id, project_name):
    safe_name = project_name.replace('..', '').replace('/', '_').replace('\\', '_')
    return os.path.join(WORKSPACES_DIR, str(user_id), safe_name)


@projects_bp.route('/api/projects', methods=['GET'])
@login_required
def list_projects(user):
    conn = get_db()
    projects = conn.execute(
        'SELECT * FROM projects WHERE user_id = ? ORDER BY updated_at DESC',
        (user['id'],)
    ).fetchall()
    conn.close()

    return jsonify({
        'projects': [
            {
                'id': p['id'],
                'name': p['name'],
                'language': p['language'],
                'description': p['description'],
                'created_at': p['created_at'],
                'updated_at': p['updated_at'],
            }
            for p in projects
        ]
    })


@projects_bp.route('/api/projects', methods=['POST'])
@login_required
def create_project(user):
    data = request.get_json()
    name = data.get('name', '').strip()
    language = data.get('language', 'python').strip().lower()
    description = data.get('description', '').strip()

    if not name:
        return jsonify({'error': 'Project name is required'}), 400

    if len(name) > 100:
        return jsonify({'error': 'Project name too long'}), 400

    conn = get_db()
    existing = conn.execute(
        'SELECT id FROM projects WHERE user_id = ? AND name = ?',
        (user['id'], name)
    ).fetchone()

    if existing:
        conn.close()
        return jsonify({'error': 'Project with this name already exists'}), 409

    cursor = conn.execute(
        'INSERT INTO projects (user_id, name, language, description) VALUES (?, ?, ?, ?)',
        (user['id'], name, language, description)
    )
    project_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Create project directory with template files
    project_path = get_project_path(user['id'], name)
    os.makedirs(project_path, exist_ok=True)

    templates = LANGUAGE_TEMPLATES.get(language, LANGUAGE_TEMPLATES['python'])
    for filename, content in templates.items():
        filepath = os.path.join(project_path, filename)
        with open(filepath, 'w') as f:
            f.write(content)

    return jsonify({
        'message': 'Project created',
        'project': {
            'id': project_id,
            'name': name,
            'language': language,
            'description': description,
        }
    }), 201


@projects_bp.route('/api/projects/<int:project_id>', methods=['DELETE'])
@login_required
def delete_project(user, project_id):
    conn = get_db()
    project = conn.execute(
        'SELECT * FROM projects WHERE id = ? AND user_id = ?',
        (project_id, user['id'])
    ).fetchone()

    if not project:
        conn.close()
        return jsonify({'error': 'Project not found'}), 404

    conn.execute('DELETE FROM projects WHERE id = ?', (project_id,))
    conn.commit()
    conn.close()

    project_path = get_project_path(user['id'], project['name'])
    if os.path.exists(project_path):
        shutil.rmtree(project_path)

    return jsonify({'message': 'Project deleted'})


@projects_bp.route('/api/projects/<int:project_id>', methods=['PUT'])
@login_required
def rename_project(user, project_id):
    data = request.get_json()
    new_name = data.get('name', '').strip()

    if not new_name:
        return jsonify({'error': 'New name is required'}), 400

    conn = get_db()
    project = conn.execute(
        'SELECT * FROM projects WHERE id = ? AND user_id = ?',
        (project_id, user['id'])
    ).fetchone()

    if not project:
        conn.close()
        return jsonify({'error': 'Project not found'}), 404

    existing = conn.execute(
        'SELECT id FROM projects WHERE user_id = ? AND name = ? AND id != ?',
        (user['id'], new_name, project_id)
    ).fetchone()

    if existing:
        conn.close()
        return jsonify({'error': 'A project with this name already exists'}), 409

    old_path = get_project_path(user['id'], project['name'])
    new_path = get_project_path(user['id'], new_name)

    if os.path.exists(old_path):
        os.rename(old_path, new_path)

    conn.execute(
        'UPDATE projects SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
        (new_name, project_id)
    )
    conn.commit()
    conn.close()

    return jsonify({'message': 'Project renamed', 'name': new_name})
