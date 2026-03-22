// ============================================
// YubiLab Editor - Main Module
// ============================================

const API_BASE = window.location.origin;
// Socket.IO connects through same origin when behind reverse proxy (nginx/proxy on 8080/8888)
// Falls back to port 3001 when accessed directly on port 5000
const NODE_ENGINE_URL = (window.location.port === '5000') ? window.location.protocol + '//' + window.location.hostname + ':3001' : window.location.origin;

// State
let projectId = null;
let projectData = null;
let monacoEditor = null;
let openTabs = [];        // [{path, name, content, modified}]
let activeTabIndex = -1;
let fileTree = [];
let socket = null;
let terminal = null;
let fitAddon = null;
let aiAction = 'generate';
let contextMenuTarget = null;
let dialogCallback = null;
let bottomPanelVisible = true;

// Language mappings for Monaco
const LANG_MAP = {
    'py': 'python', 'js': 'javascript', 'ts': 'typescript', 'jsx': 'javascript',
    'tsx': 'typescript', 'html': 'html', 'htm': 'html', 'css': 'css',
    'json': 'json', 'md': 'markdown', 'c': 'c', 'cpp': 'cpp', 'h': 'c',
    'hpp': 'cpp', 'java': 'java', 'go': 'go', 'rs': 'rust', 'php': 'php',
    'rb': 'ruby', 'sh': 'shell', 'bash': 'shell', 'yml': 'yaml', 'yaml': 'yaml',
    'xml': 'xml', 'sql': 'sql', 'txt': 'plaintext', 'toml': 'plaintext',
    'cfg': 'plaintext', 'ini': 'ini', 'dockerfile': 'dockerfile',
};

// File type icons
const FILE_ICONS = {
    'py': '🐍', 'js': '🟨', 'ts': '🔷', 'html': '🌐', 'htm': '🌐',
    'css': '🎨', 'json': '📋', 'md': '📝', 'c': '⚙️', 'cpp': '⚙️',
    'java': '☕', 'go': '🐹', 'rs': '🦀', 'php': '🐘', 'rb': '💎',
    'sh': '📜', 'yml': '⚙️', 'yaml': '⚙️', 'xml': '📄', 'sql': '🗄️',
    'txt': '📄', 'toml': '⚙️', 'gitignore': '📁',
};

// ============================================
// INITIALIZATION
// ============================================

(async function init() {
    // Check auth
    try {
        const res = await fetch(`${API_BASE}/api/auth/me`, { credentials: 'include' });
        if (!res.ok) { window.location.href = '/login'; return; }
    } catch (e) { window.location.href = '/login'; return; }

    // Get project ID from URL
    const params = new URLSearchParams(window.location.search);
    projectId = parseInt(params.get('project'));
    if (!projectId) { window.location.href = '/'; return; }

    // Load project
    await loadProject();

    // Initialize Monaco
    initMonaco();

    // Initialize Socket.IO
    initSocket();

    // Initialize Terminal
    initTerminal();

    // Load saved AI conversations
    loadConversations();

    // Setup keyboard shortcuts
    setupShortcuts();

    // Setup resize handle
    setupResize();

    // Hide context menu on click
    document.addEventListener('click', () => {
        document.getElementById('context-menu').style.display = 'none';
    });
})();

async function loadProject() {
    try {
        const res = await fetch(`${API_BASE}/api/projects`, { credentials: 'include' });
        const data = await res.json();
        projectData = (data.projects || []).find(p => p.id === projectId);
        if (!projectData) { window.location.href = '/'; return; }

        document.getElementById('project-name').textContent = projectData.name;
        document.getElementById('project-lang-badge').textContent = projectData.language;
        document.title = `${projectData.name} - YubiLab`;

        // Show preview button for HTML projects
        if (projectData.language === 'html') {
            document.getElementById('preview-btn').style.display = '';
        }

        // Show deploy button for all projects
        const deployBtn = document.querySelector('[onclick="deployProject()"]');
        if (deployBtn) deployBtn.style.display = '';

        await refreshFiles();
    } catch (e) {
        showToast('Failed to load project', 'error');
    }
}

// ============================================
// MONACO EDITOR
// ============================================

