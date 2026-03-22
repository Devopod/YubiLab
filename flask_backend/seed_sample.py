"""Seed a sample project for new users."""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from models import get_db
from config import WORKSPACES_DIR


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


def seed_sample_project(user_id):
    """Create a sample project for the given user."""
    conn = get_db()

    # Check if sample already exists
    existing = conn.execute(
        'SELECT id FROM projects WHERE user_id = ? AND name = ?',
        (user_id, 'sample-project')
    ).fetchone()

    if existing:
        conn.close()
        return existing['id']

    cursor = conn.execute(
        'INSERT INTO projects (user_id, name, language, description) VALUES (?, ?, ?, ?)',
        (user_id, 'sample-project', 'html', 'Welcome to YubiLab! A sample project to get you started.')
    )
    project_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Create files
    project_path = os.path.join(WORKSPACES_DIR, str(user_id), 'sample-project')
    os.makedirs(project_path, exist_ok=True)

    for filename, content in SAMPLE_FILES.items():
        filepath = os.path.join(project_path, filename)
        with open(filepath, 'w') as f:
            f.write(content)

    return project_id


if __name__ == '__main__':
    if len(sys.argv) > 1:
        uid = int(sys.argv[1])
        pid = seed_sample_project(uid)
        print(f"Sample project created for user {uid}, project ID: {pid}")
    else:
        print("Usage: python seed_sample.py <user_id>")
