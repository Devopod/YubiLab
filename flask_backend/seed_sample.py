"""Seed a sample project for new users."""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from models import get_db
from config import WORKSPACES_DIR


CALCULATOR_FILES = {
    'app.py': '''from flask import Flask, render_template, request
import os

app = Flask(__name__)

# Helper function for safe evaluation
def safe_eval(expr):
    try:
        # Only allow digits and operators
        allowed_chars = "0123456789+-*/(). "
        if any(c not in allowed_chars for c in expr):
            return "Invalid Input"
        return eval(expr)
    except ZeroDivisionError:
        return "Division by Zero Error"
    except Exception:
        return "Error"

@app.route("/", methods=["GET", "POST"])
def index():
    result = ""
    expression = ""
    if request.method == "POST":
        expression = request.form.get("expression", "")
        result = safe_eval(expression)
    return render_template("index.html", result=result, expression=expression)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", os.environ.get("FLASK_RUN_PORT", 3000)))
    app.run(host="0.0.0.0", port=port, debug=True)
''',
    'requirements.txt': '''Flask==2.3.3
''',
    'templates/index.html': '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Flask Calculator</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
    <div class="calculator">
        <h2>Flask Calculator</h2>
        <form method="POST">
            <input type="text" name="expression" placeholder="Enter Expression" value="{{ expression }}" class="display" readonly>
            <div class="buttons">
                <button type="button" onclick="appendChar('7')">7</button>
                <button type="button" onclick="appendChar('8')">8</button>
                <button type="button" onclick="appendChar('9')">9</button>
                <button type="button" onclick="appendChar('/')">/</button>

                <button type="button" onclick="appendChar('4')">4</button>
                <button type="button" onclick="appendChar('5')">5</button>
                <button type="button" onclick="appendChar('6')">6</button>
                <button type="button" onclick="appendChar('*')">*</button>

                <button type="button" onclick="appendChar('1')">1</button>
                <button type="button" onclick="appendChar('2')">2</button>
                <button type="button" onclick="appendChar('3')">3</button>
                <button type="button" onclick="appendChar('-')">-</button>

                <button type="button" onclick="appendChar('0')">0</button>
                <button type="button" onclick="appendChar('.')">.</button>
                <button type="submit">=</button>
                <button type="button" onclick="appendChar('+')">+</button>

                <button type="button" onclick="clearDisplay()" class="clear">C</button>
            </div>
        </form>
        {% if result != "" %}
        <div class="result">Result: {{ result }}</div>
        {% endif %}
    </div>

    <script>
        function appendChar(char) {
            let input = document.querySelector(".display");
            input.value += char;
        }
        function clearDisplay() {
            document.querySelector(".display").value = "";
        }
    </script>
</body>
</html>
''',
    'static/style.css': '''body {
    display: flex;
    justify-content: center;
    align-items: center;
    height: 100vh;
    margin: 0;
    font-family: Arial, sans-serif;
    background: #f4f4f4;
}

.calculator {
    background: #fff;
    padding: 20px 25px;
    border-radius: 10px;
    box-shadow: 0 0 15px rgba(0,0,0,0.2);
    text-align: center;
    width: 300px;
}

.display {
    width: 100%;
    height: 40px;
    font-size: 18px;
    margin-bottom: 15px;
    text-align: right;
    padding-right: 10px;
    border-radius: 5px;
    border: 1px solid #ccc;
    box-sizing: border-box;
}

.buttons {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
}

button {
    padding: 15px;
    font-size: 18px;
    border: none;
    border-radius: 5px;
    background: #007bff;
    color: white;
    cursor: pointer;
    transition: 0.2s;
}

button:hover {
    background: #0056b3;
}

button.clear {
    grid-column: span 4;
    background: #dc3545;
}

button.clear:hover {
    background: #a71d2a;
}

.result {
    margin-top: 15px;
    font-size: 20px;
    font-weight: bold;
}
''',
}


SAMPLE_FILES = {
    'index.html': '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YubiLab Sample Project</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <div class="container">
        <div class="hero">
            <h1>Welcome to <span class="highlight">YubiLab</span></h1>
            <p class="subtitle">Your Cloud IDE is ready!</p>
            <div class="features">
                <div class="feature-card">
                    <div class="icon">&#9997;</div>
                    <h3>Code Editor</h3>
                    <p>Monaco-powered editor with syntax highlighting</p>
                </div>
                <div class="feature-card">
                    <div class="icon">&#9654;</div>
                    <h3>Run Code</h3>
                    <p>Execute Python, JS, C, C++, Java, Go, Rust</p>
                </div>
                <div class="feature-card">
                    <div class="icon">&#128187;</div>
                    <h3>Terminal</h3>
                    <p>Full interactive Linux shell in your browser</p>
                </div>
                <div class="feature-card">
                    <div class="icon">&#129302;</div>
                    <h3>YubiAI</h3>
                    <p>AI-powered code generation & debugging</p>
                </div>
            </div>
            <button id="counter-btn" class="cta-btn">Click Counter: <span id="count">0</span></button>
        </div>
    </div>
    <script src="script.js"></script>
</body>
</html>
''',
    'style.css': '''* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: 'Segoe UI', sans-serif;
    background: linear-gradient(135deg, #0d1117 0%, #161b22 50%, #1a1a2e 100%);
    color: #e6edf3;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
}

.container {
    max-width: 900px;
    padding: 40px 20px;
    text-align: center;
}

.hero h1 {
    font-size: 3rem;
    margin-bottom: 8px;
}

.highlight {
    background: linear-gradient(135deg, #58a6ff, #bc8cff);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.subtitle {
    color: #8b949e;
    font-size: 1.2rem;
    margin-bottom: 40px;
}

.features {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px;
    margin-bottom: 40px;
}

.feature-card {
    background: rgba(22, 27, 34, 0.8);
    border: 1px solid #30363d;
    border-radius: 12px;
    padding: 24px 16px;
    transition: transform 0.2s, border-color 0.2s;
}

.feature-card:hover {
    transform: translateY(-4px);
    border-color: #58a6ff;
}

.feature-card .icon {
    font-size: 2rem;
    margin-bottom: 12px;
}

.feature-card h3 {
    margin-bottom: 8px;
    font-size: 1rem;
}

.feature-card p {
    color: #8b949e;
    font-size: 0.85rem;
}

.cta-btn {
    background: linear-gradient(135deg, #58a6ff, #bc8cff);
    color: #fff;
    border: none;
    padding: 14px 32px;
    border-radius: 8px;
    font-size: 1.1rem;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.2s, transform 0.2s;
}

.cta-btn:hover {
    opacity: 0.9;
    transform: scale(1.05);
}
''',
    'script.js': '''// YubiLab Sample Project - Interactive Demo
let count = 0;

const btn = document.getElementById('counter-btn');
const countEl = document.getElementById('count');

btn.addEventListener('click', () => {
    count++;
    countEl.textContent = count;
    
    // Add a fun animation
    btn.style.transform = 'scale(1.1)';
    setTimeout(() => {
        btn.style.transform = 'scale(1)';
    }, 150);
});

console.log('YubiLab Sample Project loaded!');
console.log('Try editing this file and clicking Preview!');
''',
    'main.py': '''# YubiLab Sample - Python
# Click the Run button or press Ctrl+Enter to execute!

def greet(name):
    """Generate a greeting message."""
    return f"Hello, {name}! Welcome to YubiLab!"

def fibonacci(n):
    """Generate first n Fibonacci numbers."""
    fib = [0, 1]
    for i in range(2, n):
        fib.append(fib[-1] + fib[-2])
    return fib[:n]

# Main
if __name__ == "__main__":
    print(greet("Developer"))
    print()
    print("Fibonacci sequence (first 10):")
    print(fibonacci(10))
    print()
    print("YubiLab features:")
    features = [
        "Monaco Code Editor",
        "Interactive Terminal",
        "Multi-language Execution",
        "YubiAI Assistant",
        "File Explorer",
        "HTML Preview",
    ]
    for i, feature in enumerate(features, 1):
        print(f"  {i}. {feature}")
    print()
    print("Happy coding!")
''',
}