function initMonaco() {
    monaco.editor.defineTheme('yubilab-dark', {
        base: 'vs-dark',
        inherit: true,
        rules: [
            { token: 'comment', foreground: '6a9955' },
            { token: 'keyword', foreground: 'c586c0' },
            { token: 'string', foreground: 'ce9178' },
            { token: 'number', foreground: 'b5cea8' },
            { token: 'type', foreground: '4ec9b0' },
        ],
        colors: {
            'editor.background': '#0d1117',
            'editor.foreground': '#e6edf3',
            'editor.lineHighlightBackground': '#161b2255',
            'editor.selectionBackground': '#388bfd44',
            'editorCursor.foreground': '#58a6ff',
            'editorLineNumber.foreground': '#6e7681',
            'editorLineNumber.activeForeground': '#e6edf3',
            'editor.inactiveSelectionBackground': '#388bfd22',
        }
    });

    monacoEditor = monaco.editor.create(document.getElementById('monaco-editor'), {
        value: '',
        language: 'plaintext',
        theme: 'yubilab-dark',
        automaticLayout: true,
        fontSize: 14,
        fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
        fontLigatures: true,
        minimap: { enabled: true, maxColumn: 80 },
        scrollBeyondLastLine: false,
        renderWhitespace: 'selection',
        tabSize: 4,
        insertSpaces: true,
        wordWrap: 'off',
        lineNumbers: 'on',
        glyphMargin: false,
        folding: true,
        bracketPairColorization: { enabled: true },
        suggest: { showMethods: true, showFunctions: true, showConstructors: true },
        padding: { top: 8 },
        smoothScrolling: true,
        cursorSmoothCaretAnimation: 'on',
        cursorBlinking: 'smooth',
    });

    // Track cursor position
    monacoEditor.onDidChangeCursorPosition((e) => {
        document.getElementById('status-pos').textContent = `Ln ${e.position.lineNumber}, Col ${e.position.column}`;
    });

    // Track content changes
    monacoEditor.onDidChangeModelContent(() => {
        if (activeTabIndex >= 0 && openTabs[activeTabIndex]) {
            openTabs[activeTabIndex].modified = true;
            renderTabs();
            // Auto-save after 2 seconds of inactivity
            clearTimeout(openTabs[activeTabIndex]._saveTimer);
            openTabs[activeTabIndex]._saveTimer = setTimeout(() => {
                autoSave(activeTabIndex);
            }, 2000);
        }
    });

    // Ctrl+S save
    monacoEditor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
        saveCurrentFile();
    });

    // Ctrl+Enter run
    monacoEditor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
        runCode();
    });
}

function getLanguageForFile(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    return LANG_MAP[ext] || 'plaintext';
}

function getIconForFile(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    return FILE_ICONS[ext] || '📄';
}

// ============================================
// FILE EXPLORER
// ============================================

async function refreshFiles() {
    try {
        const res = await fetch(`${API_BASE}/api/projects/${projectId}/files`, { credentials: 'include' });
        const data = await res.json();
        fileTree = data.files || [];
        renderFileTree();
    } catch (e) {
        showToast('Failed to load files', 'error');
    }
}

function renderFileTree() {
    const container = document.getElementById('file-tree');
    container.innerHTML = renderTreeItems(fileTree, 0);
}

function renderTreeItems(items, depth) {
    let html = '';
    for (const item of items) {
        const indent = depth * 16;
        if (item.type === 'directory') {
            html += `
                <div class="file-item file-item-dir" style="padding-left:${12 + indent}px"
                     onclick="toggleDir(this, '${escapeAttr(item.path)}')"
                     oncontextmenu="showContextMenu(event, '${escapeAttr(item.path)}', 'directory')">
                    <span class="dir-toggle">▶</span>
                    <span class="file-icon">📁</span>
                    <span class="file-name">${escapeHtml(item.name)}</span>
                </div>
                <div class="file-children" data-path="${escapeAttr(item.path)}">
                    ${item.children ? renderTreeItems(item.children, depth + 1) : ''}
                </div>`;
        } else {
            const icon = getIconForFile(item.name);
            const isActive = openTabs[activeTabIndex]?.path === item.path;
            html += `
                <div class="file-item ${isActive ? 'active' : ''}" style="padding-left:${12 + indent + 16}px"
                     onclick="openFile('${escapeAttr(item.path)}', '${escapeAttr(item.name)}')"
                     oncontextmenu="showContextMenu(event, '${escapeAttr(item.path)}', 'file')">
                    <span class="file-icon">${icon}</span>
                    <span class="file-name">${escapeHtml(item.name)}</span>
                </div>`;
        }
    }
    return html;
}

function toggleDir(el, path) {
    const children = document.querySelector(`.file-children[data-path="${CSS.escape(path)}"]`);
    const toggle = el.querySelector('.dir-toggle');
    if (children) {
        children.classList.toggle('open');
        toggle.classList.toggle('open');
        // Change folder icon
        const icon = el.querySelector('.file-icon');
        icon.textContent = children.classList.contains('open') ? '📂' : '📁';
    }
}

