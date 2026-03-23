"""Seed a sample project for new users."""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from models import get_db
from config import WORKSPACES_DIR


CALCULATOR_FILES = {
    'app.py': '''"""Backward-compatible entry point for the Flask Calculator.

This file exists so the deploy system can do:
    python3 -c "import app; app.app.run(host='0.0.0.0', port=PORT, debug=False)"

For direct execution, use: python run.py
"""

import os
from calculator import create_app

# Create the Flask app instance
app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", os.environ.get("FLASK_RUN_PORT", "3000")))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
''',
    'run.py': '''"""Entry point for the Flask Calculator application."""

import os
from calculator import create_app

application = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", os.environ.get("FLASK_RUN_PORT", "3000")))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    application.run(host="0.0.0.0", port=port, debug=debug)
''',
    'requirements.txt': '''Flask==2.3.3
Flask-WTF==1.2.1
pytest==7.4.4
''',
    'Procfile': '''web: python run.py
''',
    'calculator/__init__.py': '''"""Flask Calculator Application Package."""

import os
import logging
from typing import Optional

from flask import Flask


def create_app(config: Optional[dict] = None) -> Flask:
    """Create and configure the Flask application."""
    application = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), '..', 'templates'),
        static_folder=os.path.join(os.path.dirname(__file__), '..', 'static'),
    )

    application.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')
    application.config['WTF_CSRF_ENABLED'] = os.environ.get('WTF_CSRF_ENABLED', 'false').lower() == 'true'
    application.config['DEBUG'] = os.environ.get('FLASK_DEBUG', '0') == '1'

    if config:
        application.config.update(config)

    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )

    from flask_wtf.csrf import CSRFProtect
    CSRFProtect(application)

    @application.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'ALLOWALL'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self';"
        )
        return response

    from calculator.routes import calculator_bp
    application.register_blueprint(calculator_bp)

    return application
''',
    'calculator/utils.py': '''"""Safe arithmetic expression evaluator using Python's ast module."""

import ast
import logging
import operator
from typing import Union

logger = logging.getLogger(__name__)

BINARY_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Pow: operator.pow, ast.Mod: operator.mod,
}

UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class EvalError(Exception):
    def __init__(self, message: str, error_type: str = "error") -> None:
        super().__init__(message)
        self.error_type = error_type


def _eval_node(node: ast.AST) -> Union[int, float]:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise EvalError("Only numeric values are allowed", "invalid_input")
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in BINARY_OPS:
            raise EvalError("Unsupported operator", "unsupported_op")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if op_type == ast.Div and right == 0:
            raise EvalError("Division by Zero Error", "zero_division")
        if op_type == ast.Mod and right == 0:
            raise EvalError("Modulo by Zero Error", "zero_division")
        if op_type == ast.Pow and right > 100:
            raise EvalError("Exponent too large (max 100)", "overflow")
        return BINARY_OPS[op_type](left, right)
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in UNARY_OPS:
            raise EvalError("Unsupported unary operator", "unsupported_op")
        return UNARY_OPS[op_type](_eval_node(node.operand))
    raise EvalError("Unsupported expression element", "invalid_input")


def safe_eval(expr: str) -> Union[int, float, str]:
    """Safely evaluate an arithmetic expression using ast."""
    if not expr or not expr.strip():
        return "Empty Expression"
    expr = expr.strip()
    allowed_chars = set("0123456789+-*/.%() ")
    invalid = set(expr) - allowed_chars
    if invalid:
        chars = ", ".join(repr(c) for c in sorted(invalid))
        return f"Invalid characters: {chars}"
    try:
        tree = ast.parse(expr, mode='eval')
        result = _eval_node(tree)
        if isinstance(result, float) and result == int(result) and abs(result) < 1e15:
            return int(result)
        return round(result, 10) if isinstance(result, float) else result
    except EvalError as e:
        return str(e)
    except SyntaxError:
        return "Syntax Error: Invalid expression"
    except Exception:
        logger.exception("Unexpected error evaluating '%s'", expr)
        return "Error"
''',
    'calculator/routes.py': '''"""Calculator route handlers."""

import logging
from flask import Blueprint, render_template, request
from calculator.utils import safe_eval

logger = logging.getLogger(__name__)
calculator_bp = Blueprint('calculator', __name__)


@calculator_bp.route("/", methods=["GET", "POST"])
def index() -> str:
    """Render the calculator page and process expression submissions."""
    result: str = ""
    expression: str = ""
    error_type: str = ""
    if request.method == "POST":
        expression = request.form.get("expression", "").strip()
        logger.info("Evaluating expression: '%s'", expression)
        eval_result = safe_eval(expression)
        if isinstance(eval_result, (int, float)):
            result = str(eval_result)
        else:
            result = str(eval_result)
            error_type = "error"
    return render_template("index.html", result=result, expression=expression, error_type=error_type)
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
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
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
        <div class="result {% if error_type %}result-error{% endif %}">
            Result: {{ result }}
        </div>
        {% endif %}
    </div>

    <script>
        function appendChar(char) {
            let input = document.querySelector(".display");
            input.value += char;
        }
        function clearDisplay() {
            document.querySelector(".display").value = "";
            let resultEl = document.querySelector(".result");
            if (resultEl) resultEl.style.display = "none";
        }
    </script>
</body>
</html>
''',
    'static/style.css': '''* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    margin: 0;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
    background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
    -webkit-font-smoothing: antialiased;
}

.calculator {
    background: rgba(255, 255, 255, 0.05);
    backdrop-filter: blur(20px);
    padding: 28px;
    border-radius: 20px;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5), 0 0 40px rgba(88, 166, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.1);
    text-align: center;
    width: 340px;
    max-width: 95vw;
    animation: slideUp 0.5s ease-out;
}

@keyframes slideUp {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
}

.calculator h2 {
    color: #fff;
    font-size: 1.4rem;
    font-weight: 700;
    margin-bottom: 20px;
    background: linear-gradient(135deg, #58a6ff, #bc8cff);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

.display {
    width: 100%;
    height: 50px;
    font-size: 20px;
    margin-bottom: 16px;
    text-align: right;
    padding: 0 14px;
    border-radius: 12px;
    border: 1px solid rgba(255, 255, 255, 0.15);
    background: rgba(0, 0, 0, 0.3);
    color: #e6edf3;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    outline: none;
    transition: border-color 0.2s ease;
}

.display:focus {
    border-color: #58a6ff;
    box-shadow: 0 0 0 3px rgba(88, 166, 255, 0.15);
}

.buttons {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
}

button {
    padding: 16px;
    font-size: 18px;
    font-weight: 600;
    border: none;
    border-radius: 12px;
    background: linear-gradient(135deg, #58a6ff, #4c9aed);
    color: white;
    cursor: pointer;
    transition: all 0.2s ease;
    box-shadow: 0 4px 12px rgba(88, 166, 255, 0.2);
}

button:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(88, 166, 255, 0.35);
}

button:active {
    transform: translateY(0);
}

button[onclick*="/"], button[onclick*="*"] {
    background: linear-gradient(135deg, #bc8cff, #a370e8);
    box-shadow: 0 4px 12px rgba(188, 140, 255, 0.2);
}

button[onclick*="+"], button[onclick*="-"] {
    background: linear-gradient(135deg, #39d2c0, #2bb5a6);
    box-shadow: 0 4px 12px rgba(57, 210, 192, 0.2);
}

button[type="submit"] {
    background: linear-gradient(135deg, #3fb950, #2ea44f);
    box-shadow: 0 4px 12px rgba(63, 185, 80, 0.3);
    font-size: 20px;
}

button[type="submit"]:hover {
    box-shadow: 0 6px 20px rgba(63, 185, 80, 0.45);
}

button.clear {
    grid-column: span 4;
    background: linear-gradient(135deg, #f85149, #e04040);
    box-shadow: 0 4px 12px rgba(248, 81, 73, 0.2);
}

button.clear:hover {
    box-shadow: 0 6px 20px rgba(248, 81, 73, 0.4);
}

.result {
    margin-top: 16px;
    font-size: 22px;
    font-weight: 700;
    color: #3fb950;
    padding: 12px;
    border-radius: 10px;
    background: rgba(63, 185, 80, 0.08);
    border: 1px solid rgba(63, 185, 80, 0.2);
    animation: fadeIn 0.3s ease;
}

.result-error {
    color: #f85149;
    background: rgba(248, 81, 73, 0.08);
    border-color: rgba(248, 81, 73, 0.2);
}

@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}

@media (max-width: 400px) {
    .calculator { padding: 20px 16px; width: 100%; border-radius: 16px; }
    button { padding: 14px; font-size: 16px; }
    .display { height: 44px; font-size: 18px; }
    .calculator h2 { font-size: 1.2rem; }
}
''',
    'tests/__init__.py': '',
    'tests/test_calculator.py': '''"""Test suite for Flask Calculator."""

import pytest
from calculator import create_app
from calculator.utils import safe_eval


@pytest.fixture
def app():
    application = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'SECRET_KEY': 'test'})
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def csrf_client():
    application = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': True, 'SECRET_KEY': 'test'})
    return application.test_client()


class TestSafeEval:
    def test_addition(self):
        assert safe_eval("5+3") == 8

    def test_subtraction(self):
        assert safe_eval("10-4") == 6

    def test_multiplication(self):
        assert safe_eval("3*4") == 12

    def test_division(self):
        assert safe_eval("9/3") == 3

    def test_division_by_zero(self):
        assert safe_eval("5/0") == "Division by Zero Error"

    def test_empty(self):
        assert safe_eval("") == "Empty Expression"

    def test_invalid_chars(self):
        assert "Invalid characters" in safe_eval("import os")

    def test_power(self):
        assert safe_eval("2**3") == 8

    def test_parentheses(self):
        assert safe_eval("(2+3)*4") == 20


class TestRoutes:
    def test_get(self, client):
        assert client.get("/").status_code == 200

    def test_post(self, client):
        r = client.post("/", data={"expression": "5+3"})
        assert b"Result: 8" in r.data

    def test_security_headers(self, client):
        r = client.get("/")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"


class TestCSRF:
    def test_no_token_rejected(self, csrf_client):
        assert csrf_client.post("/", data={"expression": "5+3"}).status_code == 400
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