def _create_project_files(project_path, files_dict):
    """Create project files, handling nested directories."""
    os.makedirs(project_path, exist_ok=True)
    for filename, content in files_dict.items():
        filepath = os.path.join(project_path, filename)
        # Create subdirectories if needed (e.g., templates/index.html, static/style.css)
        filedir = os.path.dirname(filepath)
        if filedir and not os.path.exists(filedir):
            os.makedirs(filedir, exist_ok=True)
        with open(filepath, 'w') as f:
            f.write(content)


def seed_sample_project(user_id):
    """Create sample projects for the given user."""
    conn = get_db()

    projects_to_seed = [
        {
            'name': 'sample-project',
            'language': 'html',
            'description': 'Welcome to YubiLab! A sample project to get you started.',
            'files': SAMPLE_FILES,
        },
        {
            'name': 'flask-calculator',
            'language': 'python',
            'description': 'A responsive Flask calculator web app with safe expression evaluation.',
            'files': CALCULATOR_FILES,
        },
    ]

    created_ids = []
    for proj in projects_to_seed:
        existing = conn.execute(
            'SELECT id FROM projects WHERE user_id = ? AND name = ?',
            (user_id, proj['name'])
        ).fetchone()

        if existing:
            created_ids.append(existing['id'])
            continue

        cursor = conn.execute(
            'INSERT INTO projects (user_id, name, language, description) VALUES (?, ?, ?, ?)',
            (user_id, proj['name'], proj['language'], proj['description'])
        )
        project_id = cursor.lastrowid
        conn.commit()
        created_ids.append(project_id)

        project_path = os.path.join(WORKSPACES_DIR, str(user_id), proj['name'])
        _create_project_files(project_path, proj['files'])

    conn.close()
    return created_ids


def seed_calculator_for_existing_users():
    """Seed the flask-calculator project for all existing users who don't have it."""
    conn = get_db()
    users = conn.execute('SELECT id FROM users').fetchall()
    conn.close()

    count = 0
    for user in users:
        conn2 = get_db()
        existing = conn2.execute(
            'SELECT id FROM projects WHERE user_id = ? AND name = ?',
            (user['id'], 'flask-calculator')
        ).fetchone()
        conn2.close()

        if not existing:
            seed_sample_project(user['id'])
            count += 1

    return count


if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == '--seed-all':
            count = seed_calculator_for_existing_users()
            print(f"Seeded calculator project for {count} existing users")
        else:
            uid = int(sys.argv[1])
            ids = seed_sample_project(uid)
            print(f"Sample projects created for user {uid}, project IDs: {ids}")
    else:
        print("Usage: python seed_sample.py <user_id>")
        print("       python seed_sample.py --seed-all")