async function openFile(path, name) {
    // Check if already open
    const existingIndex = openTabs.findIndex(t => t.path === path);
    if (existingIndex >= 0) {
        switchToTab(existingIndex);
        return;
    }

    // Load file content
    try {
        setStatus('Loading...');
        const res = await fetch(`${API_BASE}/api/projects/${projectId}/files/content?path=${encodeURIComponent(path)}`, {
            credentials: 'include'
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error);

        const tab = { path, name, content: data.content, modified: false, _saveTimer: null };
        openTabs.push(tab);
        switchToTab(openTabs.length - 1);
        setStatus('Ready');
    } catch (e) {
        showToast(`Failed to open ${name}: ${e.message}`, 'error');
        setStatus('Error');
    }
}

// ============================================
// TABS
// ============================================

function renderTabs() {
    const tabsEl = document.getElementById('editor-tabs');
    tabsEl.innerHTML = openTabs.map((tab, i) => `
        <div class="editor-tab ${i === activeTabIndex ? 'active' : ''} ${tab.modified ? 'modified' : ''}"
             onclick="switchToTab(${i})" title="${escapeAttr(tab.path)}">
            <span>${getIconForFile(tab.name)} ${escapeHtml(tab.name)}</span>
            <span class="tab-modified"></span>
            <span class="tab-close" onclick="event.stopPropagation(); closeTab(${i})">✕</span>
        </div>
    `).join('');
}

function switchToTab(index) {
    if (index < 0 || index >= openTabs.length) return;

    // Save current editor content to the old tab
    if (activeTabIndex >= 0 && openTabs[activeTabIndex] && monacoEditor) {
        openTabs[activeTabIndex].content = monacoEditor.getValue();
    }

    activeTabIndex = index;
    const tab = openTabs[index];

    // Show editor, hide empty state
    document.getElementById('editor-empty').style.display = 'none';
    document.getElementById('monaco-editor').style.display = 'block';

    // Set editor content and language
    const lang = getLanguageForFile(tab.name);
    const model = monaco.editor.createModel(tab.content, lang);
    monacoEditor.setModel(model);

    // Update status bar
    document.getElementById('status-file').textContent = tab.path;
    document.getElementById('status-lang').textContent = lang;

    renderTabs();
    renderFileTree(); // Update active state
}

function closeTab(index) {
    const tab = openTabs[index];
    if (tab.modified) {
        if (!confirm(`Save changes to ${tab.name} before closing?`)) {
            // Don't save, just close
        } else {
            saveFile(index);
        }
    }

    openTabs.splice(index, 1);
    if (openTabs.length === 0) {
        activeTabIndex = -1;
        document.getElementById('editor-empty').style.display = 'flex';
        document.getElementById('monaco-editor').style.display = 'none';
        document.getElementById('status-file').textContent = '';
        document.getElementById('status-lang').textContent = '-';
    } else if (index <= activeTabIndex) {
        activeTabIndex = Math.max(0, activeTabIndex - 1);
        switchToTab(activeTabIndex);
    }

    renderTabs();
}

// ============================================
// FILE OPERATIONS
// ============================================

async function saveFile(index) {
    const tab = openTabs[index];
    if (!tab) return;

    if (monacoEditor && index === activeTabIndex) {
        tab.content = monacoEditor.getValue();
    }

    try {
        const res = await fetch(`${API_BASE}/api/projects/${projectId}/files/save`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ path: tab.path, content: tab.content })
        });

        if (res.ok) {
            tab.modified = false;
            renderTabs();
            setStatus('Saved');
            return true;
        } else {
            const data = await res.json();
            showToast(data.error || 'Save failed', 'error');
            return false;
        }
    } catch (e) {
        showToast('Save failed: ' + e.message, 'error');
        return false;
    }
}

function saveCurrentFile() {
    if (activeTabIndex >= 0) {
        saveFile(activeTabIndex);
    }
}

async function autoSave(index) {
    if (openTabs[index] && openTabs[index].modified) {
        await saveFile(index);
    }
}

function createNewFile() {
    showInputDialog('New File', 'Enter file name:', '', (name) => {
        if (!name) return;
        createFileOrFolder(name, 'file');
    });
}

function createNewFolder() {
    showInputDialog('New Folder', 'Enter folder name:', '', (name) => {
        if (!name) return;
        createFileOrFolder(name, 'directory');
    });
}

