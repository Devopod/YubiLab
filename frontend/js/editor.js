// ============================================
// YubiLab Editor - Main Module
// ============================================

// Use relative URLs to avoid issues with basic-auth tunnel proxies
// Socket.IO connects through same origin when behind reverse proxy (nginx/proxy on 8080/8888)
// Falls back to port 3001 when accessed directly on port 5000
const NODE_ENGINE_URL = (window.location.port === '5000') ? window.location.protocol + '//' + window.location.hostname + ':3001' : window.location.protocol + '//' + window.location.host;

// State
let projectId = null;
let currentProjectId = null; // alias for tools.js
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
    'dart': 'dart', 'swift': 'swift', 'kt': 'kotlin', 'kts': 'kotlin',
    'gradle': 'groovy', 'groovy': 'groovy', 'scala': 'scala',
};

// File type icons
const FILE_ICONS = {
    'py': '🐍', 'js': '🟨', 'ts': '🔷', 'html': '🌐', 'htm': '🌐',
    'css': '🎨', 'json': '📋', 'md': '📝', 'c': '⚙️', 'cpp': '⚙️',
    'java': '☕', 'go': '🐹', 'rs': '🦀', 'php': '🐘', 'rb': '💎',
    'sh': '📜', 'yml': '⚙️', 'yaml': '⚙️', 'xml': '📄', 'sql': '🗄️',
    'txt': '📄', 'toml': '⚙️', 'gitignore': '📁',
    'dart': '🎯', 'swift': '🍎', 'kt': '🟣', 'kts': '🟣',
    'gradle': '🐘', 'scala': '🔴',
};

// ============================================
// INITIALIZATION
// ============================================

