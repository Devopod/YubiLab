# YubiLab - Cloud IDE Platform

A full-stack cloud IDE platform similar to Replit, built with Flask, Node.js, and vanilla JavaScript. Features real-time code editing with Monaco Editor, interactive terminal, multi-language code execution, file management, HTML preview, and YubiAI integration.

## Features

- **User Authentication** - Register, login, logout with session-based auth
- **Project Dashboard** - Create, list, rename, delete projects
- **Monaco Code Editor** - VS Code-like editor with syntax highlighting, tabs, auto-save
- **File Explorer** - Tree structure, create/rename/delete files & folders, context menu
- **Interactive Terminal** - Full Linux shell (node-pty + xterm.js) in the browser
- **Multi-Language Execution** - Python, JavaScript, C, C++, Java, Go, PHP, Rust
- **Real-Time Console** - Live stdout/stderr streaming via WebSocket
- **HTML Preview** - Render HTML projects in iframe with live reload
- **YubiAI Integration** - Code generation, debugging, explanation, autonomous agent
- **Sample Project** - Auto-seeded for new users

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend 1 | Python (Flask) - Auth, DB, API, project management |
| Backend 2 | Node.js - Code execution, terminal, WebSocket streaming |
| Frontend | HTML, CSS, JavaScript (vanilla) |
| Editor | Monaco Editor (VS Code engine) |
| Terminal | xterm.js + node-pty |
| Database | SQLite |
| Realtime | Socket.IO |
| AI | YubiAI (GPT-OSS 120B) |

## Project Structure

```
/yubilab
  /flask_backend     # Python Flask API server
    app.py           # Main Flask app
    auth.py          # Authentication routes
    projects.py      # Project management
    files.py         # File system operations
    ai.py            # YubiAI integration
    models.py        # Database models
    config.py        # Configuration
    seed_sample.py   # Sample project seeder
    requirements.txt
  /node_engine       # Node.js execution engine
    server.js        # Main server (Express + Socket.IO)
    terminal.js      # Terminal management (node-pty)
    executor.js      # Code execution engine
    package.json
  /frontend          # Static frontend
    index.html       # Dashboard
    login.html       # Auth page
    editor.html      # IDE editor
    /css/style.css   # Global styles
    /js/auth.js      # Auth module
    /js/dashboard.js # Dashboard module
    /js/editor.js    # Editor module (Monaco, terminal, AI, files)
  /user_workspaces   # User project files (created at runtime)
```

## Setup & Run

### Prerequisites

- Python 3.10+
- Node.js 18+
- npm

### Installation

```bash
# Clone the project
cd yubilab

# Install Flask dependencies
cd flask_backend
pip install -r requirements.txt
cd ..

# Install Node.js dependencies
cd node_engine
npm install
cd ..
```

### Running Locally

Start both servers:

```bash
# Terminal 1: Flask backend (port 5000)
cd flask_backend
python app.py

# Terminal 2: Node.js engine (port 3001)
cd node_engine
node server.js
```

Open http://localhost:5000 in your browser.

### Environment Variables (Optional)

```bash
# Flask
SECRET_KEY=your-secret-key
YUBIAI_API_URL=https://your-yubiai-endpoint/api/v1/chat
YUBIAI_API_KEY=your-api-key

# Node
NODE_ENGINE_PORT=3001
```

## Database Schema

### Users
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| username | TEXT UNIQUE | User's username |
| email | TEXT UNIQUE | User's email |
| password_hash | TEXT | Bcrypt password hash |
| created_at | TIMESTAMP | Registration date |

### Projects
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| user_id | INTEGER FK | Owner user |
| name | TEXT | Project name |
| language | TEXT | Primary language |
| description | TEXT | Project description |
| created_at | TIMESTAMP | Creation date |
| updated_at | TIMESTAMP | Last modified |

## API Endpoints

### Auth
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login
- `POST /api/auth/logout` - Logout
- `GET /api/auth/me` - Get current user

### Projects
- `GET /api/projects` - List user's projects
- `POST /api/projects` - Create project
- `PUT /api/projects/:id` - Rename project
- `DELETE /api/projects/:id` - Delete project

### Files
- `GET /api/projects/:id/files` - Get file tree
- `GET /api/projects/:id/files/content?path=` - Get file content
- `POST /api/projects/:id/files/save` - Save file
- `POST /api/projects/:id/files/create` - Create file/folder
- `POST /api/projects/:id/files/delete` - Delete file/folder
- `POST /api/projects/:id/files/rename` - Rename file/folder

### AI
- `POST /api/ai/generate` - Generate/debug/explain code
- `POST /api/ai/agent` - Autonomous agent (creates files, runs code)

### WebSocket Events (Socket.IO on port 3001)
- `terminal:start` / `terminal:input` / `terminal:output` / `terminal:resize`
- `code:run` / `code:run-stream` / `code:output` / `code:done` / `code:stop`

## Supported Languages

| Language | Extension | Execution |
|----------|-----------|-----------|
| Python | .py | python3 |
| JavaScript | .js | node |
| C | .c | gcc + run |
| C++ | .cpp | g++ + run |
| Java | .java | javac + java |
| Go | .go | go run |
| PHP | .php | php |
| Rust | .rs | rustc + run |

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+S | Save file |
| Ctrl+Enter | Run code |
| Ctrl+` | Toggle terminal |
| Ctrl+B | Toggle AI panel |

## Security

- Password hashing (Werkzeug/bcrypt)
- Session-based authentication
- Path traversal prevention
- User workspace isolation
- Execution timeout (30s)
- Output size limits (1MB)

---

Built with YubiLab by Devopod Private Limited.