async function createFileOrFolder(path, type) {
    try {
        const res = await fetch(`${API_BASE}/api/projects/${projectId}/files/create`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ path, type })
        });

        const data = await res.json();
        if (res.ok) {
            showToast(`${type === 'directory' ? 'Folder' : 'File'} created`, 'success');
            await refreshFiles();
            if (type === 'file') {
                openFile(path, path.split('/').pop());
            }
        } else {
            showToast(data.error || 'Failed to create', 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function deleteFileOrFolder(path) {
    if (!confirm(`Delete "${path}"? This cannot be undone.`)) return;

    try {
        const res = await fetch(`${API_BASE}/api/projects/${projectId}/files/delete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ path })
        });

        if (res.ok) {
            showToast('Deleted', 'success');
            // Close tab if open
            const tabIndex = openTabs.findIndex(t => t.path === path || t.path.startsWith(path + '/'));
            if (tabIndex >= 0) closeTab(tabIndex);
            await refreshFiles();
        } else {
            const data = await res.json();
            showToast(data.error || 'Delete failed', 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function renameFileOrFolder(oldPath) {
    const oldName = oldPath.split('/').pop();
    showInputDialog('Rename', 'Enter new name:', oldName, async (newName) => {
        if (!newName || newName === oldName) return;

        const dir = oldPath.includes('/') ? oldPath.substring(0, oldPath.lastIndexOf('/') + 1) : '';
        const newPath = dir + newName;

        try {
            const res = await fetch(`${API_BASE}/api/projects/${projectId}/files/rename`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ old_path: oldPath, new_path: newPath })
            });

            if (res.ok) {
                showToast('Renamed', 'success');
                // Update tab if open
                const tab = openTabs.find(t => t.path === oldPath);
                if (tab) {
                    tab.path = newPath;
                    tab.name = newName;
                    renderTabs();
                }
                await refreshFiles();
            } else {
                const data = await res.json();
                showToast(data.error || 'Rename failed', 'error');
            }
        } catch (e) {
            showToast('Error: ' + e.message, 'error');
        }
    });
}

// ============================================
// CONTEXT MENU
// ============================================

function showContextMenu(event, path, type) {
    event.preventDefault();
    event.stopPropagation();
    contextMenuTarget = { path, type };

    const menu = document.getElementById('context-menu');
    menu.style.display = 'block';
    menu.style.left = event.pageX + 'px';
    menu.style.top = event.pageY + 'px';
}

function contextAction(action) {
    if (!contextMenuTarget) return;
    const { path, type } = contextMenuTarget;

    switch (action) {
        case 'rename':
            renameFileOrFolder(path);
            break;
        case 'delete':
            deleteFileOrFolder(path);
            break;
        case 'newfile': {
            const dir = type === 'directory' ? path + '/' : (path.includes('/') ? path.substring(0, path.lastIndexOf('/') + 1) : '');
            showInputDialog('New File', 'Enter file name:', '', (name) => {
                if (name) createFileOrFolder(dir + name, 'file');
            });
            break;
        }
        case 'newfolder': {
            const dir2 = type === 'directory' ? path + '/' : (path.includes('/') ? path.substring(0, path.lastIndexOf('/') + 1) : '');
            showInputDialog('New Folder', 'Enter folder name:', '', (name) => {
                if (name) createFileOrFolder(dir2 + name, 'directory');
            });
            break;
        }
    }

    document.getElementById('context-menu').style.display = 'none';
}

// ============================================
// SOCKET.IO + TERMINAL
// ============================================

function initSocket() {
    socket = io(NODE_ENGINE_URL, {
        transports: ['websocket', 'polling'],
        reconnection: true,
        reconnectionAttempts: 10,
        reconnectionDelay: 1000,
    });

    socket.on('connect', () => {
        console.log('Socket connected');
        setStatus('Connected');
        startTerminal();
    });

    socket.on('disconnect', () => {
        console.log('Socket disconnected');
        setStatus('Disconnected');
    });

    socket.on('connect_error', (err) => {
        console.warn('Socket connection error:', err.message);
        setStatus('Connection error');
    });

    // Code execution output
    socket.on('code:output', (data) => {
        appendConsole(data.data, data.type);
    });

    socket.on('code:done', (data) => {
        const status = data.exitCode === 0 ? 'success' : 'error';
        const msg = data.exitCode === 0
            ? `\n✓ Process exited with code 0 (${data.duration}ms)\n`
            : `\n✗ Process exited with code ${data.exitCode} (${data.duration || 0}ms)\n`;
        appendConsole(msg, status === 'success' ? 'success' : 'stderr');
        setStatus('Ready');
    });
}

function initTerminal() {
    terminal = new Terminal({
        cursorBlink: true,
        fontSize: 14,
        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
        theme: {
            background: '#0d1117',
            foreground: '#e6edf3',
            cursor: '#58a6ff',
            cursorAccent: '#0d1117',
            selectionBackground: '#388bfd44',
            black: '#0d1117',
            red: '#f85149',
            green: '#3fb950',
            yellow: '#d29922',
            blue: '#58a6ff',
            magenta: '#bc8cff',
            cyan: '#39d2c0',
            white: '#e6edf3',
            brightBlack: '#6e7681',
            brightRed: '#f85149',
            brightGreen: '#3fb950',
            brightYellow: '#d29922',
            brightBlue: '#58a6ff',
            brightMagenta: '#bc8cff',
            brightCyan: '#39d2c0',
            brightWhite: '#ffffff',
        },
        allowProposedApi: true,
    });

    fitAddon = new FitAddon.FitAddon();
    terminal.loadAddon(fitAddon);

    const webLinksAddon = new WebLinksAddon.WebLinksAddon();
    terminal.loadAddon(webLinksAddon);

    const container = document.getElementById('terminal-container');
    terminal.open(container);

    // Fit terminal to container
    setTimeout(() => fitAddon.fit(), 100);

    // Terminal input -> socket
    terminal.onData((data) => {
        if (socket && socket.connected) {
            socket.emit('terminal:input', data);
        }
    });

    // Terminal output <- socket
    if (socket) {
        socket.on('terminal:output', (data) => {
            terminal.write(data);
        });

        socket.on('terminal:ready', (data) => {
            console.log('Terminal ready, PID:', data.pid);
        });

        socket.on('terminal:exit', (data) => {
            terminal.writeln(`\r\n[Process exited with code ${data.exitCode}]`);
            // Restart terminal after short delay
            setTimeout(startTerminal, 1000);
        });

        socket.on('terminal:error', (data) => {
            terminal.writeln(`\r\n[Terminal error: ${data.error}]`);
        });
    }

    // Resize observer
    const resizeObserver = new ResizeObserver(() => {
        if (fitAddon) {
            try {
                fitAddon.fit();
                if (socket && socket.connected && terminal) {
                    socket.emit('terminal:resize', { cols: terminal.cols, rows: terminal.rows });
                }
            } catch (e) {}
        }
    });
    resizeObserver.observe(container);
}

async function startTerminal() {
    if (!socket || !socket.connected) return;

    // Fetch actual workspace path from Flask API
    let projectPath = null;
    try {
        const res = await fetch(`${API_BASE}/api/projects/${projectId}/workspace_path`, { credentials: 'include' });
        if (res.ok) {
            const data = await res.json();
            projectPath = data.path;
        }
    } catch (e) {
        console.warn('Could not fetch workspace path:', e);
    }

    socket.emit('terminal:start', {
        projectPath: projectPath,
        cols: terminal ? terminal.cols : 80,
        rows: terminal ? terminal.rows : 24,
    });
}

// ============================================
// CODE EXECUTION
// ============================================

function runCode() {
    if (activeTabIndex < 0 || !openTabs[activeTabIndex]) {
        showToast('No file open to run', 'error');
        return;
    }

    // Save first
    if (monacoEditor) {
        openTabs[activeTabIndex].content = monacoEditor.getValue();
    }
    saveFile(activeTabIndex);

    const tab = openTabs[activeTabIndex];
    const code = tab.content;
    const ext = tab.name.split('.').pop().toLowerCase();

    // Map extension to language
    const langMap = {
        'py': 'python', 'js': 'javascript', 'c': 'c', 'cpp': 'cpp',
        'java': 'java', 'go': 'go', 'php': 'php', 'rs': 'rust',
    };
    const language = langMap[ext];

    if (!language) {
        // For HTML files, show preview
        if (ext === 'html' || ext === 'htm') {
            showPreview();
            return;
        }
        showToast('Cannot run this file type', 'error');
        return;
    }

    // Clear console and switch to it
    clearConsole();
    switchBottomTab('console');

    setStatus('Running...');

    if (socket && socket.connected) {
        socket.emit('code:run-stream', {
            code,
            language,
            projectPath: null, // Run in temp dir
        });
    } else {
        // Fallback to REST API
        fetch(`${NODE_ENGINE_URL}/execute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code, language })
        })
        .then(r => r.json())
        .then(data => {
            if (data.stdout) appendConsole(data.stdout, 'stdout');
            if (data.stderr) appendConsole(data.stderr, 'stderr');
            appendConsole(`\nExited with code ${data.exitCode} (${data.duration}ms)\n`,
                data.exitCode === 0 ? 'success' : 'stderr');
            setStatus('Ready');
        })
        .catch(e => {
            appendConsole('Execution error: ' + e.message + '\n', 'stderr');
            setStatus('Error');
        });
    }
}

