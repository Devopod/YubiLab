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
    application.config['WTF_CSRF_ENABLED'] = False
    application.config['DEBUG'] = os.environ.get('FLASK_DEBUG', '0') == '1'

    if config:
        application.config.update(config)

    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )

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


NODEJS_TODO_FILES = {
    'package.json': '''{
  "name": "nodejs-todo-app",
  "version": "1.0.0",
  "description": "A simple Node.js Todo List web app",
  "main": "server.js",
  "scripts": {
    "start": "node server.js"
  },
  "dependencies": {
    "express": "^4.18.2"
  }
}
''',
    'server.js': '''const express = require('express');
const path = require('path');
const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, 'public')));

let todos = [
    { id: 1, text: 'Learn Node.js', done: false },
    { id: 2, text: 'Build a Todo App', done: true },
    { id: 3, text: 'Deploy on YubiLab', done: false },
];
let nextId = 4;

app.get('/api/todos', (req, res) => res.json(todos));

app.post('/api/todos', (req, res) => {
    const { text } = req.body;
    if (!text || !text.trim()) return res.status(400).json({ error: 'Text required' });
    const todo = { id: nextId++, text: text.trim(), done: false };
    todos.push(todo);
    res.status(201).json(todo);
});

app.put('/api/todos/:id', (req, res) => {
    const todo = todos.find(t => t.id === parseInt(req.params.id));
    if (!todo) return res.status(404).json({ error: 'Not found' });
    if (req.body.text !== undefined) todo.text = req.body.text;
    if (req.body.done !== undefined) todo.done = req.body.done;
    res.json(todo);
});

app.delete('/api/todos/:id', (req, res) => {
    todos = todos.filter(t => t.id !== parseInt(req.params.id));
    res.json({ status: 'deleted' });
});

app.listen(PORT, '0.0.0.0', () => {
    console.log(`Todo app running on http://0.0.0.0:${PORT}`);
});
''',
    'public/index.html': '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Node.js Todo App</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', sans-serif; background: linear-gradient(135deg, #0f0c29, #302b63, #24243e); color: #e6edf3; min-height: 100vh; display: flex; justify-content: center; align-items: flex-start; padding: 40px 16px; }
        .container { background: rgba(255,255,255,0.05); backdrop-filter: blur(20px); border: 1px solid rgba(255,255,255,0.1); border-radius: 20px; padding: 32px; width: 100%; max-width: 500px; }
        h1 { text-align: center; margin-bottom: 24px; background: linear-gradient(135deg, #58a6ff, #bc8cff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .input-row { display: flex; gap: 8px; margin-bottom: 20px; }
        input[type="text"] { flex: 1; padding: 12px 16px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.15); background: rgba(0,0,0,0.3); color: #e6edf3; font-size: 15px; outline: none; }
        input[type="text"]:focus { border-color: #58a6ff; }
        button { padding: 12px 20px; border: none; border-radius: 10px; background: linear-gradient(135deg, #58a6ff, #4c9aed); color: white; font-weight: 600; cursor: pointer; transition: transform 0.2s; }
        button:hover { transform: translateY(-2px); }
        .todo-item { display: flex; align-items: center; gap: 12px; padding: 12px; border-radius: 10px; margin-bottom: 8px; background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.05); }
        .todo-item.done span { text-decoration: line-through; opacity: 0.5; }
        .todo-item span { flex: 1; }
        .todo-item input[type="checkbox"] { width: 20px; height: 20px; cursor: pointer; }
        .del-btn { background: linear-gradient(135deg, #f85149, #e04040); padding: 6px 12px; font-size: 13px; }
        .empty { text-align: center; color: #8b949e; padding: 40px 0; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Todo List</h1>
        <div class="input-row">
            <input type="text" id="todo-input" placeholder="What needs to be done?">
            <button onclick="addTodo()">Add</button>
        </div>
        <div id="todo-list"></div>
    </div>
    <script>
        async function loadTodos() {
            const res = await fetch('/api/todos');
            const todos = await res.json();
            const list = document.getElementById('todo-list');
            if (!todos.length) { list.innerHTML = '<div class="empty">No todos yet. Add one above!</div>'; return; }
            list.innerHTML = todos.map(t => `
                <div class="todo-item ${t.done ? 'done' : ''}">
                    <input type="checkbox" ${t.done ? 'checked' : ''} onchange="toggleTodo(${t.id}, this.checked)">
                    <span>${t.text}</span>
                    <button class="del-btn" onclick="deleteTodo(${t.id})">X</button>
                </div>
            `).join('');
        }
        async function addTodo() {
            const input = document.getElementById('todo-input');
            const text = input.value.trim();
            if (!text) return;
            await fetch('/api/todos', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
            input.value = '';
            loadTodos();
        }
        async function toggleTodo(id, done) {
            await fetch('/api/todos/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ done }) });
            loadTodos();
        }
        async function deleteTodo(id) {
            await fetch('/api/todos/' + id, { method: 'DELETE' });
            loadTodos();
        }
        document.getElementById('todo-input').addEventListener('keypress', e => { if (e.key === 'Enter') addTodo(); });
        loadTodos();
    </script>
</body>
</html>
''',
}

PHP_CONTACT_FILES = {
    'index.php': '''<?php
$name = $email = $message = $status = "";

if ($_SERVER["REQUEST_METHOD"] === "POST") {
    $name = htmlspecialchars(trim($_POST["name"] ?? ""));
    $email = htmlspecialchars(trim($_POST["email"] ?? ""));
    $message = htmlspecialchars(trim($_POST["message"] ?? ""));

    if (empty($name) || empty($email) || empty($message)) {
        $status = "error";
    } elseif (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
        $status = "invalid_email";
    } else {
        $status = "success";
    }
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PHP Contact Form</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', sans-serif; background: linear-gradient(135deg, #0f0c29, #302b63, #24243e); color: #e6edf3; min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 20px; }
        .card { background: rgba(255,255,255,0.05); backdrop-filter: blur(20px); border: 1px solid rgba(255,255,255,0.1); border-radius: 20px; padding: 32px; width: 100%; max-width: 480px; }
        h2 { text-align: center; margin-bottom: 24px; background: linear-gradient(135deg, #58a6ff, #bc8cff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        label { display: block; margin-bottom: 6px; font-size: 0.9rem; color: #8b949e; }
        input, textarea { width: 100%; padding: 12px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.15); background: rgba(0,0,0,0.3); color: #e6edf3; font-size: 15px; margin-bottom: 16px; outline: none; font-family: inherit; }
        input:focus, textarea:focus { border-color: #58a6ff; }
        textarea { min-height: 100px; resize: vertical; }
        button { width: 100%; padding: 14px; border: none; border-radius: 10px; background: linear-gradient(135deg, #58a6ff, #4c9aed); color: white; font-size: 16px; font-weight: 600; cursor: pointer; transition: transform 0.2s; }
        button:hover { transform: translateY(-2px); }
        .msg { padding: 12px; border-radius: 10px; margin-bottom: 16px; text-align: center; }
        .msg.success { background: rgba(63,185,80,0.15); color: #3fb950; border: 1px solid rgba(63,185,80,0.3); }
        .msg.error { background: rgba(248,81,73,0.15); color: #f85149; border: 1px solid rgba(248,81,73,0.3); }
    </style>
</head>
<body>
    <div class="card">
        <h2>Contact Form</h2>
        <?php if ($status === "success"): ?>
            <div class="msg success">Thank you, <?= $name ?>! Your message has been received.</div>
        <?php elseif ($status === "error"): ?>
            <div class="msg error">All fields are required.</div>
        <?php elseif ($status === "invalid_email"): ?>
            <div class="msg error">Please enter a valid email address.</div>
        <?php endif; ?>
        <form method="POST">
            <label>Name</label>
            <input type="text" name="name" value="<?= $name ?>" placeholder="Your name" required>
            <label>Email</label>
            <input type="email" name="email" value="<?= $email ?>" placeholder="you@example.com" required>
            <label>Message</label>
            <textarea name="message" placeholder="Write your message..."><?= $message ?></textarea>
            <button type="submit">Send Message</button>
        </form>
    </div>
</body>
</html>
''',
}

GO_HELLO_FILES = {
    'main.go': '''package main

import (
\t"encoding/json"
\t"fmt"
\t"log"
\t"math/rand"
\t"net/http"
\t"os"
\t"time"
)

type Quote struct {
\tText   string `json:"text"`
\tAuthor string `json:"author"`
}

var quotes = []Quote{
\t{"The only way to do great work is to love what you do.", "Steve Jobs"},
\t{"Code is like humor. When you have to explain it, it's bad.", "Cory House"},
\t{"First, solve the problem. Then, write the code.", "John Johnson"},
\t{"Simplicity is the soul of efficiency.", "Austin Freeman"},
\t{"Make it work, make it right, make it fast.", "Kent Beck"},
\t{"Any fool can write code that a computer can understand.", "Martin Fowler"},
}

func main() {
\tport := os.Getenv("PORT")
\tif port == "" {
\t\tport = "3000"
\t}

\thttp.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
\t\tw.Header().Set("Content-Type", "text/html")
\t\tq := quotes[rand.Intn(len(quotes))]
\t\tfmt.Fprintf(w, `<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Go Quote Server</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',sans-serif;background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);color:#e6edf3;min-height:100vh;display:flex;justify-content:center;align-items:center;padding:20px}
.card{background:rgba(255,255,255,0.05);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,0.1);border-radius:20px;padding:40px;max-width:500px;text-align:center}
h1{margin-bottom:24px;background:linear-gradient(135deg,#58a6ff,#bc8cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
blockquote{font-size:1.3rem;font-style:italic;margin:20px 0;line-height:1.6;color:#c9d1d9}
.author{color:#8b949e;font-size:0.95rem}
a{display:inline-block;margin-top:20px;padding:12px 28px;background:linear-gradient(135deg,#58a6ff,#4c9aed);color:white;text-decoration:none;border-radius:10px;font-weight:600;transition:transform 0.2s}
a:hover{transform:translateY(-2px)}
</style></head><body><div class="card">
<h1>Go Quote Server</h1>
<blockquote>"%s"</blockquote>
<p class="author">- %s</p>
<a href="/">New Quote</a>
</div></body></html>`, q.Text, q.Author)
\t})

\thttp.HandleFunc("/api/quote", func(w http.ResponseWriter, r *http.Request) {
\t\tw.Header().Set("Content-Type", "application/json")
\t\tq := quotes[rand.Intn(len(quotes))]
\t\tjson.NewEncoder(w).Encode(q)
\t})

\tlog.Printf("Go server starting on port %s", port)
\tlog.Fatal(http.ListenAndServe("0.0.0.0:"+port, nil))
}

func init() {
\trand.Seed(time.Now().UnixNano())
}
''',
}

JAVA_HELLO_FILES = {
    'Main.java': '''import java.util.Scanner;

public class Main {
    static final String[] COLORS = {
        "\\033[31m", "\\033[32m", "\\033[33m", "\\033[34m", "\\033[35m", "\\033[36m"
    };
    static final String RESET = "\\033[0m";

    public static void main(String[] args) {
        Scanner scanner = new Scanner(System.in);

        System.out.println(COLORS[3] + "================================" + RESET);
        System.out.println(COLORS[4] + "  Java Number Guessing Game" + RESET);
        System.out.println(COLORS[3] + "================================" + RESET);
        System.out.println();

        int secret = (int) (Math.random() * 100) + 1;
        int attempts = 0;
        int maxAttempts = 7;

        System.out.println("I'm thinking of a number between 1 and 100.");
        System.out.println("You have " + maxAttempts + " attempts. Good luck!");
        System.out.println();

        while (attempts < maxAttempts) {
            attempts++;
            System.out.print(COLORS[5] + "Attempt " + attempts + "/" + maxAttempts + ": " + RESET);

            if (!scanner.hasNextInt()) {
                System.out.println(COLORS[0] + "Please enter a valid number!" + RESET);
                scanner.next();
                attempts--;
                continue;
            }

            int guess = scanner.nextInt();

            if (guess == secret) {
                System.out.println();
                System.out.println(COLORS[1] + "Congratulations! You guessed it in " + attempts + " attempts!" + RESET);
                System.out.println(COLORS[1] + "The number was: " + secret + RESET);
                scanner.close();
                return;
            } else if (guess < secret) {
                System.out.println(COLORS[2] + "Too low! Try higher." + RESET);
            } else {
                System.out.println(COLORS[0] + "Too high! Try lower." + RESET);
            }
        }

        System.out.println();
        System.out.println(COLORS[0] + "Game Over! The number was: " + secret + RESET);
        scanner.close();
    }
}
''',
}

RUBY_HELLO_FILES = {
    'main.rb': '''# Ruby - Interactive Greeting Generator
# Run this to see colorful output!

class Greeter
  COLORS = {
    red: "\\e[31m", green: "\\e[32m", yellow: "\\e[33m",
    blue: "\\e[34m", magenta: "\\e[35m", cyan: "\\e[36m",
  }
  RESET = "\\e[0m"

  def initialize(name)
    @name = name
    @greetings = [
      "Hello, #{name}! Welcome to Ruby on YubiLab!",
      "Greetings, #{name}! Ruby is elegant and fun!",
      "Hey #{name}! Let's write some beautiful Ruby code!",
      "Welcome #{name}! Ruby makes developers happy!",
    ]
  end

  def colorize(text, color)
    "#{COLORS[color]}#{text}#{RESET}"
  end

  def greet
    greeting = @greetings.sample
    color = COLORS.keys.sample
    colorize(greeting, color)
  end

  def ascii_art
    <<~ART
      #{colorize("  ____        _           ", :red)}
      #{colorize(" |  _ \\ _   _| |__  _   _ ", :yellow)}
      #{colorize(" | |_) | | | | '_ \\| | | |", :green)}
      #{colorize(" |  _ <| |_| | |_) | |_| |", :cyan)}
      #{colorize(" |_| \\_\\\\__,_|_.__/ \\__, |", :blue)}
      #{colorize("                    |___/ ", :magenta)}
    ART
  end
end

# Main
puts ""
greeter = Greeter.new("Developer")
puts greeter.ascii_art
puts ""
5.times do |i|
  puts "  #{i + 1}. #{greeter.greet}"
end
puts ""
puts greeter.colorize("  Happy coding with Ruby on YubiLab!", :green)
puts ""

# Fibonacci with Ruby elegance
fib = [0, 1]
8.times { fib << fib[-1] + fib[-2] }
puts greeter.colorize("  Fibonacci: #{fib.join(', ')}", :cyan)
puts ""
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


CHATBOT_FILES = {
    'app.py': '''"""Infinite Learner AI Chatbot — Developed by Dewan Sakibul Islam, Dhaka, Bangladesh.
A stylish Flask chatbot powered by YubiAI GPT-OSS 120B model.
"""

import os
import json
import requests
from flask import Flask, render_template, request, jsonify, session

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'infinite-learner-secret-key')

# YubiAI API Configuration
API_URL = os.environ.get('YUBIAI_API_URL', 'https://yubiai.onrender.com/api/v1/chat')
API_KEY = os.environ.get('YUBIAI_API_KEY', '')

SYSTEM_PROMPT = """You are Infinite Learner AI, an intelligent, friendly, and knowledgeable AI chatbot developed by Dewan Sakibul Islam at Dhaka, Bangladesh. You are powered by GPT-OSS 120B.

Your personality:
- Warm, helpful, and encouraging
- You explain complex topics in simple terms
- You use examples and analogies to teach
- You can help with coding, math, science, writing, and general knowledge
- You always encourage learning and curiosity
- When you don\'t know something, you say so honestly

Keep responses concise but informative. Use markdown formatting for code blocks and lists when appropriate."""


@app.route('/')
def index():
    if 'messages' not in session:
        session['messages'] = []
    return render_template('index.html')


@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_message = data.get('message', '').strip()

    if not user_message:
        return jsonify({'error': 'Message is required'}), 400

    if not API_KEY:
        return jsonify({'error': 'YubiAI API key not configured. Set YUBIAI_API_KEY environment variable.'}), 500

    # Build conversation history
    if 'messages' not in session:
        session['messages'] = []

    session['messages'].append({'role': 'user', 'content': user_message})

    # Keep last 20 messages for context
    history = session['messages'][-20:]

    try:
        resp = requests.post(
            API_URL,
            headers={
                'Authorization': f'Bearer {API_KEY}',
                'Content-Type': 'application/json',
            },
            json={
                'message': user_message,
                'model': 'gpt-oss-120b',
                'system_prompt': SYSTEM_PROMPT,
                'conversation_history': [
                    {'role': m['role'], 'content': m['content']}
                    for m in history[:-1]  # exclude current message (already in 'message' field)
                ],
                'temperature': 0.7,
                'top_p': 0.9,
                'max_tokens': 2048,
            },
            timeout=120,
        )

        if resp.status_code == 200:
            result = resp.json()
            ai_response = result.get('response', 'I could not generate a response.')
            model = result.get('model', 'gpt-oss-120b')
            usage = result.get('usage', {})

            session['messages'].append({'role': 'assistant', 'content': ai_response})
            session.modified = True

            return jsonify({
                'response': ai_response,
                'model': model,
                'usage': usage,
            })
        else:
            error_text = resp.text
            if 'ngrok' in error_text.lower() or 'offline' in error_text.lower():
                return jsonify({'error': 'YubiAI API is currently offline. Please try again later.'}), 503
            return jsonify({'error': f'API returned status {resp.status_code}'}), 500

    except requests.exceptions.ConnectionError:
        return jsonify({'error': 'Cannot connect to YubiAI API. The server may be offline.'}), 503
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Request timed out. Please try again.'}), 504
    except Exception as e:
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500


@app.route('/api/clear', methods=['POST'])
def clear_chat():
    session['messages'] = []
    return jsonify({'status': 'cleared'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', os.environ.get('FLASK_RUN_PORT', '3000')))
    app.run(host='0.0.0.0', port=port, debug=True)
''',
    'requirements.txt': '''Flask==2.3.3
requests==2.31.0
''',
    'templates/index.html': '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Infinite Learner AI</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
    <div class="chat-container">
        <header class="chat-header">
            <div class="header-left">
                <div class="bot-avatar">
                    <span class="pulse"></span>
                    IL
                </div>
                <div class="header-info">
                    <h1>Infinite Learner AI</h1>
                    <p class="subtitle">Powered by GPT-OSS 120B &bull; by Dewan Sakibul Islam</p>
                </div>
            </div>
            <div class="header-actions">
                <button class="btn-icon" onclick="clearChat()" title="Clear chat">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14"/></svg>
                </button>
            </div>
        </header>

        <div class="chat-messages" id="chat-messages">
            <div class="welcome-message">
                <div class="welcome-avatar">IL</div>
                <h2>Welcome to Infinite Learner AI!</h2>
                <p>I'm your intelligent AI assistant powered by GPT-OSS 120B. Ask me anything about coding, science, math, or any topic!</p>
                <div class="suggestion-chips">
                    <button class="chip" onclick="sendSuggestion('Explain quantum computing in simple terms')">Explain quantum computing</button>
                    <button class="chip" onclick="sendSuggestion('Write a Python function to sort a list')">Python sorting function</button>
                    <button class="chip" onclick="sendSuggestion('What are the best practices for web development?')">Web dev best practices</button>
                    <button class="chip" onclick="sendSuggestion('Tell me about Bangladesh')">About Bangladesh</button>
                </div>
                <p class="dev-credit">Developed by <strong>Dewan Sakibul Islam</strong> &bull; Dhaka, Bangladesh</p>
            </div>
        </div>

        <div class="chat-input-area">
            <div class="input-wrapper">
                <textarea id="message-input" placeholder="Ask me anything..." rows="1" onkeydown="handleKeyDown(event)"></textarea>
                <button class="send-btn" id="send-btn" onclick="sendMessage()">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
                </button>
            </div>
            <p class="input-footer">Infinite Learner AI can make mistakes. Verify important information.</p>
        </div>
    </div>
    <script src="{{ url_for('static', filename='chat.js') }}"></script>
</body>
</html>
''',
    'static/style.css': '''* { margin: 0; padding: 0; box-sizing: border-box; }

:root {
    --bg-primary: #0d1117;
    --bg-secondary: #161b22;
    --bg-tertiary: #1c2333;
    --text-primary: #e6edf3;
    --text-secondary: #8b949e;
    --accent-blue: #58a6ff;
    --accent-purple: #bc8cff;
    --accent-green: #3fb950;
    --accent-orange: #f0883e;
    --border-color: rgba(255,255,255,0.08);
    --user-bubble: linear-gradient(135deg, #58a6ff, #4c9aed);
    --bot-bubble: rgba(255,255,255,0.06);
}

body {
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
}

.chat-container {
    display: flex;
    flex-direction: column;
    height: 100vh;
    max-width: 900px;
    margin: 0 auto;
}

/* Header */
.chat-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 24px;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
    flex-shrink: 0;
}

.header-left { display: flex; align-items: center; gap: 14px; }

.bot-avatar {
    width: 44px; height: 44px;
    border-radius: 50%;
    background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 0.9rem; color: #fff;
    position: relative;
    box-shadow: 0 4px 16px rgba(88,166,255,0.25);
}

.pulse {
    position: absolute; bottom: 0; right: 0;
    width: 12px; height: 12px;
    border-radius: 50%;
    background: var(--accent-green);
    border: 2px solid var(--bg-secondary);
}

.header-info h1 {
    font-size: 1.1rem; font-weight: 700;
    background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}

.subtitle { font-size: 0.75rem; color: var(--text-secondary); margin-top: 2px; }

.btn-icon {
    width: 40px; height: 40px;
    border-radius: 10px; border: 1px solid var(--border-color);
    background: transparent; color: var(--text-secondary);
    display: flex; align-items: center; justify-content: center;
    cursor: pointer; transition: all 0.2s;
}
.btn-icon:hover { background: rgba(255,255,255,0.06); color: var(--text-primary); }

/* Messages Area */
.chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 24px;
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.chat-messages::-webkit-scrollbar { width: 6px; }
.chat-messages::-webkit-scrollbar-track { background: transparent; }
.chat-messages::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }

/* Welcome Message */
.welcome-message {
    text-align: center;
    padding: 60px 20px;
    animation: fadeIn 0.5s ease;
}

.welcome-avatar {
    width: 80px; height: 80px;
    border-radius: 50%;
    background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
    display: flex; align-items: center; justify-content: center;
    font-size: 1.8rem; font-weight: 700; color: #fff;
    margin: 0 auto 20px;
    box-shadow: 0 8px 32px rgba(88,166,255,0.3);
    animation: float 3s ease-in-out infinite;
}

@keyframes float {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-8px); }
}

.welcome-message h2 {
    font-size: 1.5rem; margin-bottom: 12px;
    background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}

.welcome-message p { color: var(--text-secondary); max-width: 480px; margin: 0 auto; line-height: 1.6; }

.suggestion-chips {
    display: flex; flex-wrap: wrap; gap: 8px;
    justify-content: center; margin-top: 24px;
}

.chip {
    padding: 8px 16px;
    border-radius: 20px;
    border: 1px solid var(--border-color);
    background: var(--bg-secondary);
    color: var(--text-secondary);
    font-size: 0.82rem; cursor: pointer;
    transition: all 0.2s;
}
.chip:hover { border-color: var(--accent-blue); color: var(--accent-blue); background: rgba(88,166,255,0.08); }

.dev-credit { margin-top: 32px; font-size: 0.78rem; color: var(--text-secondary); opacity: 0.6; }

/* Message Bubbles */
.message { display: flex; gap: 12px; max-width: 85%; animation: slideUp 0.3s ease; }
.message.user { margin-left: auto; flex-direction: row-reverse; }

@keyframes slideUp {
    from { opacity: 0; transform: translateY(12px); }
    to { opacity: 1; transform: translateY(0); }
}
@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}

.msg-avatar {
    width: 34px; height: 34px; min-width: 34px;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 0.75rem; color: #fff;
    flex-shrink: 0;
}
.message.bot .msg-avatar { background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple)); }
.message.user .msg-avatar { background: linear-gradient(135deg, var(--accent-green), #2ea44f); }

.msg-content {
    padding: 12px 16px;
    border-radius: 16px;
    line-height: 1.6;
    font-size: 0.92rem;
    word-wrap: break-word;
}
.message.bot .msg-content {
    background: var(--bot-bubble);
    border: 1px solid var(--border-color);
    border-top-left-radius: 4px;
}
.message.user .msg-content {
    background: var(--user-bubble);
    color: #fff;
    border-top-right-radius: 4px;
}

.msg-content pre {
    background: rgba(0,0,0,0.3);
    border-radius: 8px;
    padding: 12px;
    overflow-x: auto;
    margin: 8px 0;
    font-size: 0.85rem;
    border: 1px solid rgba(255,255,255,0.05);
}
.msg-content code {
    background: rgba(0,0,0,0.2);
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.85rem;
}
.msg-content pre code { background: none; padding: 0; }

.msg-meta {
    font-size: 0.7rem;
    color: var(--text-secondary);
    margin-top: 6px;
    opacity: 0.6;
}

/* Typing Indicator */
.typing-indicator {
    display: flex; gap: 4px; padding: 12px 16px;
    background: var(--bot-bubble);
    border: 1px solid var(--border-color);
    border-radius: 16px; border-top-left-radius: 4px;
    width: fit-content;
}
.typing-indicator span {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--text-secondary);
    animation: bounce 1.4s infinite both;
}
.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
    0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
    40% { transform: scale(1); opacity: 1; }
}

/* Input Area */
.chat-input-area {
    padding: 16px 24px 20px;
    background: var(--bg-secondary);
    border-top: 1px solid var(--border-color);
    flex-shrink: 0;
}

.input-wrapper {
    display: flex; align-items: flex-end; gap: 12px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border-color);
    border-radius: 16px;
    padding: 8px 8px 8px 16px;
    transition: border-color 0.2s;
}
.input-wrapper:focus-within { border-color: var(--accent-blue); box-shadow: 0 0 0 3px rgba(88,166,255,0.1); }

textarea {
    flex: 1; border: none; background: none;
    color: var(--text-primary);
    font-size: 0.95rem;
    font-family: inherit;
    resize: none;
    outline: none;
    padding: 8px 0;
    max-height: 150px;
    line-height: 1.5;
}
textarea::placeholder { color: var(--text-secondary); }

.send-btn {
    width: 40px; height: 40px; min-width: 40px;
    border-radius: 12px; border: none;
    background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
    color: #fff;
    display: flex; align-items: center; justify-content: center;
    cursor: pointer;
    transition: all 0.2s;
    box-shadow: 0 4px 12px rgba(88,166,255,0.25);
}
.send-btn:hover { transform: scale(1.05); box-shadow: 0 6px 20px rgba(88,166,255,0.35); }
.send-btn:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }

.input-footer {
    text-align: center;
    font-size: 0.72rem;
    color: var(--text-secondary);
    margin-top: 8px;
    opacity: 0.5;
}

/* Responsive */
@media (max-width: 768px) {
    .chat-header { padding: 12px 16px; }
    .chat-messages { padding: 16px; }
    .chat-input-area { padding: 12px 16px 16px; }
    .message { max-width: 92%; }
    .welcome-message { padding: 40px 16px; }
    .welcome-avatar { width: 64px; height: 64px; font-size: 1.5rem; }
    .welcome-message h2 { font-size: 1.2rem; }
    .suggestion-chips { gap: 6px; }
    .chip { font-size: 0.78rem; padding: 6px 12px; }
}

@media (max-width: 480px) {
    .header-info h1 { font-size: 0.95rem; }
    .subtitle { font-size: 0.7rem; }
    .bot-avatar { width: 38px; height: 38px; font-size: 0.8rem; }
}
''',
    'static/chat.js': '''const messagesContainer = document.getElementById('chat-messages');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
let isTyping = false;

function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

// Auto-resize textarea
messageInput.addEventListener('input', () => {
    messageInput.style.height = 'auto';
    messageInput.style.height = Math.min(messageInput.scrollHeight, 150) + 'px';
});

function sendSuggestion(text) {
    messageInput.value = text;
    sendMessage();
}

function formatMessage(text) {
    // Convert markdown code blocks
    text = text.replace(/```(\\w*)\\n([\\s\\S]*?)```/g, '<pre><code>$2</code></pre>');
    // Inline code
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Bold
    text = text.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
    // Italic
    text = text.replace(/\\*([^*]+)\\*/g, '<em>$1</em>');
    // Line breaks
    text = text.replace(/\\n/g, '<br>');
    return text;
}

function addMessage(role, content, meta = '') {
    // Remove welcome message if it exists
    const welcome = messagesContainer.querySelector('.welcome-message');
    if (welcome) welcome.remove();

    const div = document.createElement('div');
    div.className = `message ${role}`;

    const avatarText = role === 'user' ? 'You' : 'IL';
    const formatted = role === 'bot' ? formatMessage(content) : content.replace(/\\n/g, '<br>');

    div.innerHTML = `
        <div class="msg-avatar">${avatarText}</div>
        <div>
            <div class="msg-content">${formatted}</div>
            ${meta ? `<div class="msg-meta">${meta}</div>` : ''}
        </div>
    `;

    messagesContainer.appendChild(div);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function showTyping() {
    const div = document.createElement('div');
    div.className = 'message bot';
    div.id = 'typing-msg';
    div.innerHTML = `
        <div class="msg-avatar">IL</div>
        <div class="typing-indicator">
            <span></span><span></span><span></span>
        </div>
    `;
    messagesContainer.appendChild(div);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function removeTyping() {
    const el = document.getElementById('typing-msg');
    if (el) el.remove();
}

async function sendMessage() {
    const message = messageInput.value.trim();
    if (!message || isTyping) return;

    isTyping = true;
    sendBtn.disabled = true;
    messageInput.value = '';
    messageInput.style.height = 'auto';

    addMessage('user', message);
    showTyping();

    try {
        const baseUrl = window.location.pathname.replace(/\/$/, '');
        const res = await fetch(baseUrl + '/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message }),
        });

        removeTyping();

        if (res.ok) {
            const data = await res.json();
            const meta = data.usage ? `${data.model || 'gpt-oss-120b'} &bull; ${data.usage.total_tokens || '?'} tokens` : '';
            addMessage('bot', data.response, meta);
        } else {
            let errorMsg = 'Something went wrong. Please try again.';
            try {
                const err = await res.json();
                errorMsg = err.error || errorMsg;
            } catch (e) {}
            addMessage('bot', errorMsg);
        }
    } catch (e) {
        removeTyping();
        addMessage('bot', 'Connection error. Please check if the server is running.');
    }

    isTyping = false;
    sendBtn.disabled = false;
    messageInput.focus();
}

async function clearChat() {
    const baseUrl = window.location.pathname.replace(/\/$/, '');
    try { await fetch(baseUrl + '/api/clear', { method: 'POST' }); } catch(e) {}
    messagesContainer.innerHTML = `
        <div class="welcome-message">
            <div class="welcome-avatar">IL</div>
            <h2>Welcome to Infinite Learner AI!</h2>
            <p>I\\'m your intelligent AI assistant powered by GPT-OSS 120B. Ask me anything about coding, science, math, or any topic!</p>
            <div class="suggestion-chips">
                <button class="chip" onclick="sendSuggestion('Explain quantum computing in simple terms')">Explain quantum computing</button>
                <button class="chip" onclick="sendSuggestion('Write a Python function to sort a list')">Python sorting function</button>
                <button class="chip" onclick="sendSuggestion('What are the best practices for web development?')">Web dev best practices</button>
                <button class="chip" onclick="sendSuggestion('Tell me about Bangladesh')">About Bangladesh</button>
            </div>
            <p class="dev-credit">Developed by <strong>Dewan Sakibul Islam</strong> &bull; Dhaka, Bangladesh</p>
        </div>
    `;
}

messageInput.focus();
''',
}


FLUTTER_MUSIC_PLAYER_FILES = {
    'pubspec.yaml': '''name: music_player
description: A beautiful Music Player app built with Flutter and Material Design 3.
publish_to: 'none'
version: 1.0.0+1

environment:
  sdk: '>=3.0.0 <4.0.0'

dependencies:
  flutter:
    sdk: flutter
  cupertino_icons: ^1.0.6
  provider: ^6.1.1

dev_dependencies:
  flutter_test:
    sdk: flutter
  flutter_lints: ^3.0.1

flutter:
  uses-material-design: true
  assets:
    - assets/
''',
    'lib/main.dart': """import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'providers/music_provider.dart';
import 'screens/home_screen.dart';
import 'screens/player_screen.dart';
import 'screens/search_screen.dart';
import 'screens/library_screen.dart';

void main() {
  runApp(
    ChangeNotifierProvider(
      create: (_) => MusicProvider(),
      child: const MusicPlayerApp(),
    ),
  );
}

class MusicPlayerApp extends StatelessWidget {
  const MusicPlayerApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'YubiMusic',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF6C63FF),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(0xFF0D0D1A),
        cardColor: const Color(0xFF1A1A2E),
        fontFamily: 'Roboto',
      ),
      home: const MainScreen(),
    );
  }
}

class MainScreen extends StatefulWidget {
  const MainScreen({super.key});

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> {
  int _currentIndex = 0;

  final List<Widget> _screens = const [
    HomeScreen(),
    SearchScreen(),
    LibraryScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Stack(
        children: [
          _screens[_currentIndex],
          // Mini player at bottom
          Consumer<MusicProvider>(
            builder: (context, provider, child) {
              if (provider.currentSong == null) return const SizedBox.shrink();
              return Positioned(
                left: 0,
                right: 0,
                bottom: 80,
                child: GestureDetector(
                  onTap: () {
                    Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => const PlayerScreen()),
                    );
                  },
                  child: Container(
                    margin: const EdgeInsets.symmetric(horizontal: 8),
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                    decoration: BoxDecoration(
                      gradient: const LinearGradient(
                        colors: [Color(0xFF6C63FF), Color(0xFF3F3D9E)],
                      ),
                      borderRadius: BorderRadius.circular(16),
                      boxShadow: [
                        BoxShadow(
                          color: const Color(0xFF6C63FF).withOpacity(0.3),
                          blurRadius: 20,
                          offset: const Offset(0, 8),
                        ),
                      ],
                    ),
                    child: Row(
                      children: [
                        Container(
                          width: 42,
                          height: 42,
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(10),
                            color: Colors.white.withOpacity(0.2),
                          ),
                          child: Icon(
                            provider.currentSong!.icon,
                            color: Colors.white,
                            size: 22,
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                provider.currentSong!.title,
                                style: const TextStyle(
                                  color: Colors.white,
                                  fontWeight: FontWeight.w600,
                                  fontSize: 14,
                                ),
                                overflow: TextOverflow.ellipsis,
                              ),
                              Text(
                                provider.currentSong!.artist,
                                style: TextStyle(
                                  color: Colors.white.withOpacity(0.7),
                                  fontSize: 12,
                                ),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ],
                          ),
                        ),
                        IconButton(
                          icon: Icon(
                            provider.isPlaying ? Icons.pause_rounded : Icons.play_arrow_rounded,
                            color: Colors.white,
                            size: 32,
                          ),
                          onPressed: provider.togglePlayPause,
                        ),
                        IconButton(
                          icon: const Icon(Icons.skip_next_rounded, color: Colors.white, size: 28),
                          onPressed: provider.nextSong,
                        ),
                      ],
                    ),
                  ),
                ),
              );
            },
          ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex,
        onDestinationSelected: (i) => setState(() => _currentIndex = i),
        backgroundColor: const Color(0xFF0D0D1A),
        indicatorColor: const Color(0xFF6C63FF).withOpacity(0.2),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.home_rounded), label: 'Home'),
          NavigationDestination(icon: Icon(Icons.search_rounded), label: 'Search'),
          NavigationDestination(icon: Icon(Icons.library_music_rounded), label: 'Library'),
        ],
      ),
    );
  }
}
""",
    'lib/models/song.dart': """import 'package:flutter/material.dart';

class Song {
  final String id;
  final String title;
  final String artist;
  final String album;
  final Duration duration;
  final IconData icon;
  final Color color;
  final String genre;
  bool isFavorite;

  Song({
    required this.id,
    required this.title,
    required this.artist,
    required this.album,
    required this.duration,
    this.icon = Icons.music_note_rounded,
    this.color = const Color(0xFF6C63FF),
    this.genre = 'Pop',
    this.isFavorite = false,
  });

  String get durationString {
    final minutes = duration.inMinutes;
    final seconds = duration.inSeconds % 60;
    return '${minutes.toString().padLeft(2, "0")}:${seconds.toString().padLeft(2, "0")}';
  }
}

class Playlist {
  final String id;
  final String name;
  final String description;
  final IconData icon;
  final Color color;
  final List<Song> songs;

  Playlist({
    required this.id,
    required this.name,
    required this.description,
    this.icon = Icons.playlist_play_rounded,
    this.color = const Color(0xFF6C63FF),
    this.songs = const [],
  });
}
""",
    'lib/providers/music_provider.dart': """import 'dart:async';
import 'package:flutter/material.dart';
import '../models/song.dart';

class MusicProvider extends ChangeNotifier {
  List<Song> _songs = [];
  List<Playlist> _playlists = [];
  Song? _currentSong;
  bool _isPlaying = false;
  Duration _position = Duration.zero;
  bool _isShuffled = false;
  int _repeatMode = 0; // 0=off, 1=all, 2=one
  Timer? _timer;

  MusicProvider() {
    _initializeSongs();
    _initializePlaylists();
  }

  List<Song> get songs => _songs;
  List<Playlist> get playlists => _playlists;
  Song? get currentSong => _currentSong;
  bool get isPlaying => _isPlaying;
  Duration get position => _position;
  bool get isShuffled => _isShuffled;
  int get repeatMode => _repeatMode;
  List<Song> get favorites => _songs.where((s) => s.isFavorite).toList();

  void _initializeSongs() {
    _songs = [
      Song(id: '1', title: 'Midnight Dreams', artist: 'Luna Wave', album: 'Nocturnal', duration: const Duration(minutes: 3, seconds: 45), icon: Icons.nightlight_round, color: const Color(0xFF6C63FF), genre: 'Electronic'),
      Song(id: '2', title: 'Sunrise Boulevard', artist: 'The Horizons', album: 'Dawn', duration: const Duration(minutes: 4, seconds: 12), icon: Icons.wb_sunny_rounded, color: const Color(0xFFFF6B6B), genre: 'Indie'),
      Song(id: '3', title: 'Ocean Breeze', artist: 'Coastal Vibes', album: 'Seaside', duration: const Duration(minutes: 3, seconds: 28), icon: Icons.waves_rounded, color: const Color(0xFF4ECDC4), genre: 'Chill'),
      Song(id: '4', title: 'Mountain Echo', artist: 'Peak Collective', album: 'Summit', duration: const Duration(minutes: 5, seconds: 01), icon: Icons.landscape_rounded, color: const Color(0xFFFF8A5C), genre: 'Ambient'),
      Song(id: '5', title: 'City Lights', artist: 'Urban Beat', album: 'Metro', duration: const Duration(minutes: 3, seconds: 55), icon: Icons.location_city_rounded, color: const Color(0xFFA29BFE), genre: 'Pop'),
      Song(id: '6', title: 'Forest Rain', artist: 'Nature Sound', album: 'Earth', duration: const Duration(minutes: 4, seconds: 33), icon: Icons.forest_rounded, color: const Color(0xFF2ECC71), genre: 'Nature'),
      Song(id: '7', title: 'Desert Storm', artist: 'Sand Riders', album: 'Sahara', duration: const Duration(minutes: 3, seconds: 17), icon: Icons.wb_twighlight, color: const Color(0xFFE17055), genre: 'Rock'),
      Song(id: '8', title: 'Neon Nights', artist: 'Synth Wave', album: 'Retro', duration: const Duration(minutes: 4, seconds: 08), icon: Icons.flashlight_on_rounded, color: const Color(0xFFFF6FF2), genre: 'Synthwave'),
      Song(id: '9', title: 'Rainy Jazz', artist: 'Smooth Notes', album: 'Cafe', duration: const Duration(minutes: 5, seconds: 22), icon: Icons.coffee_rounded, color: const Color(0xFF636E72), genre: 'Jazz'),
      Song(id: '10', title: 'Summer Vibes', artist: 'Beach Party', album: 'Tropical', duration: const Duration(minutes: 3, seconds: 40), icon: Icons.beach_access_rounded, color: const Color(0xFFFFA62B), genre: 'Tropical'),
      Song(id: '11', title: 'Starfall', artist: 'Cosmic Drift', album: 'Galaxy', duration: const Duration(minutes: 4, seconds: 15), icon: Icons.star_rounded, color: const Color(0xFF9B59B6), genre: 'Electronic'),
      Song(id: '12', title: 'Thunder Road', artist: 'Storm Chasers', album: 'Electric', duration: const Duration(minutes: 3, seconds: 52), icon: Icons.bolt_rounded, color: const Color(0xFFF39C12), genre: 'Rock'),
    ];
  }

  void _initializePlaylists() {
    _playlists = [
      Playlist(id: 'p1', name: 'Chill Vibes', description: 'Relax and unwind', icon: Icons.spa_rounded, color: const Color(0xFF4ECDC4), songs: [_songs[2], _songs[5], _songs[8]]),
      Playlist(id: 'p2', name: 'Workout Mix', description: 'Get pumped up', icon: Icons.fitness_center_rounded, color: const Color(0xFFFF6B6B), songs: [_songs[6], _songs[11], _songs[4]]),
      Playlist(id: 'p3', name: 'Night Drive', description: 'Late night tunes', icon: Icons.directions_car_rounded, color: const Color(0xFF6C63FF), songs: [_songs[0], _songs[7], _songs[10]]),
      Playlist(id: 'p4', name: 'Focus Mode', description: 'Study and concentrate', icon: Icons.psychology_rounded, color: const Color(0xFFA29BFE), songs: [_songs[3], _songs[5], _songs[8]]),
      Playlist(id: 'p5', name: 'Summer Hits', description: 'Beach day playlist', icon: Icons.wb_sunny_rounded, color: const Color(0xFFFFA62B), songs: [_songs[1], _songs[9], _songs[4]]),
    ];
  }

  void playSong(Song song) {
    _currentSong = song;
    _isPlaying = true;
    _position = Duration.zero;
    _startTimer();
    notifyListeners();
  }

  void togglePlayPause() {
    _isPlaying = !_isPlaying;
    if (_isPlaying) {
      _startTimer();
    } else {
      _stopTimer();
    }
    notifyListeners();
  }

  void seekTo(Duration position) {
    _position = position;
    notifyListeners();
  }

  void nextSong() {
    if (_currentSong == null) return;
    final index = _songs.indexWhere((s) => s.id == _currentSong!.id);
    if (index < _songs.length - 1) {
      playSong(_songs[index + 1]);
    } else {
      playSong(_songs[0]);
    }
  }

  void previousSong() {
    if (_currentSong == null) return;
    if (_position.inSeconds > 3) {
      _position = Duration.zero;
      notifyListeners();
      return;
    }
    final index = _songs.indexWhere((s) => s.id == _currentSong!.id);
    if (index > 0) {
      playSong(_songs[index - 1]);
    } else {
      playSong(_songs[_songs.length - 1]);
    }
  }

  void toggleShuffle() {
    _isShuffled = !_isShuffled;
    notifyListeners();
  }

  void toggleRepeat() {
    _repeatMode = (_repeatMode + 1) % 3;
    notifyListeners();
  }

  void toggleFavorite(Song song) {
    song.isFavorite = !song.isFavorite;
    notifyListeners();
  }

  List<Song> searchSongs(String query) {
    if (query.isEmpty) return _songs;
    final q = query.toLowerCase();
    return _songs.where((s) =>
      s.title.toLowerCase().contains(q) ||
      s.artist.toLowerCase().contains(q) ||
      s.album.toLowerCase().contains(q) ||
      s.genre.toLowerCase().contains(q)
    ).toList();
  }

  void _startTimer() {
    _stopTimer();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (_currentSong != null && _position < _currentSong!.duration) {
        _position += const Duration(seconds: 1);
        notifyListeners();
      } else if (_currentSong != null) {
        if (_repeatMode == 2) {
          _position = Duration.zero;
        } else {
          nextSong();
        }
      }
    });
  }

  void _stopTimer() {
    _timer?.cancel();
    _timer = null;
  }

  @override
  void dispose() {
    _stopTimer();
    super.dispose();
  }
}
""",
    'lib/screens/home_screen.dart': """import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/music_provider.dart';
import '../models/song.dart';
import 'player_screen.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<MusicProvider>(
      builder: (context, provider, child) {
        return CustomScrollView(
          slivers: [
            SliverAppBar(
              expandedHeight: 120,
              floating: true,
              pinned: true,
              backgroundColor: const Color(0xFF0D0D1A),
              flexibleSpace: FlexibleSpaceBar(
                title: const Text(
                  'YubiMusic',
                  style: TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: 24,
                    letterSpacing: -0.5,
                  ),
                ),
                titlePadding: const EdgeInsets.only(left: 20, bottom: 16),
              ),
              actions: [
                IconButton(
                  icon: const Icon(Icons.notifications_outlined),
                  onPressed: () {},
                ),
                const CircleAvatar(
                  radius: 16,
                  backgroundColor: Color(0xFF6C63FF),
                  child: Text('Y', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                ),
                const SizedBox(width: 16),
              ],
            ),

            // Featured Section
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Featured Playlists',
                      style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: Colors.white),
                    ),
                    const SizedBox(height: 12),
                    SizedBox(
                      height: 180,
                      child: ListView.builder(
                        scrollDirection: Axis.horizontal,
                        itemCount: provider.playlists.length,
                        itemBuilder: (context, index) {
                          final playlist = provider.playlists[index];
                          return _PlaylistCard(playlist: playlist, provider: provider);
                        },
                      ),
                    ),
                  ],
                ),
              ),
            ),

            // Recently Played
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text(
                      'All Songs',
                      style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: Colors.white),
                    ),
                    TextButton(
                      onPressed: () {},
                      child: const Text('See All', style: TextStyle(color: Color(0xFF6C63FF))),
                    ),
                  ],
                ),
              ),
            ),

            // Song List
            SliverList(
              delegate: SliverChildBuilderDelegate(
                (context, index) {
                  final song = provider.songs[index];
                  return _SongTile(song: song, provider: provider);
                },
                childCount: provider.songs.length,
              ),
            ),

            // Bottom padding for mini player
            const SliverToBoxAdapter(child: SizedBox(height: 160)),
          ],
        );
      },
    );
  }
}

class _PlaylistCard extends StatelessWidget {
  final dynamic playlist;
  final MusicProvider provider;

  const _PlaylistCard({required this.playlist, required this.provider});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () {
        if (playlist.songs.isNotEmpty) {
          provider.playSong(playlist.songs[0]);
        }
      },
      child: Container(
        width: 160,
        margin: const EdgeInsets.only(right: 12),
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [playlist.color, playlist.color.withOpacity(0.6)],
          ),
          borderRadius: BorderRadius.circular(20),
          boxShadow: [
            BoxShadow(
              color: playlist.color.withOpacity(0.3),
              blurRadius: 16,
              offset: const Offset(0, 8),
            ),
          ],
        ),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              Icon(playlist.icon, color: Colors.white, size: 36),
              const SizedBox(height: 12),
              Text(
                playlist.name,
                style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 16),
              ),
              const SizedBox(height: 4),
              Text(
                playlist.description,
                style: TextStyle(color: Colors.white.withOpacity(0.8), fontSize: 12),
              ),
              const SizedBox(height: 4),
              Text(
                '${playlist.songs.length} songs',
                style: TextStyle(color: Colors.white.withOpacity(0.6), fontSize: 11),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SongTile extends StatelessWidget {
  final Song song;
  final MusicProvider provider;

  const _SongTile({required this.song, required this.provider});

  @override
  Widget build(BuildContext context) {
    final isCurrentSong = provider.currentSong?.id == song.id;
    return ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      leading: Container(
        width: 52,
        height: 52,
        decoration: BoxDecoration(
          gradient: LinearGradient(
            colors: [song.color, song.color.withOpacity(0.6)],
          ),
          borderRadius: BorderRadius.circular(14),
          boxShadow: isCurrentSong
              ? [BoxShadow(color: song.color.withOpacity(0.4), blurRadius: 12, offset: const Offset(0, 4))]
              : [],
        ),
        child: Icon(song.icon, color: Colors.white, size: 26),
      ),
      title: Text(
        song.title,
        style: TextStyle(
          color: isCurrentSong ? song.color : Colors.white,
          fontWeight: isCurrentSong ? FontWeight.w700 : FontWeight.w500,
          fontSize: 15,
        ),
      ),
      subtitle: Text(
        '${song.artist} • ${song.album}',
        style: TextStyle(color: Colors.white.withOpacity(0.5), fontSize: 13),
      ),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(song.durationString, style: TextStyle(color: Colors.white.withOpacity(0.4), fontSize: 12)),
          const SizedBox(width: 8),
          GestureDetector(
            onTap: () => provider.toggleFavorite(song),
            child: Icon(
              song.isFavorite ? Icons.favorite_rounded : Icons.favorite_border_rounded,
              color: song.isFavorite ? const Color(0xFFFF6B6B) : Colors.white.withOpacity(0.3),
              size: 22,
            ),
          ),
        ],
      ),
      onTap: () {
        provider.playSong(song);
        Navigator.of(context).push(
          MaterialPageRoute(builder: (_) => const PlayerScreen()),
        );
      },
    );
  }
}
""",
    'lib/screens/player_screen.dart': """import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/music_provider.dart';

class PlayerScreen extends StatelessWidget {
  const PlayerScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<MusicProvider>(
      builder: (context, provider, child) {
        final song = provider.currentSong;
        if (song == null) {
          return const Scaffold(
            body: Center(child: Text('No song playing', style: TextStyle(color: Colors.white))),
          );
        }

        final progress = song.duration.inSeconds > 0
            ? provider.position.inSeconds / song.duration.inSeconds
            : 0.0;

        return Scaffold(
          backgroundColor: const Color(0xFF0D0D1A),
          body: Container(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: [
                  song.color.withOpacity(0.3),
                  const Color(0xFF0D0D1A),
                ],
              ),
            ),
            child: SafeArea(
              child: Column(
                children: [
                  // Top bar
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        IconButton(
                          icon: const Icon(Icons.keyboard_arrow_down_rounded, color: Colors.white, size: 32),
                          onPressed: () => Navigator.of(context).pop(),
                        ),
                        const Text('NOW PLAYING', style: TextStyle(color: Colors.white70, fontSize: 12, letterSpacing: 2, fontWeight: FontWeight.w600)),
                        IconButton(
                          icon: const Icon(Icons.more_vert_rounded, color: Colors.white),
                          onPressed: () {},
                        ),
                      ],
                    ),
                  ),

                  const Spacer(),

                  // Album Art
                  Hero(
                    tag: 'album-art',
                    child: Container(
                      width: 280,
                      height: 280,
                      decoration: BoxDecoration(
                        gradient: LinearGradient(
                          begin: Alignment.topLeft,
                          end: Alignment.bottomRight,
                          colors: [song.color, song.color.withOpacity(0.4)],
                        ),
                        borderRadius: BorderRadius.circular(32),
                        boxShadow: [
                          BoxShadow(
                            color: song.color.withOpacity(0.4),
                            blurRadius: 40,
                            offset: const Offset(0, 20),
                          ),
                        ],
                      ),
                      child: Icon(song.icon, color: Colors.white, size: 100),
                    ),
                  ),

                  const Spacer(),

                  // Song Info
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 32),
                    child: Column(
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    song.title,
                                    style: const TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.w800),
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                  const SizedBox(height: 4),
                                  Text(
                                    '${song.artist} — ${song.album}',
                                    style: TextStyle(color: Colors.white.withOpacity(0.6), fontSize: 15),
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ],
                              ),
                            ),
                            GestureDetector(
                              onTap: () => provider.toggleFavorite(song),
                              child: Icon(
                                song.isFavorite ? Icons.favorite_rounded : Icons.favorite_border_rounded,
                                color: song.isFavorite ? const Color(0xFFFF6B6B) : Colors.white.withOpacity(0.5),
                                size: 28,
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 28),

                  // Progress Bar
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 32),
                    child: Column(
                      children: [
                        SliderTheme(
                          data: SliderTheme.of(context).copyWith(
                            trackHeight: 4,
                            thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 6),
                            overlayShape: const RoundSliderOverlayShape(overlayRadius: 14),
                            activeTrackColor: song.color,
                            inactiveTrackColor: Colors.white.withOpacity(0.1),
                            thumbColor: Colors.white,
                            overlayColor: song.color.withOpacity(0.2),
                          ),
                          child: Slider(
                            value: progress.clamp(0.0, 1.0),
                            onChanged: (v) {
                              provider.seekTo(Duration(seconds: (v * song.duration.inSeconds).toInt()));
                            },
                          ),
                        ),
                        Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 8),
                          child: Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              Text(_formatDuration(provider.position), style: TextStyle(color: Colors.white.withOpacity(0.5), fontSize: 12)),
                              Text(_formatDuration(song.duration), style: TextStyle(color: Colors.white.withOpacity(0.5), fontSize: 12)),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 16),

                  // Controls
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 32),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                      children: [
                        IconButton(
                          icon: Icon(
                            Icons.shuffle_rounded,
                            color: provider.isShuffled ? song.color : Colors.white.withOpacity(0.5),
                            size: 24,
                          ),
                          onPressed: provider.toggleShuffle,
                        ),
                        IconButton(
                          icon: const Icon(Icons.skip_previous_rounded, color: Colors.white, size: 36),
                          onPressed: provider.previousSong,
                        ),
                        Container(
                          width: 72,
                          height: 72,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            gradient: LinearGradient(colors: [song.color, song.color.withOpacity(0.7)]),
                            boxShadow: [
                              BoxShadow(color: song.color.withOpacity(0.4), blurRadius: 20, offset: const Offset(0, 8)),
                            ],
                          ),
                          child: IconButton(
                            icon: Icon(
                              provider.isPlaying ? Icons.pause_rounded : Icons.play_arrow_rounded,
                              color: Colors.white,
                              size: 36,
                            ),
                            onPressed: provider.togglePlayPause,
                          ),
                        ),
                        IconButton(
                          icon: const Icon(Icons.skip_next_rounded, color: Colors.white, size: 36),
                          onPressed: provider.nextSong,
                        ),
                        IconButton(
                          icon: Icon(
                            provider.repeatMode == 2 ? Icons.repeat_one_rounded : Icons.repeat_rounded,
                            color: provider.repeatMode > 0 ? song.color : Colors.white.withOpacity(0.5),
                            size: 24,
                          ),
                          onPressed: provider.toggleRepeat,
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 40),
                ],
              ),
            ),
          ),
        );
      },
    );
  }

  String _formatDuration(Duration d) {
    final minutes = d.inMinutes;
    final seconds = d.inSeconds % 60;
    return '${minutes.toString().padLeft(2, \"0\")}:${seconds.toString().padLeft(2, \"0\")}';
  }
}
""",
    'lib/screens/search_screen.dart': """import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/music_provider.dart';
import '../models/song.dart';
import 'player_screen.dart';

class SearchScreen extends StatefulWidget {
  const SearchScreen({super.key});

  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  String _query = '';
  final _controller = TextEditingController();

  @override
  Widget build(BuildContext context) {
    return Consumer<MusicProvider>(
      builder: (context, provider, child) {
        final results = provider.searchSongs(_query);
        final genres = ['All', 'Pop', 'Rock', 'Electronic', 'Jazz', 'Chill', 'Ambient', 'Indie', 'Synthwave'];

        return SafeArea(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(20, 16, 20, 8),
                child: Text('Search', style: TextStyle(fontSize: 28, fontWeight: FontWeight.w800, color: Colors.white)),
              ),

              // Search Bar
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                child: Container(
                  decoration: BoxDecoration(
                    color: const Color(0xFF1A1A2E),
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(color: Colors.white.withOpacity(0.05)),
                  ),
                  child: TextField(
                    controller: _controller,
                    onChanged: (v) => setState(() => _query = v),
                    style: const TextStyle(color: Colors.white),
                    decoration: InputDecoration(
                      hintText: 'Search songs, artists, albums...',
                      hintStyle: TextStyle(color: Colors.white.withOpacity(0.3)),
                      prefixIcon: Icon(Icons.search_rounded, color: Colors.white.withOpacity(0.4)),
                      suffixIcon: _query.isNotEmpty
                        ? IconButton(
                            icon: const Icon(Icons.clear_rounded, color: Colors.white54),
                            onPressed: () {
                              _controller.clear();
                              setState(() => _query = '');
                            },
                          )
                        : null,
                      border: InputBorder.none,
                      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
                    ),
                  ),
                ),
              ),

              // Genre chips
              SizedBox(
                height: 42,
                child: ListView.builder(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  itemCount: genres.length,
                  itemBuilder: (context, index) {
                    return Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: FilterChip(
                        label: Text(genres[index]),
                        selected: false,
                        onSelected: (v) => setState(() => _query = genres[index] == 'All' ? '' : genres[index]),
                        backgroundColor: const Color(0xFF1A1A2E),
                        selectedColor: const Color(0xFF6C63FF),
                        labelStyle: const TextStyle(color: Colors.white70, fontSize: 13),
                        side: BorderSide(color: Colors.white.withOpacity(0.05)),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                      ),
                    );
                  },
                ),
              ),

              const SizedBox(height: 8),

              // Results
              Expanded(
                child: results.isEmpty
                    ? Center(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(Icons.search_off_rounded, color: Colors.white.withOpacity(0.2), size: 64),
                            const SizedBox(height: 16),
                            Text('No songs found', style: TextStyle(color: Colors.white.withOpacity(0.4), fontSize: 16)),
                          ],
                        ),
                      )
                    : ListView.builder(
                        padding: const EdgeInsets.only(bottom: 160),
                        itemCount: results.length,
                        itemBuilder: (context, index) {
                          final song = results[index];
                          return _SearchResultTile(song: song, provider: provider);
                        },
                      ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _SearchResultTile extends StatelessWidget {
  final Song song;
  final MusicProvider provider;

  const _SearchResultTile({required this.song, required this.provider});

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 2),
      leading: Container(
        width: 48,
        height: 48,
        decoration: BoxDecoration(
          gradient: LinearGradient(colors: [song.color, song.color.withOpacity(0.5)]),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Icon(song.icon, color: Colors.white, size: 24),
      ),
      title: Text(song.title, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w500, fontSize: 15)),
      subtitle: Text('${song.artist} • ${song.genre}', style: TextStyle(color: Colors.white.withOpacity(0.5), fontSize: 13)),
      trailing: Text(song.durationString, style: TextStyle(color: Colors.white.withOpacity(0.4), fontSize: 12)),
      onTap: () {
        provider.playSong(song);
        Navigator.of(context).push(MaterialPageRoute(builder: (_) => const PlayerScreen()));
      },
    );
  }
}
""",
    'lib/screens/library_screen.dart': """import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/music_provider.dart';
import '../models/song.dart';
import 'player_screen.dart';

class LibraryScreen extends StatelessWidget {
  const LibraryScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<MusicProvider>(
      builder: (context, provider, child) {
        final favorites = provider.favorites;
        final playlists = provider.playlists;

        return SafeArea(
          child: CustomScrollView(
            slivers: [
              const SliverToBoxAdapter(
                child: Padding(
                  padding: EdgeInsets.fromLTRB(20, 16, 20, 16),
                  child: Text('Your Library', style: TextStyle(fontSize: 28, fontWeight: FontWeight.w800, color: Colors.white)),
                ),
              ),

              // Stats
              SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: Row(
                    children: [
                      _StatCard(icon: Icons.music_note_rounded, label: 'Songs', value: '${provider.songs.length}', color: const Color(0xFF6C63FF)),
                      const SizedBox(width: 12),
                      _StatCard(icon: Icons.favorite_rounded, label: 'Liked', value: '${favorites.length}', color: const Color(0xFFFF6B6B)),
                      const SizedBox(width: 12),
                      _StatCard(icon: Icons.playlist_play_rounded, label: 'Playlists', value: '${playlists.length}', color: const Color(0xFF4ECDC4)),
                    ],
                  ),
                ),
              ),

              // Playlists Section
              const SliverToBoxAdapter(
                child: Padding(
                  padding: EdgeInsets.fromLTRB(20, 24, 20, 12),
                  child: Text('Your Playlists', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: Colors.white)),
                ),
              ),

              SliverList(
                delegate: SliverChildBuilderDelegate(
                  (context, index) {
                    final playlist = playlists[index];
                    return ListTile(
                      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                      leading: Container(
                        width: 52,
                        height: 52,
                        decoration: BoxDecoration(
                          gradient: LinearGradient(colors: [playlist.color, playlist.color.withOpacity(0.5)]),
                          borderRadius: BorderRadius.circular(14),
                        ),
                        child: Icon(playlist.icon, color: Colors.white, size: 26),
                      ),
                      title: Text(playlist.name, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
                      subtitle: Text('${playlist.songs.length} songs', style: TextStyle(color: Colors.white.withOpacity(0.5), fontSize: 13)),
                      trailing: const Icon(Icons.chevron_right_rounded, color: Colors.white38),
                      onTap: () {
                        if (playlist.songs.isNotEmpty) {
                          provider.playSong(playlist.songs[0]);
                        }
                      },
                    );
                  },
                  childCount: playlists.length,
                ),
              ),

              // Favorites Section
              SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(20, 24, 20, 12),
                  child: Text(
                    'Liked Songs (${favorites.length})',
                    style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: Colors.white),
                  ),
                ),
              ),

              if (favorites.isEmpty)
                SliverToBoxAdapter(
                  child: Padding(
                    padding: const EdgeInsets.all(32),
                    child: Column(
                      children: [
                        Icon(Icons.favorite_border_rounded, color: Colors.white.withOpacity(0.15), size: 48),
                        const SizedBox(height: 12),
                        Text('No liked songs yet', style: TextStyle(color: Colors.white.withOpacity(0.4))),
                        const SizedBox(height: 4),
                        Text('Tap the heart icon on any song', style: TextStyle(color: Colors.white.withOpacity(0.25), fontSize: 13)),
                      ],
                    ),
                  ),
                ),

              if (favorites.isNotEmpty)
                SliverList(
                  delegate: SliverChildBuilderDelegate(
                    (context, index) {
                      final song = favorites[index];
                      return ListTile(
                        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 2),
                        leading: Container(
                          width: 48,
                          height: 48,
                          decoration: BoxDecoration(
                            gradient: LinearGradient(colors: [song.color, song.color.withOpacity(0.5)]),
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: Icon(song.icon, color: Colors.white, size: 24),
                        ),
                        title: Text(song.title, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w500)),
                        subtitle: Text(song.artist, style: TextStyle(color: Colors.white.withOpacity(0.5), fontSize: 13)),
                        trailing: IconButton(
                          icon: const Icon(Icons.favorite_rounded, color: Color(0xFFFF6B6B), size: 22),
                          onPressed: () => provider.toggleFavorite(song),
                        ),
                        onTap: () {
                          provider.playSong(song);
                          Navigator.of(context).push(MaterialPageRoute(builder: (_) => const PlayerScreen()));
                        },
                      );
                    },
                    childCount: favorites.length,
                  ),
                ),

              // Bottom padding
              const SliverToBoxAdapter(child: SizedBox(height: 160)),
            ],
          ),
        );
      },
    );
  }
}

class _StatCard extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  final Color color;

  const _StatCard({required this.icon, required this.label, required this.value, required this.color});

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: color.withOpacity(0.1),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: color.withOpacity(0.2)),
        ),
        child: Column(
          children: [
            Icon(icon, color: color, size: 28),
            const SizedBox(height: 8),
            Text(value, style: TextStyle(color: color, fontSize: 22, fontWeight: FontWeight.w800)),
            const SizedBox(height: 2),
            Text(label, style: TextStyle(color: Colors.white.withOpacity(0.5), fontSize: 12)),
          ],
        ),
      ),
    );
  }
}
""",
    'assets/.gitkeep': '',
    'analysis_options.yaml': '''include: package:flutter_lints/flutter.yaml

linter:
  rules:
    prefer_const_constructors: false
    prefer_const_literals_to_create_immutables: false
    use_key_in_widget_constructors: false
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
            'name': 'flask-calculator',
            'language': 'python',
            'description': 'A responsive Flask calculator web app with safe expression evaluation.',
            'files': CALCULATOR_FILES,
        },
        {
            'name': 'nodejs-todo-app',
            'language': 'javascript',
            'description': 'A Node.js + Express Todo List web app with REST API.',
            'files': NODEJS_TODO_FILES,
        },
        {
            'name': 'php-contact-form',
            'language': 'php',
            'description': 'A PHP contact form with validation and responsive UI.',
            'files': PHP_CONTACT_FILES,
        },
        {
            'name': 'go-quote-server',
            'language': 'go',
            'description': 'A Go web server that serves random programming quotes.',
            'files': GO_HELLO_FILES,
        },
        {
            'name': 'java-guessing-game',
            'language': 'java',
            'description': 'A Java number guessing game. Run in terminal!',
            'files': JAVA_HELLO_FILES,
        },
        {
            'name': 'ruby-greeter',
            'language': 'ruby',
            'description': 'A Ruby greeting generator with colorful ASCII art.',
            'files': RUBY_HELLO_FILES,
        },
        {
            'name': 'sample-project',
            'language': 'html',
            'description': 'Welcome to YubiLab! A sample HTML project to get you started.',
            'files': SAMPLE_FILES,
        },
        {
            'name': 'infinite-learner-chatbot',
            'language': 'python',
            'description': 'Infinite Learner AI Chatbot — powered by GPT-OSS 120B. By Dewan Sakibul Islam.',
            'files': CHATBOT_FILES,
        },
        {
            'name': 'flutter-music-player',
            'language': 'flutter',
            'description': 'A beautiful Music Player app built with Flutter & Material Design 3. Features playlist management, search, favorites, and now-playing UI.',
            'files': FLUTTER_MUSIC_PLAYER_FILES,
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


def seed_all_samples_for_existing_users():
    """Seed all sample projects for all existing users who don't have them."""
    conn = get_db()
    users = conn.execute('SELECT id FROM users').fetchall()
    conn.close()

    count = 0
    for user in users:
        seed_sample_project(user['id'])
        count += 1

    return count


if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == '--seed-all':
            count = seed_all_samples_for_existing_users()
            print(f"Seeded sample projects for {count} existing users")
        else:
            uid = int(sys.argv[1])
            ids = seed_sample_project(uid)
            print(f"Sample projects created for user {uid}, project IDs: {ids}")
    else:
        print("Usage: python seed_sample.py <user_id>")
        print("       python seed_sample.py --seed-all")