(async function init() {
    // Check auth
    try {
        const res = await apiFetch(`/api/auth/me`);
        if (!res.ok) { window.location.href = '/login'; return; }
    } catch (e) { window.location.href = '/login'; return; }

    // Get project ID from URL
    const params = new URLSearchParams(window.location.search);
    projectId = parseInt(params.get('project'));
    currentProjectId = projectId;
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
        const res = await apiFetch(`/api/projects`);
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

        // Check if Flutter project — show Build button
        checkFlutterStatus();
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
        const res = await apiFetch(`/api/projects/${projectId}/files`);
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
        const res = await apiFetch(`/api/projects/${projectId}/files/content?path=${encodeURIComponent(path)}`);
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
        const res = await apiFetch(`/api/projects/${projectId}/files/save`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
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
        const res = await apiFetch(`/api/projects/${projectId}/files/create`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
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
        const res = await apiFetch(`/api/projects/${projectId}/files/delete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
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
            const res = await apiFetch(`/api/projects/${projectId}/files/rename`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
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
        const res = await apiFetch(`/api/projects/${projectId}/workspace_path`);
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
        apiFetch(`${NODE_ENGINE_URL}/execute`, {
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

async function updatePreview() {
    const frame = document.getElementById('preview-frame');
    // For non-HTML projects, check if there's an active deployment and use preview-app
    if (projectData && projectData.language !== 'html') {
        try {
            const res = await apiFetch(`/api/deploy/${projectId}/status`);
            const data = await res.json();
            if (data.status === 'running') {
                frame.src = `/preview-app/${projectId}?t=${Date.now()}`;
                return;
            }
        } catch (e) { /* fall through to static preview */ }
    }
    // Default: static file preview for HTML projects
    frame.src = `/preview/${projectId}/index.html?t=${Date.now()}`;
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
    document.querySelector(`.bottom-tab[data-panel="${panel}"]`)?.classList.add('active');

    document.querySelectorAll('.panel-pane').forEach(p => p.classList.remove('active'));
    const pane = document.getElementById(`${panel}-pane`);
    if (pane) pane.classList.add('active');

    if (panel === 'terminal' && fitAddon) {
        setTimeout(() => fitAddon.fit(), 50);
    }
    if (panel === 'preview') {
        updatePreview();
    }
    if (panel === 'deployments') {
        loadDeployments();
    }
    if (panel === 'database' && typeof initDatabasePanel === 'function') {
        const dbPane = document.getElementById('database-panel');
        if (dbPane && !dbPane.dataset.initialized) {
            dbPane.dataset.initialized = 'true';
            initDatabasePanel();
        }
    }
    if (panel === 'search' && typeof initSearchPanel === 'function') {
        const searchPane = document.getElementById('search-panel');
        if (searchPane && !searchPane.dataset.initialized) {
            searchPane.dataset.initialized = 'true';
            initSearchPanel();
        }
    }
    if (panel === 'browser') {
        // If browser has a URL loaded, make sure iframe is visible
        const browserFrame = document.getElementById('browser-frame');
        if (browserFrame && browserFrame.src && browserFrame.src !== 'about:blank') {
            browserFrame.style.display = 'block';
            document.getElementById('browser-empty').style.display = 'none';
        }
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
        const res = await apiFetch(`/api/ai/conversations/${projectId}`);
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
    apiFetch(`/api/ai/conversations/${projectId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role, content, msg_type: msgType || 'text' }),
    }).catch(() => {});
}

async function sendAIMessage() {
    const input = document.getElementById('ai-input');
    const prompt = input.value.trim();
    if (!prompt) return;

    addAIMessage(prompt, 'user');
    saveConversation('user', prompt);
    input.value = '';

    let codeContext = '';
    if (monacoEditor && activeTabIndex >= 0) {
        const selection = monacoEditor.getModel().getValueInRange(monacoEditor.getSelection());
        codeContext = selection || monacoEditor.getValue();
    }

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
            body = { prompt, project_id: projectId, auto_deploy: true };
            animateAgentProgress(progressEl);
        } else {
            endpoint = '/api/ai/generate';
            body = {
                prompt,
                code_context: codeContext,
                language: projectData.language,
                action: aiAction,
                project_id: projectId,
            };
        }

        const res = await apiFetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            timeout: aiAction === 'agent' ? 600000 : 120000,  // 10 min for agent, 2 min for others
        });

        const data = await res.json();

        if (aiAction === 'agent') {
            stopAgentAnimation();
        }
        progressEl.remove();

        if (aiAction === 'agent' && data.agent_executed) {
            renderAgentResult(data);
            await refreshFiles();
            // Auto-open in built-in browser if deployed
            if (data.deploy_result && data.deploy_result.success) {
                setTimeout(() => {
                    const appUrl = data.deploy_result.url;
                    openInBrowser(appUrl);
                }, 1000);
            }
        } else if (data.response) {
            addAIMessage(data.response, 'assistant');
            saveConversation('assistant', data.response);

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
                document.getElementById('ai-messages').lastElementChild.appendChild(insertBtn);
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

function renderAgentResult(data) {
    const resultEl = document.createElement('div');
    resultEl.className = 'ai-message assistant agent-result';
    let html = '';

    // Phase badge
    const phaseBadge = data.phase === 'fix' ? '🔧 Bug Fix' : data.phase === 'update' ? '🔄 Update' : data.phase === 'plan' ? '📋 Plan' : data.phase === 'multi-build' ? '🏗️ Multi-Build' : '🏗️ Build';
    const statusBadge = data.tests_passed ? '<span style="background:#3fb950;color:#000;padding:2px 8px;border-radius:10px;font-size:0.7rem;font-weight:700;margin-left:8px;">PASSED</span>' : (data.errors && data.errors.length ? '<span style="background:#f85149;color:#fff;padding:2px 8px;border-radius:10px;font-size:0.7rem;font-weight:700;margin-left:8px;">ISSUES</span>' : '');
    html += `<div class="agent-result-header"><span>${phaseBadge}</span> Agent Completed${statusBadge}</div>`;

    // Steps timeline (new multi-step view)
    if (data.steps && data.steps.length > 0) {
        html += `<div class="agent-steps-timeline">`;
        data.steps.forEach((step, i) => {
            const icon = step.status === 'done' ? '✅' : step.status === 'failed' ? '❌' : step.status === 'skipped' ? '⏭️' : '⏳';
            const color = step.status === 'done' ? '#3fb950' : step.status === 'failed' ? '#f85149' : '#8b949e';
            const duration = step.duration ? ` (${step.duration}s)` : '';
            html += `<div class="agent-timeline-step" style="border-left:2px solid ${color};padding:4px 0 4px 12px;margin-left:8px;">`;
            html += `<div style="font-size:0.82rem;font-weight:600;color:${color};">${icon} ${escapeHtml(step.name)}${duration}</div>`;
            if (step.detail) {
                html += `<div style="font-size:0.72rem;color:var(--text-secondary);margin-top:2px;">${escapeHtml(step.detail.substring(0, 200))}</div>`;
            }
            html += `</div>`;
        });
        html += `</div>`;
    }

    // Roadmap (collapsed by default if steps are present)
    if (data.roadmap && data.roadmap.length > 0) {
        const collapsed = data.steps && data.steps.length > 0 ? 'style="display:none;"' : '';
        html += `<div class="agent-roadmap" ${collapsed}><div class="agent-roadmap-title">📋 Roadmap</div>`;
        data.roadmap.forEach((step, i) => {
            html += `<div class="agent-roadmap-step"><span class="step-num">${i + 1}</span>${escapeHtml(step)}</div>`;
        });
        html += `</div>`;
    }

    // Files
    if (data.files && data.files.length > 0) {
        html += `<div class="agent-files-header">📁 ${data.files.length} files created/modified:</div><div class="agent-files-list">`;
        data.files.forEach(f => {
            const icon = f.action === 'deleted' ? '🗑' : (f.action === 'modify' ? '✍' : '📄');
            html += `<div class="agent-file-item"><span class="agent-file-icon">${icon}</span><span class="agent-file-path">${escapeHtml(f.path)}</span><span class="agent-file-action">${f.action}</span></div>`;
        });
        html += `</div>`;
    }

    // Fix iterations
    if (data.fix_iterations && data.fix_iterations.length > 0) {
        html += `<div style="margin-top:8px;"><strong style="font-size:0.8rem;">🔧 Auto-Fix Iterations:</strong>`;
        data.fix_iterations.forEach(fix => {
            const fIcon = fix.success ? '✅' : '❌';
            html += `<div style="font-size:0.75rem;margin-top:4px;color:${fix.success ? '#3fb950' : '#f85149'};">${fIcon} Attempt #${fix.attempt}: ${escapeHtml(fix.message || fix.error || 'Unknown')}</div>`;
        });
        html += `</div>`;
    }

    // AI-Powered Developer Tools (autonomous tool actions)
    if (data.tool_actions && data.tool_actions.length > 0) {
        const toolPassCount = data.tool_actions.filter(a => a.status === 'pass').length;
        const toolFailCount = data.tool_actions.filter(a => a.status === 'fail').length;
        const toolSummaryColor = toolFailCount > 0 ? '#f85149' : '#3fb950';
        const toolSummaryText = toolFailCount > 0 ? `${toolFailCount} failed` : 'All succeeded';

        html += `<div style="margin-top:10px;border:1px solid var(--border-color, #30363d);border-radius:8px;overflow:hidden;">`;
        html += `<div style="background:linear-gradient(135deg,#1a1b2e,#2d1b40);padding:8px 12px;display:flex;align-items:center;justify-content:space-between;">`;
        html += `<strong style="font-size:0.82rem;color:#e6e6e6;">\u{1F916} AI-Powered Tools</strong>`;
        html += `<span style="font-size:0.7rem;color:${toolSummaryColor};font-weight:600;">${toolPassCount} passed \u00b7 ${toolSummaryText}</span>`;
        html += `</div>`;
        html += `<div style="max-height:250px;overflow-y:auto;padding:6px 0;">`;
        data.tool_actions.forEach((act, i) => {
            let bg = 'transparent';
            let textColor = 'var(--text-secondary, #8b949e)';
            if (act.status === 'pass') { bg = 'rgba(63,185,80,0.08)'; textColor = '#3fb950'; }
            else if (act.status === 'fail') { bg = 'rgba(248,81,73,0.08)'; textColor = '#f85149'; }
            else if (act.status === 'info') { bg = 'rgba(88,166,255,0.05)'; textColor = '#58a6ff'; }
            const toolIcon = act.icon || '\u{1F527}';
            const toolLabel = act.tool ? `<span style="font-size:0.65rem;background:rgba(240,136,62,0.15);color:#f0883e;padding:1px 5px;border-radius:4px;margin-right:4px;">${act.tool}</span>` : '';
            html += `<div style="padding:4px 12px;background:${bg};display:flex;align-items:flex-start;gap:8px;border-bottom:1px solid rgba(255,255,255,0.03);">`;
            html += `<span style="font-size:0.78rem;min-width:18px;">${toolIcon}</span>`;
            html += `<div style="flex:1;min-width:0;">`;
            html += `<div style="font-size:0.78rem;font-weight:500;color:${textColor};">${toolLabel}${escapeHtml(act.action)}</div>`;
            if (act.detail) {
                html += `<div style="font-size:0.68rem;color:var(--text-secondary,#8b949e);margin-top:1px;opacity:0.8;">${escapeHtml(act.detail)}</div>`;
            }
            html += `</div></div>`;
        });
        html += `</div></div>`;
    }

    // Interactive Test Actions (Devin-like testing log)
    if (data.test_actions && data.test_actions.length > 0) {
        const passCount = data.test_actions.filter(a => a.status === 'pass').length;
        const failCount = data.test_actions.filter(a => a.status === 'fail').length;
        const issueCount = (data.test_issues || []).length;
        const summaryColor = failCount > 0 ? '#f85149' : '#3fb950';
        const summaryText = failCount > 0 ? `${failCount} issues found` : 'All tests passed';

        html += `<div style="margin-top:10px;border:1px solid var(--border-color, #30363d);border-radius:8px;overflow:hidden;">`;
        html += `<div style="background:linear-gradient(135deg,#1a1b2e,#2d1b69);padding:8px 12px;display:flex;align-items:center;justify-content:space-between;">`;
        html += `<strong style="font-size:0.82rem;color:#e6e6e6;">🧪 Interactive Testing</strong>`;
        html += `<span style="font-size:0.7rem;color:${summaryColor};font-weight:600;">${passCount} passed · ${summaryText}</span>`;
        html += `</div>`;
        html += `<div style="max-height:300px;overflow-y:auto;padding:6px 0;">`;
        data.test_actions.forEach((act, i) => {
            let bg = 'transparent';
            let textColor = 'var(--text-secondary, #8b949e)';
            if (act.status === 'pass') { bg = 'rgba(63,185,80,0.08)'; textColor = '#3fb950'; }
            else if (act.status === 'fail') { bg = 'rgba(248,81,73,0.08)'; textColor = '#f85149'; }
            else if (act.status === 'warn') { bg = 'rgba(210,153,34,0.08)'; textColor = '#d29922'; }
            html += `<div style="padding:4px 12px;background:${bg};display:flex;align-items:flex-start;gap:8px;border-bottom:1px solid rgba(255,255,255,0.03);">`;
            html += `<span style="font-size:0.75rem;color:var(--text-tertiary,#666);min-width:20px;text-align:right;">${i + 1}.</span>`;
            html += `<div style="flex:1;min-width:0;">`;
            html += `<div style="font-size:0.78rem;font-weight:500;color:${textColor};">${escapeHtml(act.action)}</div>`;
            if (act.detail) {
                html += `<div style="font-size:0.68rem;color:var(--text-secondary,#8b949e);margin-top:1px;opacity:0.8;">${escapeHtml(act.detail)}</div>`;
            }
            html += `</div></div>`;
        });
        html += `</div>`;
        if (issueCount > 0) {
            html += `<div style="padding:6px 12px;background:rgba(248,81,73,0.1);border-top:1px solid rgba(248,81,73,0.2);">`;
            html += `<div style="font-size:0.72rem;color:#f85149;font-weight:600;">⚠️ ${issueCount} issue(s) detected & auto-fixed:</div>`;
            (data.test_issues || []).forEach(issue => {
                html += `<div style="font-size:0.68rem;color:#f85149;margin-top:2px;">• ${escapeHtml(issue)}</div>`;
            });
            html += `</div>`;
        }
        html += `</div>`;
    }

    // Devin-like Agent Activity Log (live_log)
    if (data.live_log && data.live_log.length > 0) {
        html += `<div style="margin-top:10px;border:1px solid var(--border-color, #30363d);border-radius:8px;overflow:hidden;">`;
        html += `<div onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none';this.querySelector('.toggle-arrow').textContent=this.nextElementSibling.style.display==='none'?'\u25B6':'\u25BC'" style="background:linear-gradient(135deg,#0d1117,#161b22);padding:8px 12px;display:flex;align-items:center;justify-content:space-between;cursor:pointer;">`;
        html += `<strong style="font-size:0.82rem;color:#58a6ff;">\u{1F4AC} Agent Activity Log</strong>`;
        html += `<span style="font-size:0.7rem;color:var(--text-secondary);font-weight:600;"><span class="toggle-arrow">\u25BC</span> ${data.live_log.length} events</span>`;
        html += `</div>`;
        html += `<div class="agent-live-log" style="max-height:350px;overflow-y:auto;padding:4px 0;">`;
        data.live_log.forEach((entry, i) => {
            const typeColors = { info: '#58a6ff', plan: '#d2a8ff', generate: '#79c0ff', write: '#7ee787', fix: '#ffa657', success: '#3fb950', error: '#f85149', warn: '#d29922', test: '#bc8cff', install: '#58a6ff', deploy: '#f778ba', complete: '#3fb950' };
            const color = typeColors[entry.type] || '#8b949e';
            const bg = entry.type === 'success' ? 'rgba(63,185,80,0.06)' : entry.type === 'error' ? 'rgba(248,81,73,0.06)' : entry.type === 'warn' ? 'rgba(210,153,34,0.06)' : 'transparent';
            html += `<div class="log-entry" style="padding:3px 12px;background:${bg};display:flex;align-items:flex-start;gap:8px;border-bottom:1px solid rgba(255,255,255,0.02);animation:fadeInLog 0.3s ease ${i * 0.05}s both;">`;
            html += `<span style="font-size:0.78rem;min-width:18px;">${entry.icon || '\u25CF'}</span>`;
            html += `<span style="font-size:0.75rem;color:${color};line-height:1.4;">${escapeHtml(entry.message)}</span>`;
            html += `</div>`;
        });
        html += `</div></div>`;
    }

    // Deploy result
    if (data.deploy_result) {
        if (data.deploy_result.success) {
            html += `<div class="agent-test-result" style="border-color:#3fb950;background:rgba(63,185,80,0.1);"><strong>🚀 Auto-Deployed!</strong> Running on port ${data.deploy_result.port} — Ready!</div>`;
        } else {
            html += `<div class="agent-test-result" style="border-color:#f85149;"><strong>🚀 Deploy Failed:</strong> ${escapeHtml(data.deploy_result.error || 'Unknown error')}</div>`;
        }
    }

    // Run command
    if (data.run_command) {
        html += `<div class="agent-run-cmd"><span>Run:</span> <code>${escapeHtml(data.run_command)}</code></div>`;
    }

    // Message
    html += `<div class="agent-message">${escapeHtml(data.message)}</div>`;

    // Errors
    if (data.errors && data.errors.length > 0) {
        html += `<div class="agent-errors">⚠️ Warnings: ${data.errors.map(escapeHtml).join(', ')}</div>`;
    }

    // Action buttons
    html += `<div class="agent-actions" style="display:flex;gap:6px;margin-top:10px;flex-wrap:wrap;">`;
    if (!data.deploy_result || !data.deploy_result.success) {
        if (data.deploy_ready || data.tests_passed) {
            html += `<button onclick="agentDeploy()" class="btn btn-sm" style="background:linear-gradient(135deg,#3fb950,#2ea44f);color:white;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:0.8rem;font-weight:600;">🚀 Deploy Now</button>`;
        }
    } else if (data.deploy_result && data.deploy_result.success) {
        html += `<button onclick="window.open('${data.deploy_result.url}','_blank')" class="btn btn-sm" style="background:linear-gradient(135deg,#3fb950,#2ea44f);color:white;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:0.8rem;font-weight:600;">🌐 Open App</button>`;
    }
    if (data.run_command) {
        html += `<button onclick="agentRunInTerminal('${escapeAttr(data.run_command)}')" class="btn btn-sm" style="background:var(--accent-blue);color:white;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:0.8rem;">▶ Run</button>`;
    }
    if (!data.tests_passed) {
        html += `<button onclick="agentRetryFix()" class="btn btn-sm" style="background:var(--accent-orange, #d29922);color:white;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:0.8rem;">🔧 Fix Again</button>`;
    }
    html += `</div>`;

    resultEl.innerHTML = html;
    document.getElementById('ai-messages').appendChild(resultEl);
    document.getElementById('ai-messages').scrollTop = document.getElementById('ai-messages').scrollHeight;

    saveConversation('assistant', resultEl.innerHTML, 'agent-result');

    // Store last agent data for retry/deploy
    window._lastAgentData = data;

    if (data.deploy_result && data.deploy_result.success) {
        showToast('App built, tested & auto-deployed!', 'success');
    } else if (data.tests_passed) {
        showToast('Agent built & all tests passed!', 'success');
    } else if (data.fix_iterations && data.fix_iterations.length > 0) {
        showToast('Agent attempted auto-fixes. Check results.', 'info');
    } else {
        showToast('Agent completed. Check results.', 'info');
    }
}

async function agentDeploy() {
    showToast('Deploying...', 'info');
    setStatus('Deploying...');
    try {
        const res = await apiFetch(`/api/deploy/${projectId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.ready ? `Deployed and ready on port ${data.port}!` : `Deployed on port ${data.port} (starting...)`, data.ready ? 'success' : 'info');
            setStatus(`Deployed (port ${data.port})`);
            addAIMessage(`✅ Deployed successfully!\nPort: ${data.port}\nURL: ${window.location.origin}${data.url}\n\nOpening in browser...`, 'system');
            const agentDelay = data.ready ? 200 : 2000;
            setTimeout(() => {
                openInBrowser(data.url);
            }, agentDelay);
            loadDeployments();
        } else {
            showToast(data.error || 'Deploy failed', 'error');
            addAIMessage(`❌ Deploy failed: ${data.error || 'Unknown error'}`, 'system error');
        }
    } catch (e) {
        showToast('Deploy error: ' + e.message, 'error');
    }
}

function agentRunInTerminal(command) {
    switchBottomTab('terminal');
    if (socket && socket.connected) {
        socket.emit('terminal_input', { input: command + '\r' });
    }
}

async function agentRetryFix() {
    const lastData = window._lastAgentData;
    if (!lastData) return;

    const errorOutput = lastData.test_result?.output || lastData.auto_fix?.remaining_error || '';
    const input = document.getElementById('ai-input');
    input.value = '';

    addAIMessage('Retrying fix...', 'user');
    saveConversation('user', 'Fix the remaining error');

    const progressEl = addAgentProgress();
    updateAgentStep(progressEl, 1);

    setTimeout(() => updateAgentStep(progressEl, 2), 2000);
    setTimeout(() => updateAgentStep(progressEl, 3), 5000);

    try {
        const res = await apiFetch(`/api/ai/agent`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt: 'Fix the error and make the app work correctly.',
                project_id: projectId,
                error_context: errorOutput,
                phase: 'fix',
            }),
        });
        const data = await res.json();
        updateAgentStep(progressEl, 6);
        await new Promise(r => setTimeout(r, 300));
        progressEl.remove();

        if (data.agent_executed) {
            renderAgentResult(data);
            await refreshFiles();
        } else if (data.error) {
            addAIMessage(`Error: ${data.error}`, 'system error');
        }
    } catch (e) {
        progressEl.remove();
        addAIMessage(`Error: ${e.message}`, 'system error');
    }
}

let _agentAnimationInterval = null;

function addAgentProgress() {
    const messagesDiv = document.getElementById('ai-messages');
    const el = document.createElement('div');
    el.className = 'ai-message system agent-progress';
    el.innerHTML = `
        <div class="agent-progress-title">🤖 YubiAI Autonomous Agent</div>
        <div class="agent-mode-badge" style="font-size:0.7rem;color:var(--accent-blue);margin-bottom:6px;font-weight:600;">Analyzing project size...</div>
        <div class="agent-steps">
            <div class="agent-step active" data-step="1"><span class="step-icon spinner">⚙</span> Analyzing project...</div>
            <div class="agent-step" data-step="2"><span class="step-icon">🧠</span> Planning architecture...</div>
            <div class="agent-step" data-step="3"><span class="step-icon">📁</span> Generating code (batch 1)...</div>
            <div class="agent-step" data-step="4"><span class="step-icon">📁</span> Generating code (batch 2+)...</div>
            <div class="agent-step" data-step="5"><span class="step-icon">📦</span> Installing dependencies...</div>
            <div class="agent-step" data-step="6"><span class="step-icon">🧪</span> Testing &amp; auto-fixing...</div>
            <div class="agent-step" data-step="7"><span class="step-icon">🚀</span> Auto-deploying...</div>
            <div class="agent-step" data-step="8"><span class="step-icon">✅</span> Complete!</div>
        </div>
        <div class="agent-live-feed" style="margin-top:8px;border-top:1px solid var(--border-color,#30363d);padding-top:6px;">
            <div style="font-size:0.7rem;color:#58a6ff;font-weight:600;margin-bottom:4px;">💬 Live Activity</div>
            <div class="live-feed-messages" style="max-height:120px;overflow-y:auto;font-size:0.72rem;"></div>
        </div>
        <div class="agent-timer" style="font-size:0.7rem;color:var(--text-secondary);margin-top:6px;">Elapsed: 0s</div>
    `;
    messagesDiv.appendChild(el);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    return el;
}

function animateAgentProgress(el) {
    if (!el) return;
    const startTime = Date.now();
    let currentStep = 1;
    let liveMsgIndex = 0;
    const stepTimings = [0, 3000, 12000, 25000, 40000, 55000, 70000, 85000];

    // Devin-like live activity messages shown during build
    const liveMessages = [
        { t: 1000, icon: '🔍', msg: 'Now analyzing project structure and requirements...' },
        { t: 3500, icon: '🧠', msg: 'Now planning project architecture — identifying files and dependencies...' },
        { t: 6000, icon: '📋', msg: 'Now organizing files into build groups for optimal generation...' },
        { t: 10000, icon: '⚡', msg: 'Now generating Project Core files (settings, urls, config)...' },
        { t: 18000, icon: '📝', msg: 'Now creating application models and database schema...' },
        { t: 26000, icon: '📝', msg: 'Now generating views, forms, and URL routing...' },
        { t: 34000, icon: '🎨', msg: 'Now creating HTML templates with responsive design...' },
        { t: 42000, icon: '🎨', msg: 'Now generating static assets (CSS, JavaScript)...' },
        { t: 50000, icon: '📦', msg: 'Now installing project dependencies...' },
        { t: 58000, icon: '🧪', msg: 'Now testing project — running validation checks...' },
        { t: 65000, icon: '🔧', msg: 'Now checking for issues and applying auto-fixes...' },
        { t: 72000, icon: '🗄️', msg: 'Now setting up database and running migrations...' },
        { t: 78000, icon: '🚀', msg: 'Now deploying application...' },
        { t: 85000, icon: '✅', msg: 'Finalizing build — almost done!' },
    ];

    // Update mode badge after 4 seconds
    setTimeout(() => {
        const badge = el.querySelector('.agent-mode-badge');
        if (badge) badge.textContent = '🔄 Multi-Request Mode — building in batches for best results';
    }, 4000);

    _agentAnimationInterval = setInterval(() => {
        if (!el || !el.parentNode) { stopAgentAnimation(); return; }
        const elapsed = Date.now() - startTime;

        // Advance steps based on elapsed time
        for (let i = stepTimings.length - 1; i >= 0; i--) {
            if (elapsed >= stepTimings[i] && i + 1 > currentStep) {
                currentStep = i + 1;
                break;
            }
        }
        updateAgentStep(el, currentStep);

        // Show live activity messages based on elapsed time
        const feedEl = el.querySelector('.live-feed-messages');
        if (feedEl) {
            while (liveMsgIndex < liveMessages.length && elapsed >= liveMessages[liveMsgIndex].t) {
                const m = liveMessages[liveMsgIndex];
                const msgDiv = document.createElement('div');
                msgDiv.style.cssText = 'padding:2px 0;color:#58a6ff;opacity:0;animation:fadeInLog 0.4s ease forwards;';
                msgDiv.innerHTML = `<span style="margin-right:4px;">${m.icon}</span>${m.msg}`;
                feedEl.appendChild(msgDiv);
                feedEl.scrollTop = feedEl.scrollHeight;
                liveMsgIndex++;
            }
        }

        // Update timer
        const timerEl = el.querySelector('.agent-timer');
        if (timerEl) timerEl.textContent = `Elapsed: ${Math.round(elapsed / 1000)}s`;
    }, 500);
}

function stopAgentAnimation() {
    if (_agentAnimationInterval) {
        clearInterval(_agentAnimationInterval);
        _agentAnimationInterval = null;
    }
}

function updateAgentStep(el, step) {
    if (!el || !el.parentNode) return;
    el.querySelectorAll('.agent-step').forEach(s => {
        const n = parseInt(s.dataset.step);
        if (n < step) { s.classList.add('done'); s.classList.remove('active'); }
        else if (n === step) { s.classList.add('active'); s.classList.remove('done'); }
        else { s.classList.remove('active', 'done'); }
    });
    document.getElementById('ai-messages').scrollTop = document.getElementById('ai-messages').scrollHeight;
}

async function clearAIChat() {
    if (!confirm('Clear all AI conversation history for this project?')) return;
    document.getElementById('ai-messages').innerHTML = '<div class="ai-message system">YubiAI is ready. Ask me to generate code, debug, explain, or build your entire project!</div>';
    try {
        await apiFetch(`/api/ai/conversations/${projectId}`, { method: 'DELETE' });
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
        const res = await apiFetch(`/api/deploy/${projectId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
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

            // Show preview immediately if ready, otherwise short delay
            const delay = data.ready ? 200 : 2000;
            setTimeout(() => {
                const frame = document.getElementById('preview-frame');
                frame.src = `${data.url}?t=${Date.now()}`;
                switchBottomTab('preview');
            }, delay);

            // Also refresh deployments panel
            loadDeployments();
        } else {
            showToast(data.error || 'Deploy failed', 'error');
            setStatus('Deploy failed');
        }
    } catch (e) {
        showToast('Deploy error: ' + e.message, 'error');
        setStatus('Error');
    }
}

async function stopDeployment(pid) {
    const targetId = pid || projectId;
    try {
        const res = await apiFetch(`/api/deploy/${targetId}`, {
            method: 'DELETE',
        });
        const data = await res.json();
        if (res.ok) {
            showToast('Deployment stopped', 'success');
            setStatus('Ready');
            loadDeployments();
        } else {
            showToast(data.error || 'Failed to stop', 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function loadDeployments() {
    const container = document.getElementById('deployments-list');
    if (!container) return;
    container.innerHTML = '<div style="color:var(--text-muted);padding:20px;text-align:center;">Loading deployments...</div>';

    try {
        const res = await apiFetch(`/api/deployments`);
        const deployments = await res.json();

        if (!deployments.length) {
            container.innerHTML = `
                <div style="text-align:center;padding:30px;color:var(--text-muted);">
                    <div style="font-size:2rem;margin-bottom:8px;">🚀</div>
                    <p>No deployments yet</p>
                    <p style="font-size:0.8rem;">Click the Deploy button to deploy your project</p>
                </div>`;
            return;
        }

        let html = '<div style="display:flex;flex-direction:column;gap:8px;">';
        for (const dep of deployments) {
            const statusColor = dep.status === 'running' ? '#3fb950' : dep.status === 'crashed' ? '#f85149' : '#8b949e';
            const statusIcon = dep.status === 'running' ? '🟢' : dep.status === 'crashed' ? '🔴' : '⚪';
            const previewUrl = `/preview-app/${dep.project_id}`;
            const createdAt = dep.created_at ? new Date(dep.created_at).toLocaleString() : '';

            html += `
            <div style="background:var(--bg-tertiary);border:1px solid var(--border-color);border-radius:8px;padding:12px;">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span>${statusIcon}</span>
                        <strong style="color:var(--text-primary);">${escapeHtml(dep.project_name || 'Project #' + dep.project_id)}</strong>
                        <span style="background:color-mix(in srgb, ${statusColor} 20%, transparent);color:${statusColor};padding:2px 8px;border-radius:12px;font-size:0.75rem;font-weight:600;">${dep.status}</span>
                    </div>
                    <span style="color:var(--text-muted);font-size:0.75rem;">${createdAt}</span>
                </div>
                <div style="display:flex;gap:12px;font-size:0.8rem;color:var(--text-secondary);margin-bottom:8px;">
                    <span>Port: <strong>${dep.deploy_port}</strong></span>
                    <span>PID: <strong>${dep.deploy_pid || '-'}</strong></span>
                    ${dep.project_language ? `<span>Stack: <strong>${dep.project_language}</strong></span>` : ''}
                </div>
                <div style="display:flex;gap:6px;flex-wrap:wrap;">
                    ${dep.status === 'running' ? `
                        <button onclick="window.open('${previewUrl}','_blank')" class="btn btn-sm" style="background:var(--accent-blue);color:white;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:0.75rem;">🌐 Open</button>
                        <button onclick="restartDeployment(${dep.project_id})" class="btn btn-sm" style="background:var(--accent-purple);color:white;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:0.75rem;">🔄 Restart</button>
                        <button onclick="stopDeployment(${dep.project_id})" class="btn btn-sm" style="background:var(--accent-orange);color:white;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:0.75rem;">⏹ Stop</button>
                    ` : `
                        <button onclick="redeployProject(${dep.project_id})" class="btn btn-sm" style="background:var(--accent-green);color:white;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:0.75rem;">🚀 Redeploy</button>
                    `}
                    <button onclick="deleteDeployment(${dep.id})" class="btn btn-sm" style="background:var(--danger);color:white;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:0.75rem;">🗑 Delete</button>
                </div>
            </div>`;
        }
        html += '</div>';
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = `<div style="color:var(--danger);padding:20px;text-align:center;">Failed to load deployments: ${e.message}</div>`;
    }
}

async function restartDeployment(projId) {
    showToast('Restarting deployment...', 'info');
    try {
        const res = await apiFetch(`/api/deploy/${projId}/restart`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
        const data = await res.json();
        if (res.ok) {
            showToast(`Restarted on port ${data.port}!`, 'success');
            loadDeployments();
        } else {
            showToast(data.error || 'Restart failed', 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function redeployProject(projId) {
    showToast('Deploying...', 'info');
    try {
        const res = await apiFetch(`/api/deploy/${projId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
        const data = await res.json();
        if (res.ok) {
            showToast(`Deployed on port ${data.port}!`, 'success');
            loadDeployments();
        } else {
            showToast(data.error || 'Deploy failed', 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

async function deleteDeployment(deployId) {
    if (!confirm('Delete this deployment record?')) return;
    try {
        const res = await apiFetch(`/api/deploy/${deployId}/delete`, {
            method: 'DELETE',
        });
        const data = await res.json();
        if (res.ok) {
            showToast('Deployment deleted', 'success');
            loadDeployments();
        } else {
            showToast(data.error || 'Delete failed', 'error');
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

// ============================================
// FLUTTER BUILD & DOWNLOAD
// ============================================

let _flutterStatus = null;

async function checkFlutterStatus() {
    if (!projectId) return;
    try {
        const res = await apiFetch(`/api/flutter/status/${projectId}`);
        const data = await res.json();
        _flutterStatus = data;
        const btn = document.getElementById('flutter-build-btn');
        const dlBtn = document.getElementById('flutter-download-apk-btn');
        if (btn && data.is_flutter) {
            btn.style.display = '';
        }
        // Show/hide download APK button based on build status
        if (dlBtn && data.is_flutter && data.apk_built) {
            dlBtn.style.display = '';
            dlBtn.title = `Download APK (${data.apk_size_human || ''})`;
            dlBtn.innerHTML = `⬇ Download APK${data.apk_size_human ? ' (' + data.apk_size_human + ')' : ''}`;
        } else if (dlBtn) {
            dlBtn.style.display = 'none';
        }
    } catch (e) {
        // Not a Flutter project or endpoint not available
    }
}

function showFlutterBuildMenu() {
    // Remove existing menu if any
    const existing = document.getElementById('flutter-build-menu');
    if (existing) { existing.remove(); return; }

    const btn = document.getElementById('flutter-build-btn');
    const rect = btn.getBoundingClientRect();

    const menu = document.createElement('div');
    menu.id = 'flutter-build-menu';
    menu.style.cssText = `position:fixed;top:${rect.bottom+4}px;left:${rect.left}px;background:var(--bg-secondary,#161b22);border:1px solid var(--border-color,#30363d);border-radius:8px;padding:6px 0;z-index:9999;min-width:220px;box-shadow:0 8px 24px rgba(0,0,0,0.4);`;

    let items = `
        <div class="flutter-menu-item" onclick="flutterBuild('web')" style="padding:8px 16px;cursor:pointer;display:flex;align-items:center;gap:8px;font-size:0.85rem;color:var(--text-primary,#e6edf3);" onmouseover="this.style.background='rgba(255,255,255,0.06)'" onmouseout="this.style.background='none'">
            <span>🌐</span> Build Web App
        </div>
        <div class="flutter-menu-item" onclick="flutterBuild('apk')" style="padding:8px 16px;cursor:pointer;display:flex;align-items:center;gap:8px;font-size:0.85rem;color:var(--text-primary,#e6edf3);" onmouseover="this.style.background='rgba(255,255,255,0.06)'" onmouseout="this.style.background='none'">
            <span>📱</span> Build Android APK
        </div>
        <div style="border-top:1px solid var(--border-color,#30363d);margin:4px 0;"></div>
    `;

    if (_flutterStatus && _flutterStatus.apk_built) {
        items += `
        <div class="flutter-menu-item" onclick="flutterDownload('apk')" style="padding:8px 16px;cursor:pointer;display:flex;align-items:center;gap:8px;font-size:0.85rem;color:#58a6ff;" onmouseover="this.style.background='rgba(255,255,255,0.06)'" onmouseout="this.style.background='none'">
            <span>⬇️</span> Download APK (${_flutterStatus.apk_size_human})
        </div>`;
    }
    if (_flutterStatus && _flutterStatus.web_built) {
        items += `
        <div class="flutter-menu-item" onclick="flutterDownload('web')" style="padding:8px 16px;cursor:pointer;display:flex;align-items:center;gap:8px;font-size:0.85rem;color:#58a6ff;" onmouseover="this.style.background='rgba(255,255,255,0.06)'" onmouseout="this.style.background='none'">
            <span>⬇️</span> Download Web Build (.zip)
        </div>`;
    }
    if (!(_flutterStatus && (_flutterStatus.apk_built || _flutterStatus.web_built))) {
        items += `
        <div style="padding:8px 16px;font-size:0.78rem;color:var(--text-secondary,#8b949e);">
            No builds yet. Build first to download.
        </div>`;
    }

    menu.innerHTML = items;
    document.body.appendChild(menu);

    // Close on outside click
    setTimeout(() => {
        document.addEventListener('click', function closeMenu(e) {
            if (!menu.contains(e.target) && e.target !== btn) {
                menu.remove();
                document.removeEventListener('click', closeMenu);
            }
        });
    }, 10);
}

async function flutterBuild(type) {
    // Close menu
    const menu = document.getElementById('flutter-build-menu');
    if (menu) menu.remove();

    const typeLabel = type === 'apk' ? 'Android APK' : 'Web App';
    showToast(`Building Flutter ${typeLabel}... This may take a few minutes.`, 'info');
    setStatus(`Building Flutter ${typeLabel}...`);

    // Show progress in console
    clearConsole();
    switchBottomTab('console');
    appendConsole(`=== Flutter ${typeLabel} Build ===\n`, 'info');
    appendConsole(`Running flutter pub get...\n`, 'info');

    try {
        const res = await apiFetch(`/api/flutter/build/${projectId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type }),
        });
        const data = await res.json();

        if (data.success) {
            if (type === 'web') {
                appendConsole(`\nBuild successful!\n`, 'success');
                appendConsole(`Flutter web app deployed on port ${data.port}\n`, 'success');
                appendConsole(`URL: ${window.location.origin}${data.url}\n`, 'info');
                showToast('Flutter web app built and deployed!', 'success');
                setStatus(`Web app deployed (port ${data.port})`);

                // Auto-show in preview
                setTimeout(() => {
                    const frame = document.getElementById('preview-frame');
                    frame.src = `${data.url}?t=${Date.now()}`;
                    switchBottomTab('preview');
                }, 500);

                // Also open in browser panel
                openInBrowser(data.url);
                loadDeployments();
            } else {
                appendConsole(`\nAPK built successfully!\n`, 'success');
                appendConsole(`Size: ${data.size_human}\n`, 'info');
                appendConsole(`Download: ${data.download_url}\n`, 'info');
                showToast(`APK built! Size: ${data.size_human}. Click "Download APK" to download.`, 'success');
                setStatus(`APK ready (${data.size_human})`);
                // Immediately show the download button
                const dlBtn = document.getElementById('flutter-download-apk-btn');
                if (dlBtn) {
                    dlBtn.style.display = '';
                    dlBtn.innerHTML = `⬇ Download APK (${data.size_human})`;
                    dlBtn.title = `Download APK (${data.size_human})`;
                }
            }
            // Refresh flutter status for download buttons
            checkFlutterStatus();
        } else {
            appendConsole(`\nBuild FAILED:\n`, 'error');
            appendConsole(`${data.error}\n`, 'error');
            if (data.details) appendConsole(`\n${data.details}\n`, 'error');
            showToast(`Flutter ${typeLabel} build failed: ${data.error}`, 'error');
            setStatus('Build failed');
        }
    } catch (e) {
        appendConsole(`\nBuild error: ${e.message}\n`, 'error');
        showToast(`Build error: ${e.message}`, 'error');
        setStatus('Build error');
    }
}

function flutterDownload(artifact) {
    // Close menu
    const menu = document.getElementById('flutter-build-menu');
    if (menu) menu.remove();

    // Trigger download via hidden link
    const url = `/api/flutter/download/${projectId}/${artifact}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
    showToast(`Downloading ${artifact === 'apk' ? 'APK' : 'web build'}...`, 'info');
}

// ============================================
// UTILITIES
// ============================================

// ============================================
// BUILT-IN BROWSER PANEL (Devin-like)
// ============================================

let _browserHistory = [];
let _browserHistoryIndex = -1;

function openInBrowser(url) {
    if (!url) return;
    // Ensure URL has protocol
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
        url = window.location.origin + url;
    }
    const frame = document.getElementById('browser-frame');
    const urlBar = document.getElementById('browser-url-bar');
    const emptyState = document.getElementById('browser-empty');
    if (frame) {
        frame.src = url + (url.includes('?') ? '&' : '?') + 't=' + Date.now();
        frame.style.display = 'block';
        if (emptyState) emptyState.style.display = 'none';
    }
    if (urlBar) urlBar.value = url;
    // Add to history
    _browserHistory = _browserHistory.slice(0, _browserHistoryIndex + 1);
    _browserHistory.push(url);
    _browserHistoryIndex = _browserHistory.length - 1;
    // Switch to browser tab
    switchBottomTab('browser');
    showToast('App opened in browser', 'success');
}

function browserNavigate(url) {
    if (!url || !url.trim()) return;
    url = url.trim();
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
        url = 'https://' + url;
    }
    openInBrowser(url);
}

function browserBack() {
    if (_browserHistoryIndex > 0) {
        _browserHistoryIndex--;
        const url = _browserHistory[_browserHistoryIndex];
        const frame = document.getElementById('browser-frame');
        const urlBar = document.getElementById('browser-url-bar');
        if (frame) frame.src = url;
        if (urlBar) urlBar.value = url;
    }
}

function browserForward() {
    if (_browserHistoryIndex < _browserHistory.length - 1) {
        _browserHistoryIndex++;
        const url = _browserHistory[_browserHistoryIndex];
        const frame = document.getElementById('browser-frame');
        const urlBar = document.getElementById('browser-url-bar');
        if (frame) frame.src = url;
        if (urlBar) urlBar.value = url;
    }
}

function browserReload() {
    const frame = document.getElementById('browser-frame');
    if (frame && frame.src && frame.src !== 'about:blank') {
        frame.src = frame.src;
    }
}

function browserOpenExternal() {
    const urlBar = document.getElementById('browser-url-bar');
    if (urlBar && urlBar.value) {
        window.open(urlBar.value, '_blank');
    }
}

// ============================================
// NAVIGATION
// ============================================

function goBack() {
    // Check for unsaved changes
    const hasUnsaved = openTabs.some(tab => tab.modified);
    if (hasUnsaved) {
        if (!confirm('You have unsaved changes. Save before leaving?')) {
            // User chose not to save, just go back
            window.location.href = '/';
            return;
        }
        // Save all modified files before navigating
        openTabs.forEach((tab, i) => {
            if (tab.modified) saveFile(i);
        });
    }
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