// ============================================
// CONSOLE
// ============================================

function appendConsole(text, type = 'stdout') {
    const console_el = document.getElementById('console-output');
    const line = document.createElement('div');
    line.className = `console-line console-${type}`;
    line.textContent = text;
    console_el.appendChild(line);
    console_el.scrollTop = console_el.scrollHeight;
}

function clearConsole() {
    document.getElementById('console-output').innerHTML = '';
}

// ============================================
// HTML PREVIEW
// ============================================

function showPreview() {
    switchBottomTab('preview');
    updatePreview();
}

function updatePreview() {
    const frame = document.getElementById('preview-frame');
    // Find index.html in project
    frame.src = `${API_BASE}/preview/${projectId}/index.html?t=${Date.now()}`;
}

function togglePreview() {
    const previewPane = document.getElementById('preview-pane');
    if (previewPane.classList.contains('active')) {
        switchBottomTab('terminal');
    } else {
        showPreview();
    }
}

// ============================================
// BOTTOM PANEL
// ============================================

function switchBottomTab(panel) {
    document.querySelectorAll('.bottom-tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`.bottom-tab[data-panel="${panel}"]`).classList.add('active');

    document.querySelectorAll('.panel-pane').forEach(p => p.classList.remove('active'));
    document.getElementById(`${panel}-pane`).classList.add('active');

    if (panel === 'terminal' && fitAddon) {
        setTimeout(() => fitAddon.fit(), 50);
    }
    if (panel === 'preview') {
        updatePreview();
    }
}

function toggleBottomPanel() {
    const panel = document.getElementById('bottom-panel');
    bottomPanelVisible = !bottomPanelVisible;
    panel.style.display = bottomPanelVisible ? 'flex' : 'none';
    if (bottomPanelVisible && fitAddon) {
        setTimeout(() => fitAddon.fit(), 50);
    }
}

// ============================================
// AI PANEL
// ============================================

function toggleAI() {
    const panel = document.getElementById('ai-panel');
    panel.classList.toggle('open');
}

function setAIAction(action) {
    aiAction = action;
    document.querySelectorAll('.ai-action-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.action === action);
    });

    const placeholder = {
        generate: 'Describe what code to generate...',
        debug: 'Paste code or describe the bug...',
        explain: 'Paste code or ask a question...',
        agent: 'Tell the AI agent what to build...',
    };
    document.getElementById('ai-input').placeholder = placeholder[action] || 'Ask YubiAI...';
}

async function loadConversations() {
    try {
        const res = await fetch(`${API_BASE}/api/ai/conversations/${projectId}`, { credentials: 'include' });
        if (!res.ok) return;
        const messages = await res.json();
        const messagesDiv = document.getElementById('ai-messages');
        messages.forEach(m => {
            const el = document.createElement('div');
            el.className = `ai-message ${m.role}`;
            if (m.msg_type === 'agent-result') {
                el.className += ' agent-result';
                el.innerHTML = m.content;
            } else {
                el.textContent = m.content;
            }
            messagesDiv.appendChild(el);
        });
        if (messages.length > 0) {
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        }
    } catch (e) {
        console.warn('Could not load conversations:', e);
    }
}

function saveConversation(role, content, msgType) {
    fetch(`${API_BASE}/api/ai/conversations/${projectId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ role, content, msg_type: msgType || 'text' }),
    }).catch(() => {});
}

async function sendAIMessage() {
    const input = document.getElementById('ai-input');
    const prompt = input.value.trim();
    if (!prompt) return;

    // Add user message
    addAIMessage(prompt, 'user');
    saveConversation('user', prompt);
    input.value = '';

    // Get code context
    let codeContext = '';
    if (monacoEditor && activeTabIndex >= 0) {
        const selection = monacoEditor.getModel().getValueInRange(monacoEditor.getSelection());
        codeContext = selection || monacoEditor.getValue();
    }

    // Show animated progress for agent, simple loading for others
    let progressEl = null;
    if (aiAction === 'agent') {
        progressEl = addAgentProgress();
    } else {
        progressEl = addAIMessage('Thinking...', 'system');
    }

    try {
        let endpoint, body;

        if (aiAction === 'agent') {
            endpoint = '/api/ai/agent';
            body = { prompt, project_id: projectId };
            updateAgentStep(progressEl, 1); // Analyzing
        } else {
            endpoint = '/api/ai/generate';
            body = {
                prompt,
                code_context: codeContext,
                language: projectData.language,
                action: aiAction,
            };
        }

        if (aiAction === 'agent') {
            // Simulate step progress while waiting
            setTimeout(() => updateAgentStep(progressEl, 2), 3000); // Generating
            setTimeout(() => updateAgentStep(progressEl, 3), 8000); // Creating files
        }

        const res = await fetch(`${API_BASE}${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify(body),
        });

        const data = await res.json();

        if (aiAction === 'agent') {
            updateAgentStep(progressEl, 4); // Finishing
            await new Promise(r => setTimeout(r, 500));
        }
        progressEl.remove();

        if (aiAction === 'agent' && data.agent_executed) {
            // Agent executed - show rich results
            const resultEl = document.createElement('div');
            resultEl.className = 'ai-message assistant agent-result';
            let html = `<div class="agent-result-header">Agent Completed</div>`;
            html += `<div class="agent-plan">${escapeHtml(data.plan)}</div>`;
            if (data.files && data.files.length > 0) {
                html += `<div class="agent-files-header">Files created/modified:</div>`;
                html += `<div class="agent-files-list">`;
                data.files.forEach(f => {
                    const icon = f.action === 'deleted' ? '&#128465;' : (f.action === 'modify' ? '&#9997;' : '&#128196;');
                    html += `<div class="agent-file-item"><span class="agent-file-icon">${icon}</span><span class="agent-file-path">${escapeHtml(f.path)}</span><span class="agent-file-action">${f.action}</span></div>`;
                });
                html += `</div>`;
            }
            if (data.run_command) {
                html += `<div class="agent-run-cmd"><span>Run:</span> <code>${escapeHtml(data.run_command)}</code></div>`;
            }
            html += `<div class="agent-message">${escapeHtml(data.message)}</div>`;
            if (data.errors && data.errors.length > 0) {
                html += `<div class="agent-errors">Errors: ${data.errors.map(escapeHtml).join(', ')}</div>`;
            }
            resultEl.innerHTML = html;
            document.getElementById('ai-messages').appendChild(resultEl);
            document.getElementById('ai-messages').scrollTop = document.getElementById('ai-messages').scrollHeight;

            // Save agent result to conversations
            saveConversation('assistant', resultEl.innerHTML, 'agent-result');

            // Refresh file tree
            await refreshFiles();
            showToast('Agent completed! Files created.', 'success');
        } else if (data.response) {
            addAIMessage(data.response, 'assistant');
            saveConversation('assistant', data.response);

            // If generating code, offer to insert it
            if (aiAction === 'generate' || aiAction === 'debug' || aiAction === 'complete') {
                const insertBtn = document.createElement('button');
                insertBtn.className = 'ai-action-btn';
                insertBtn.textContent = 'Insert into editor';
                insertBtn.style.marginTop = '8px';
                insertBtn.onclick = () => {
                    if (monacoEditor && activeTabIndex >= 0) {
                        let code = data.response;
                        const codeBlockMatch = code.match(/```[\w]*\n([\s\S]*?)```/);
                        if (codeBlockMatch) code = codeBlockMatch[1];
                        monacoEditor.setValue(code);
                        showToast('Code inserted', 'success');
                    }
                };
                const messagesDiv = document.getElementById('ai-messages');
                messagesDiv.lastElementChild.appendChild(insertBtn);
            }
        } else if (data.error) {
            addAIMessage(`Error: ${data.error}`, 'system error');
            saveConversation('system', `Error: ${data.error}`);
        }
    } catch (e) {
        progressEl.remove();
        addAIMessage(`Error: ${e.message}`, 'system error');
        saveConversation('system', `Error: ${e.message}`);
    }
}

function addAgentProgress() {
    const messagesDiv = document.getElementById('ai-messages');
    const el = document.createElement('div');
    el.className = 'ai-message system agent-progress';
    el.innerHTML = `
        <div class="agent-progress-title">YubiAI Agent Working...</div>
        <div class="agent-steps">
            <div class="agent-step active" data-step="1"><span class="step-icon spinner">&#9881;</span> Analyzing your request...</div>
            <div class="agent-step" data-step="2"><span class="step-icon">&#128296;</span> Generating code &amp; structure...</div>
            <div class="agent-step" data-step="3"><span class="step-icon">&#128193;</span> Creating files &amp; folders...</div>
            <div class="agent-step" data-step="4"><span class="step-icon">&#9989;</span> Finishing up...</div>
        </div>
    `;
    messagesDiv.appendChild(el);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    return el;
}

function updateAgentStep(el, step) {
    if (!el || !el.parentNode) return;
    el.querySelectorAll('.agent-step').forEach(s => {
        const n = parseInt(s.dataset.step);
        if (n < step) { s.classList.add('done'); s.classList.remove('active'); }
        else if (n === step) { s.classList.add('active'); s.classList.remove('done'); }
        else { s.classList.remove('active', 'done'); }
    });
    const messagesDiv = document.getElementById('ai-messages');
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

async function clearAIChat() {
    if (!confirm('Clear all AI conversation history for this project?')) return;
    document.getElementById('ai-messages').innerHTML = '<div class="ai-message system">YubiAI is ready. Ask me to generate code, debug, explain, or build your entire project!</div>';
    try {
        await fetch(`${API_BASE}/api/ai/conversations/${projectId}`, { method: 'DELETE', credentials: 'include' });
        showToast('Chat cleared', 'success');
    } catch (e) {}
}

function addAIMessage(text, type) {
    const messagesDiv = document.getElementById('ai-messages');
    const msg = document.createElement('div');
    msg.className = `ai-message ${type}`;
    msg.textContent = text;
    messagesDiv.appendChild(msg);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    return msg;
}

// ============================================
// DEPLOY
// ============================================

async function deployProject() {
    if (!projectData) return;

    // Save all open files first
    for (let i = 0; i < openTabs.length; i++) {
        if (openTabs[i].modified) await saveFile(i);
    }

    // For HTML projects, just show preview
    if (projectData.language === 'html') {
        showToast('Opening preview...', 'info');
        showPreview();
        return;
    }

    // For all other projects, use deploy API
    showToast('Deploying project...', 'info');
    setStatus('Deploying...');

    try {
        const res = await fetch(`${API_BASE}/api/deploy/${projectId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({}),
        });
        const data = await res.json();

        if (res.ok) {
            showToast(`Deployed on port ${data.port}!`, 'success');
            setStatus(`Deployed (port ${data.port})`);

            // Show deploy info in console
            clearConsole();
            switchBottomTab('console');
            appendConsole(`=== Project Deployed ===\n`, 'success');
            appendConsole(`Port: ${data.port}\n`, 'info');
            appendConsole(`Command: ${data.command}\n`, 'info');
            appendConsole(`URL: ${window.location.origin}${data.url}\n`, 'info');
            appendConsole(`\nOpening preview...\n`, 'info');

            // Wait a bit for the server to start, then show preview
            setTimeout(() => {
                const frame = document.getElementById('preview-frame');
                frame.src = `${API_BASE}${data.url}?t=${Date.now()}`;
                switchBottomTab('preview');
            }, 2000);
        } else {
            showToast(data.error || 'Deploy failed', 'error');
            setStatus('Deploy failed');
        }
    } catch (e) {
        showToast('Deploy error: ' + e.message, 'error');
        setStatus('Error');
    }
}

async function stopDeployment() {
    try {
        const res = await fetch(`${API_BASE}/api/deploy/${projectId}`, {
            method: 'DELETE',
            credentials: 'include',
        });
        const data = await res.json();
        if (res.ok) {
            showToast('Deployment stopped', 'success');
            setStatus('Ready');
        } else {
            showToast(data.error || 'Failed to stop', 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

// ============================================
// UTILITIES
// ============================================

function goBack() {
    // Save any modified files
    openTabs.forEach((tab, i) => {
        if (tab.modified) saveFile(i);
    });
    window.location.href = '/';
}

function setStatus(text) {
    document.getElementById('status-text').textContent = text;
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function escapeAttr(text) {
    return text.replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

// ============================================
// INPUT DIALOG
// ============================================

function showInputDialog(title, placeholder, defaultValue, callback) {
    const dialog = document.getElementById('input-dialog');
    document.getElementById('dialog-title').textContent = title;
    const input = document.getElementById('dialog-input');
    input.placeholder = placeholder;
    input.value = defaultValue || '';
    dialogCallback = callback;
    dialog.classList.add('active');
    setTimeout(() => input.focus(), 50);
}

function confirmDialog() {
    const value = document.getElementById('dialog-input').value.trim();
    document.getElementById('input-dialog').classList.remove('active');
    if (dialogCallback) dialogCallback(value);
    dialogCallback = null;
}

function cancelDialog() {
    document.getElementById('input-dialog').classList.remove('active');
    dialogCallback = null;
}

// Dialog keyboard handling
document.getElementById('dialog-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') confirmDialog();
    if (e.key === 'Escape') cancelDialog();
});

// ============================================
// KEYBOARD SHORTCUTS
// ============================================

function setupShortcuts() {
    document.addEventListener('keydown', (e) => {
        // Ctrl+S - Save
        if ((e.ctrlKey || e.metaKey) && e.key === 's') {
            e.preventDefault();
            saveCurrentFile();
        }
        // Ctrl+Enter - Run
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            runCode();
        }
        // Ctrl+` - Toggle terminal
        if ((e.ctrlKey || e.metaKey) && e.key === '`') {
            e.preventDefault();
            toggleBottomPanel();
        }
        // Ctrl+B - Toggle AI
        if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
            e.preventDefault();
            toggleAI();
        }
        // Escape - Close dialogs
        if (e.key === 'Escape') {
            cancelDialog();
            document.getElementById('context-menu').style.display = 'none';
        }
    });
}

// ============================================
// RESIZE HANDLE
// ============================================

function setupResize() {
    const handle = document.getElementById('resize-handle');
    const panel = document.getElementById('bottom-panel');
    let startY, startHeight;

    handle.addEventListener('mousedown', (e) => {
        startY = e.clientY;
        startHeight = panel.offsetHeight;

        const onMouseMove = (e) => {
            const diff = startY - e.clientY;
            const newHeight = Math.max(120, Math.min(600, startHeight + diff));
            panel.style.height = newHeight + 'px';
            if (fitAddon) fitAddon.fit();
        };

        const onMouseUp = () => {
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
        };

        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    });
}
