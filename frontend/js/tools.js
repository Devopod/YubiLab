/**
 * YubiLab Developer Tools — Replit-like tools for the IDE
 * Package Manager, SQL Executor, Code Search, Workflow Manager, Secrets, Shell
 */

// ══════════════════════════════════════════════════════════════
// TOOLS PANEL (slide-out panel like the AI panel)
// ══════════════════════════════════════════════════════════════

let toolsPanelOpen = false;
let currentToolTab = 'packages';

function toggleTools() {
    const panel = document.getElementById('tools-panel');
    if (!panel) {
        createToolsPanel();
        toolsPanelOpen = true;
        return;
    }
    toolsPanelOpen = !toolsPanelOpen;
    panel.style.display = toolsPanelOpen ? 'flex' : 'none';
    if (toolsPanelOpen) switchToolTab(currentToolTab);
}

function createToolsPanel() {
    // Remove if exists
    const existing = document.getElementById('tools-panel');
    if (existing) existing.remove();

    const panel = document.createElement('div');
    panel.id = 'tools-panel';
    panel.className = 'ai-panel';
    panel.style.cssText = 'display:flex;flex-direction:column;';
    panel.innerHTML = `
        <div class="ai-panel-header" style="background:linear-gradient(135deg,#1a1b2e,#2d1b40);">
            <div style="display:flex;align-items:center;gap:8px;">
                <span>\ud83d\udee0 Developer Tools</span>
                <span class="ai-badge" style="background:linear-gradient(135deg,#f0883e,#d29922);">Replit-like</span>
            </div>
            <button class="ai-close" onclick="toggleTools()">\u2715</button>
        </div>

        <!-- Tool Tabs -->
        <div style="display:flex;gap:2px;padding:6px 8px;background:var(--bg-secondary, #161b22);border-bottom:1px solid var(--border-color, #30363d);flex-wrap:wrap;">
            <button class="tool-tab active" data-tool="packages" onclick="switchToolTab('packages')">\ud83d\udce6 Packages</button>
            <button class="tool-tab" data-tool="database" onclick="switchToolTab('database')">\ud83d\uddc4 Database</button>
            <button class="tool-tab" data-tool="search" onclick="switchToolTab('search')">\ud83d\udd0d Search</button>
            <button class="tool-tab" data-tool="workflows" onclick="switchToolTab('workflows')">\u2699\ufe0f Workflows</button>
            <button class="tool-tab" data-tool="secrets" onclick="switchToolTab('secrets')">\ud83d\udd10 Secrets</button>
            <button class="tool-tab" data-tool="shell" onclick="switchToolTab('shell')">\ud83d\udcbb Shell</button>
            <button class="tool-tab" data-tool="info" onclick="switchToolTab('info')">\u2139\ufe0f Info</button>
        </div>

        <!-- Tool Content -->
        <div id="tools-content" style="flex:1;overflow-y:auto;padding:10px;font-size:0.82rem;">
        </div>
    `;

    // Insert before the AI panel or at end of editor-body
    const editorBody = document.querySelector('.editor-body');
    const aiPanel = document.getElementById('ai-panel');
    if (aiPanel) {
        editorBody.insertBefore(panel, aiPanel);
    } else {
        editorBody.appendChild(panel);
    }

    // Add tool tab styles
    if (!document.getElementById('tool-tab-styles')) {
        const style = document.createElement('style');
        style.id = 'tool-tab-styles';
        style.textContent = `
            .tool-tab {
                padding: 4px 8px; font-size: 0.72rem; border-radius: 6px;
                background: transparent; border: 1px solid transparent;
                color: var(--text-secondary, #8b949e); cursor: pointer;
                transition: all 0.15s;
            }
            .tool-tab:hover { background: var(--bg-tertiary, #21262d); color: var(--text-primary, #e6edf3); }
            .tool-tab.active {
                background: linear-gradient(135deg, rgba(240,136,62,0.2), rgba(210,153,34,0.2));
                border-color: #f0883e; color: #f0883e; font-weight: 600;
            }
            .tool-input {
                width: 100%; padding: 6px 10px; font-size: 0.8rem; border-radius: 6px;
                background: var(--bg-primary, #0d1117); border: 1px solid var(--border-color, #30363d);
                color: var(--text-primary, #e6edf3); outline: none; font-family: 'JetBrains Mono', monospace;
            }
            .tool-input:focus { border-color: #f0883e; }
            .tool-btn {
                padding: 5px 12px; font-size: 0.75rem; border-radius: 6px; cursor: pointer;
                background: linear-gradient(135deg, #f0883e, #d29922); border: none;
                color: #fff; font-weight: 600; transition: opacity 0.15s;
            }
            .tool-btn:hover { opacity: 0.85; }
            .tool-btn.danger { background: linear-gradient(135deg, #f85149, #da3633); }
            .tool-btn.secondary { background: var(--bg-tertiary, #21262d); border: 1px solid var(--border-color, #30363d); color: var(--text-primary, #e6edf3); }
            .tool-result {
                margin-top: 8px; padding: 8px; border-radius: 6px;
                background: var(--bg-primary, #0d1117); border: 1px solid var(--border-color, #30363d);
                font-family: 'JetBrains Mono', monospace; font-size: 0.75rem;
                max-height: 300px; overflow-y: auto; white-space: pre-wrap; word-break: break-all;
            }
            .tool-section { margin-bottom: 14px; }
            .tool-section-title {
                font-size: 0.78rem; font-weight: 600; color: var(--text-primary, #e6edf3);
                margin-bottom: 6px; display: flex; align-items: center; gap: 6px;
            }
            .tool-hint { font-size: 0.7rem; color: var(--text-secondary, #8b949e); margin-bottom: 6px; }
            .sql-table { width: 100%; border-collapse: collapse; font-size: 0.72rem; }
            .sql-table th { background: var(--bg-tertiary, #21262d); padding: 4px 8px; text-align: left; border: 1px solid var(--border-color, #30363d); }
            .sql-table td { padding: 4px 8px; border: 1px solid var(--border-color, #30363d); }
            .sql-table tr:hover { background: rgba(240,136,62,0.05); }
            .search-result { padding: 6px 8px; border-bottom: 1px solid var(--border-color, #30363d); cursor: pointer; }
            .search-result:hover { background: var(--bg-tertiary, #21262d); }
            .search-file { color: #58a6ff; font-size: 0.72rem; }
            .search-line { color: #f0883e; font-size: 0.7rem; }
            .search-content { color: var(--text-primary, #e6edf3); font-family: 'JetBrains Mono', monospace; font-size: 0.72rem; }
            .workflow-item { display: flex; align-items: center; gap: 8px; padding: 8px; border: 1px solid var(--border-color, #30363d); border-radius: 6px; margin-bottom: 6px; }
            .secret-item { display: flex; align-items: center; justify-content: space-between; padding: 6px 8px; border: 1px solid var(--border-color, #30363d); border-radius: 6px; margin-bottom: 4px; }
        `;
        document.head.appendChild(style);
    }

    switchToolTab('packages');
}

function switchToolTab(tab) {
    currentToolTab = tab;
    document.querySelectorAll('.tool-tab').forEach(t => {
        t.classList.toggle('active', t.dataset.tool === tab);
    });
    const content = document.getElementById('tools-content');
    if (!content) return;

    switch (tab) {
        case 'packages': renderPackagesTab(content); break;
        case 'database': renderDatabaseTab(content); break;
        case 'search': renderSearchTab(content); break;
        case 'workflows': renderWorkflowsTab(content); break;
        case 'secrets': renderSecretsTab(content); break;
        case 'shell': renderShellTab(content); break;
        case 'info': renderInfoTab(content); break;
    }
}


// ══════════════════════════════════════════════════════════════
// PACKAGES TAB
// ══════════════════════════════════════════════════════════════

function renderPackagesTab(el) {
    el.innerHTML = `
        <div class="tool-section">
            <div class="tool-section-title">\ud83d\udce6 Package Manager</div>
            <div class="tool-hint">Install or uninstall packages for your project</div>
            <div style="display:flex;gap:6px;margin-bottom:8px;">
                <select id="pkg-lang" class="tool-input" style="width:120px;">
                    <option value="python">Python (pip)</option>
                    <option value="nodejs">Node.js (npm)</option>
                </select>
                <select id="pkg-action" class="tool-input" style="width:100px;">
                    <option value="install">Install</option>
                    <option value="uninstall">Uninstall</option>
                </select>
            </div>
            <div style="display:flex;gap:6px;">
                <input type="text" id="pkg-names" class="tool-input" placeholder="flask, requests, sqlalchemy..." style="flex:1;">
                <button class="tool-btn" onclick="runPackageAction()">\u25b6 Run</button>
            </div>
            <div id="pkg-results"></div>
        </div>
        <div class="tool-section">
            <div class="tool-section-title">\ud83d\udcdd Quick Install</div>
            <div style="display:flex;flex-wrap:wrap;gap:4px;">
                <button class="tool-btn secondary" onclick="quickInstall('flask')">Flask</button>
                <button class="tool-btn secondary" onclick="quickInstall('requests')">Requests</button>
                <button class="tool-btn secondary" onclick="quickInstall('sqlalchemy')">SQLAlchemy</button>
                <button class="tool-btn secondary" onclick="quickInstall('flask-wtf')">Flask-WTF</button>
                <button class="tool-btn secondary" onclick="quickInstall('bcrypt')">Bcrypt</button>
                <button class="tool-btn secondary" onclick="quickInstall('pytest')">Pytest</button>
            </div>
        </div>
    `;
}

async function runPackageAction() {
    const lang = document.getElementById('pkg-lang').value;
    const action = document.getElementById('pkg-action').value;
    const names = document.getElementById('pkg-names').value.trim();
    if (!names) return;

    const packages = names.split(',').map(p => p.trim()).filter(Boolean);
    const resultsEl = document.getElementById('pkg-results');
    resultsEl.innerHTML = '<div class="tool-result" style="color:#f0883e;">\u23f3 Installing packages...</div>';

    try {
        const resp = await apiRequest('/api/tools/packages', 'POST', {
            project_id: currentProjectId,
            action, language: lang, packages
        });
        let html = '<div class="tool-result">';
        if (resp.results) {
            resp.results.forEach(r => {
                const icon = r.success ? '\u2705' : '\u274c';
                html += `<div>${icon} <strong>${r.package}</strong> ${r.success ? 'OK' : 'FAILED'}</div>`;
                if (r.output) html += `<div style="color:var(--text-secondary);margin-left:20px;">${escapeHtml(r.output.substring(0, 200))}</div>`;
            });
        }
        html += '</div>';
        resultsEl.innerHTML = html;
    } catch (e) {
        resultsEl.innerHTML = `<div class="tool-result" style="color:#f85149;">\u274c ${e.message || e}</div>`;
    }
}

function quickInstall(pkg) {
    document.getElementById('pkg-names').value = pkg;
    document.getElementById('pkg-lang').value = 'python';
    document.getElementById('pkg-action').value = 'install';
    runPackageAction();
}


// ══════════════════════════════════════════════════════════════
// DATABASE TAB
// ══════════════════════════════════════════════════════════════

function renderDatabaseTab(el) {
    el.innerHTML = `
        <div class="tool-section">
            <div class="tool-section-title">\ud83d\uddc4 SQL Database Explorer</div>
            <div class="tool-hint">Query your project's SQLite database</div>
            <div style="display:flex;gap:6px;margin-bottom:8px;">
                <button class="tool-btn secondary" onclick="loadDbSchema()">Show Schema</button>
                <button class="tool-btn secondary" onclick="loadDbTables()">List Tables</button>
            </div>
            <textarea id="sql-query" class="tool-input" rows="3" placeholder="SELECT * FROM users LIMIT 10;" style="font-family:'JetBrains Mono',monospace;"></textarea>
            <div style="display:flex;gap:6px;margin-top:6px;">
                <button class="tool-btn" onclick="executeSql()">\u25b6 Execute SQL</button>
                <select id="sql-db" class="tool-input" style="width:180px;">
                    <option value="">(auto-detect database)</option>
                </select>
            </div>
            <div id="sql-results"></div>
        </div>
    `;
}

async function executeSql() {
    const query = document.getElementById('sql-query').value.trim();
    if (!query) return;
    const dbName = document.getElementById('sql-db').value;
    const resultsEl = document.getElementById('sql-results');
    resultsEl.innerHTML = '<div class="tool-result" style="color:#f0883e;">\u23f3 Executing query...</div>';

    try {
        const resp = await apiRequest('/api/tools/sql', 'POST', {
            project_id: currentProjectId,
            query, db_name: dbName
        });

        // Update db selector
        if (resp.databases) {
            const sel = document.getElementById('sql-db');
            sel.innerHTML = '<option value="">(auto-detect)</option>';
            resp.databases.forEach(db => {
                sel.innerHTML += `<option value="${db}" ${db === resp.database ? 'selected' : ''}>${db}</option>`;
            });
        }

        if (resp.columns) {
            // SELECT result — render table
            let html = `<div class="tool-result" style="padding:0;overflow-x:auto;">`;
            html += `<div style="padding:6px 8px;color:var(--text-secondary);font-size:0.7rem;">${resp.total_rows} row(s) from ${resp.database}</div>`;
            html += '<table class="sql-table"><thead><tr>';
            resp.columns.forEach(c => { html += `<th>${escapeHtml(c)}</th>`; });
            html += '</tr></thead><tbody>';
            resp.rows.forEach(row => {
                html += '<tr>';
                resp.columns.forEach(c => { html += `<td>${escapeHtml(String(row[c] ?? 'NULL'))}</td>`; });
                html += '</tr>';
            });
            html += '</tbody></table></div>';
            resultsEl.innerHTML = html;
        } else {
            resultsEl.innerHTML = `<div class="tool-result" style="color:#3fb950;">\u2705 ${resp.message || 'Query executed'}</div>`;
        }
    } catch (e) {
        resultsEl.innerHTML = `<div class="tool-result" style="color:#f85149;">\u274c ${e.message || e}</div>`;
    }
}

async function loadDbSchema() {
    const resultsEl = document.getElementById('sql-results');
    resultsEl.innerHTML = '<div class="tool-result" style="color:#f0883e;">\u23f3 Loading schema...</div>';
    try {
        const resp = await apiRequest('/api/tools/sql/schema', 'POST', {
            project_id: currentProjectId,
            db_name: document.getElementById('sql-db')?.value || ''
        });

        let html = '<div class="tool-result">';
        html += `<div style="margin-bottom:8px;color:#58a6ff;">Database: ${resp.database}</div>`;
        for (const [table, info] of Object.entries(resp.schema || {})) {
            html += `<div style="margin-bottom:8px;"><strong style="color:#f0883e;">${table}</strong> <span style="color:var(--text-secondary);">(${info.row_count} rows)</span>`;
            html += '<table class="sql-table" style="margin-top:4px;">';
            html += '<tr><th>Column</th><th>Type</th><th>PK</th><th>Not Null</th></tr>';
            info.columns.forEach(col => {
                html += `<tr><td>${col.name}</td><td>${col.type}</td><td>${col.pk ? '\u2705' : ''}</td><td>${col.notnull ? '\u2705' : ''}</td></tr>`;
            });
            html += '</table></div>';
        }
        html += '</div>';
        resultsEl.innerHTML = html;

        // Update db selector
        if (resp.databases) {
            const sel = document.getElementById('sql-db');
            sel.innerHTML = '<option value="">(auto-detect)</option>';
            resp.databases.forEach(db => {
                sel.innerHTML += `<option value="${db}" ${db === resp.database ? 'selected' : ''}>${db}</option>`;
            });
        }
    } catch (e) {
        resultsEl.innerHTML = `<div class="tool-result" style="color:#f85149;">\u274c ${e.message || e}</div>`;
    }
}

async function loadDbTables() {
    document.getElementById('sql-query').value = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;";
    executeSql();
}


// ══════════════════════════════════════════════════════════════
// SEARCH TAB
// ══════════════════════════════════════════════════════════════

function renderSearchTab(el) {
    el.innerHTML = `
        <div class="tool-section">
            <div class="tool-section-title">\ud83d\udd0d Code Search</div>
            <div class="tool-hint">Search your project for code, functions, classes</div>
            <div style="display:flex;gap:6px;margin-bottom:8px;">
                <select id="search-type" class="tool-input" style="width:120px;">
                    <option value="text">Text</option>
                    <option value="function">Functions</option>
                    <option value="class">Classes</option>
                    <option value="regex">Regex</option>
                </select>
                <input type="text" id="search-pattern" class="tool-input" placeholder="e.g. login, User, def create..." style="flex:1;">
            </div>
            <div style="display:flex;gap:6px;">
                <input type="text" id="search-file-filter" class="tool-input" placeholder="File filter (e.g. *.py)" style="flex:1;">
                <button class="tool-btn" onclick="runCodeSearch()">\ud83d\udd0d Search</button>
            </div>
            <div id="search-results"></div>
        </div>
    `;
}

async function runCodeSearch() {
    const query = document.getElementById('search-pattern').value.trim();
    if (!query) return;
    const type = document.getElementById('search-type').value;
    const filePattern = document.getElementById('search-file-filter').value.trim();
    const resultsEl = document.getElementById('search-results');
    resultsEl.innerHTML = '<div class="tool-result" style="color:#f0883e;">\u23f3 Searching...</div>';

    try {
        const resp = await apiRequest('/api/tools/search', 'POST', {
            project_id: currentProjectId,
            query, type, file_pattern: filePattern
        });

        if (!resp.results || resp.results.length === 0) {
            resultsEl.innerHTML = '<div class="tool-result" style="color:var(--text-secondary);">No results found</div>';
            return;
        }

        let html = `<div style="margin-top:8px;color:var(--text-secondary);font-size:0.7rem;">${resp.total} result(s)${resp.truncated ? ' (truncated)' : ''}</div>`;
        html += '<div class="tool-result" style="padding:0;">';
        resp.results.forEach(r => {
            html += `<div class="search-result" onclick="openFileAtLine('${escapeHtml(r.file)}', ${r.line})">
                <span class="search-file">${escapeHtml(r.file)}</span>
                <span class="search-line">:${r.line}</span>
                <div class="search-content">${escapeHtml(r.content)}</div>
            </div>`;
        });
        html += '</div>';
        resultsEl.innerHTML = html;
    } catch (e) {
        resultsEl.innerHTML = `<div class="tool-result" style="color:#f85149;">\u274c ${e.message || e}</div>`;
    }
}

function openFileAtLine(file, line) {
    // Use the existing editor file opening function if available
    if (typeof openFile === 'function') {
        openFile(file);
        // After file loads, go to line
        setTimeout(() => {
            if (window.monacoEditor) {
                window.monacoEditor.revealLineInCenter(line);
                window.monacoEditor.setPosition({ lineNumber: line, column: 1 });
            }
        }, 500);
    }
}


// ══════════════════════════════════════════════════════════════
// WORKFLOWS TAB
// ══════════════════════════════════════════════════════════════

function renderWorkflowsTab(el) {
    el.innerHTML = `
        <div class="tool-section">
            <div class="tool-section-title">\u2699\ufe0f Workflow Manager</div>
            <div class="tool-hint">Configure how your project runs (like Replit workflows)</div>
            <div id="workflows-list" style="margin-bottom:10px;"><div style="color:var(--text-secondary);">Loading...</div></div>
            <div style="border-top:1px solid var(--border-color, #30363d);padding-top:10px;">
                <div class="tool-section-title">Add Workflow</div>
                <input type="text" id="wf-name" class="tool-input" placeholder="Workflow name (e.g. Server, Tests)" style="margin-bottom:6px;">
                <input type="text" id="wf-command" class="tool-input" placeholder="Command (e.g. python app.py, npm run dev)" style="margin-bottom:6px;">
                <div style="display:flex;gap:6px;align-items:center;">
                    <input type="number" id="wf-port" class="tool-input" placeholder="Port (optional)" style="width:100px;">
                    <label style="font-size:0.72rem;color:var(--text-secondary);display:flex;align-items:center;gap:4px;">
                        <input type="checkbox" id="wf-run-btn"> Run Button
                    </label>
                    <button class="tool-btn" onclick="addWorkflow()">+ Add</button>
                </div>
            </div>
        </div>
    `;
    loadWorkflows();
}

async function loadWorkflows() {
    try {
        const resp = await apiRequest(`/api/tools/workflows?project_id=${currentProjectId}`, 'GET');
        const listEl = document.getElementById('workflows-list');
        if (!resp.workflows || resp.workflows.length === 0) {
            listEl.innerHTML = '<div style="color:var(--text-secondary);font-size:0.75rem;">No workflows configured yet</div>';
            return;
        }
        let html = '';
        resp.workflows.forEach(wf => {
            html += `<div class="workflow-item">
                <div style="flex:1;">
                    <div style="font-weight:600;color:var(--text-primary);">${escapeHtml(wf.name)} ${wf.is_run_button ? '<span style="color:#3fb950;font-size:0.68rem;">\u25b6 RUN</span>' : ''}</div>
                    <div style="font-family:'JetBrains Mono',monospace;font-size:0.72rem;color:var(--text-secondary);">${escapeHtml(wf.command)}</div>
                    ${wf.wait_for_port ? `<div style="font-size:0.68rem;color:#f0883e;">Port: ${wf.wait_for_port}</div>` : ''}
                </div>
                <button class="tool-btn danger" style="padding:3px 8px;font-size:0.68rem;" onclick="removeWorkflow('${escapeHtml(wf.name)}')">\u2715</button>
            </div>`;
        });
        listEl.innerHTML = html;
    } catch (e) {
        document.getElementById('workflows-list').innerHTML = `<div style="color:#f85149;">\u274c ${e.message || e}</div>`;
    }
}

async function addWorkflow() {
    const name = document.getElementById('wf-name').value.trim();
    const command = document.getElementById('wf-command').value.trim();
    const port = document.getElementById('wf-port').value;
    const isRunBtn = document.getElementById('wf-run-btn').checked;

    if (!name || !command) return;

    try {
        await apiRequest('/api/tools/workflows', 'POST', {
            project_id: currentProjectId,
            name, command,
            wait_for_port: port ? parseInt(port) : null,
            is_run_button: isRunBtn
        });
        document.getElementById('wf-name').value = '';
        document.getElementById('wf-command').value = '';
        document.getElementById('wf-port').value = '';
        loadWorkflows();
    } catch (e) {
        alert('Error: ' + (e.message || e));
    }
}

async function removeWorkflow(name) {
    try {
        await apiRequest('/api/tools/workflows', 'DELETE', {
            project_id: currentProjectId, name
        });
        loadWorkflows();
    } catch (e) {
        alert('Error: ' + (e.message || e));
    }
}


// ══════════════════════════════════════════════════════════════
// SECRETS TAB
// ══════════════════════════════════════════════════════════════

function renderSecretsTab(el) {
    el.innerHTML = `
        <div class="tool-section">
            <div class="tool-section-title">\ud83d\udd10 Secrets & Environment Variables</div>
            <div class="tool-hint">Manage .env file for your project (values are never exposed in UI)</div>
            <div id="secrets-list" style="margin-bottom:10px;"><div style="color:var(--text-secondary);">Loading...</div></div>
            <div style="border-top:1px solid var(--border-color, #30363d);padding-top:10px;">
                <div class="tool-section-title">Add Secret</div>
                <div style="display:flex;gap:6px;margin-bottom:6px;">
                    <input type="text" id="secret-key" class="tool-input" placeholder="KEY_NAME" style="flex:1;">
                    <input type="password" id="secret-value" class="tool-input" placeholder="Value" style="flex:1;">
                </div>
                <button class="tool-btn" onclick="addSecret()">+ Add Secret</button>
            </div>
        </div>
    `;
    loadSecrets();
}

async function loadSecrets() {
    try {
        const resp = await apiRequest(`/api/tools/secrets?project_id=${currentProjectId}`, 'GET');
        const listEl = document.getElementById('secrets-list');
        if (!resp.secrets || resp.secrets.length === 0) {
            listEl.innerHTML = '<div style="color:var(--text-secondary);font-size:0.75rem;">No secrets configured</div>';
            return;
        }
        let html = '';
        resp.secrets.forEach(s => {
            html += `<div class="secret-item">
                <div style="font-family:'JetBrains Mono',monospace;font-size:0.75rem;">\ud83d\udd11 ${escapeHtml(s.key)}</div>
                <button class="tool-btn danger" style="padding:2px 8px;font-size:0.65rem;" onclick="deleteSecret('${escapeHtml(s.key)}')">\u2715</button>
            </div>`;
        });
        listEl.innerHTML = html;
    } catch (e) {
        document.getElementById('secrets-list').innerHTML = `<div style="color:#f85149;">\u274c ${e.message || e}</div>`;
    }
}

async function addSecret() {
    const key = document.getElementById('secret-key').value.trim();
    const value = document.getElementById('secret-value').value;
    if (!key) return;

    try {
        await apiRequest('/api/tools/secrets', 'POST', {
            project_id: currentProjectId, key, value
        });
        document.getElementById('secret-key').value = '';
        document.getElementById('secret-value').value = '';
        loadSecrets();
    } catch (e) {
        alert('Error: ' + (e.message || e));
    }
}

async function deleteSecret(key) {
    try {
        await apiRequest('/api/tools/secrets', 'DELETE', {
            project_id: currentProjectId, key
        });
        loadSecrets();
    } catch (e) {
        alert('Error: ' + (e.message || e));
    }
}


// ══════════════════════════════════════════════════════════════
// SHELL TAB
// ══════════════════════════════════════════════════════════════

function renderShellTab(el) {
    el.innerHTML = `
        <div class="tool-section">
            <div class="tool-section-title">\ud83d\udcbb Quick Shell</div>
            <div class="tool-hint">Run commands in your project directory</div>
            <div style="display:flex;gap:6px;">
                <input type="text" id="shell-cmd" class="tool-input" placeholder="ls -la, pip list, cat app.py..." style="flex:1;"
                    onkeydown="if(event.key==='Enter')runShellCommand();">
                <button class="tool-btn" onclick="runShellCommand()">\u25b6 Run</button>
            </div>
            <div id="shell-output"></div>
        </div>
        <div class="tool-section">
            <div class="tool-section-title">Quick Commands</div>
            <div style="display:flex;flex-wrap:wrap;gap:4px;">
                <button class="tool-btn secondary" onclick="quickShell('ls -la')">ls -la</button>
                <button class="tool-btn secondary" onclick="quickShell('pip list')">pip list</button>
                <button class="tool-btn secondary" onclick="quickShell('python --version')">Python ver</button>
                <button class="tool-btn secondary" onclick="quickShell('cat requirements.txt')">requirements</button>
                <button class="tool-btn secondary" onclick="quickShell('du -sh .')">Disk usage</button>
                <button class="tool-btn secondary" onclick="quickShell('git status')">git status</button>
            </div>
        </div>
    `;
}

async function runShellCommand() {
    const cmd = document.getElementById('shell-cmd').value.trim();
    if (!cmd) return;
    const outputEl = document.getElementById('shell-output');
    outputEl.innerHTML = '<div class="tool-result" style="color:#f0883e;">\u23f3 Running...</div>';

    try {
        const resp = await apiRequest('/api/tools/shell', 'POST', {
            project_id: currentProjectId, command: cmd
        });
        const color = resp.success ? '#3fb950' : '#f85149';
        let html = `<div class="tool-result">`;
        html += `<div style="color:${color};margin-bottom:4px;">${resp.success ? '\u2705' : '\u274c'} Exit code: ${resp.exit_code}</div>`;
        if (resp.stdout) html += `<div style="color:var(--text-primary);">${escapeHtml(resp.stdout)}</div>`;
        if (resp.stderr) html += `<div style="color:#f85149;margin-top:4px;">${escapeHtml(resp.stderr)}</div>`;
        html += '</div>';
        outputEl.innerHTML = html;
    } catch (e) {
        outputEl.innerHTML = `<div class="tool-result" style="color:#f85149;">\u274c ${e.message || e}</div>`;
    }
}

function quickShell(cmd) {
    document.getElementById('shell-cmd').value = cmd;
    runShellCommand();
}


// ══════════════════════════════════════════════════════════════
// INFO TAB
// ══════════════════════════════════════════════════════════════

function renderInfoTab(el) {
    el.innerHTML = '<div class="tool-result" style="color:#f0883e;">\u23f3 Loading project info...</div>';
    loadProjectInfo(el);
}

async function loadProjectInfo(el) {
    try {
        const resp = await apiRequest(`/api/tools/project-info?project_id=${currentProjectId}`, 'GET');
        let html = '<div class="tool-section">';
        html += `<div class="tool-section-title">\u2139\ufe0f Project Information</div>`;
        html += `<div class="tool-result">`;
        html += `<div><strong>Name:</strong> ${escapeHtml(resp.name)}</div>`;
        html += `<div><strong>Language:</strong> ${escapeHtml(resp.language)}</div>`;
        html += `<div><strong>Files:</strong> ${resp.file_count}</div>`;
        html += `<div><strong>Size:</strong> ${resp.total_size_human}</div>`;

        // Extensions
        if (resp.extensions && Object.keys(resp.extensions).length > 0) {
            html += `<div style="margin-top:8px;"><strong>File Types:</strong></div>`;
            const sorted = Object.entries(resp.extensions).sort((a, b) => b[1] - a[1]);
            sorted.forEach(([ext, count]) => {
                html += `<div style="margin-left:12px;">${ext}: ${count}</div>`;
            });
        }

        // Dependencies
        if (resp.dependencies && Object.keys(resp.dependencies).length > 0) {
            html += `<div style="margin-top:8px;"><strong>Dependencies:</strong></div>`;
            for (const [lang, deps] of Object.entries(resp.dependencies)) {
                html += `<div style="margin-left:12px;color:#58a6ff;">${lang}:</div>`;
                deps.forEach(d => { html += `<div style="margin-left:24px;">${escapeHtml(d)}</div>`; });
            }
        }

        // Databases
        if (resp.databases && resp.databases.length > 0) {
            html += `<div style="margin-top:8px;"><strong>Databases:</strong></div>`;
            resp.databases.forEach(db => { html += `<div style="margin-left:12px;">\ud83d\uddc4 ${escapeHtml(db)}</div>`; });
        }

        html += '</div></div>';
        el.innerHTML = html;
    } catch (e) {
        el.innerHTML = `<div class="tool-result" style="color:#f85149;">\u274c ${e.message || e}</div>`;
    }
}


// ══════════════════════════════════════════════════════════════
// BOTTOM PANEL: DATABASE TAB
// ══════════════════════════════════════════════════════════════

function initDatabasePanel() {
    const panel = document.getElementById('database-panel');
    if (!panel) return;
    panel.innerHTML = `
        <div style="display:flex;gap:6px;margin-bottom:8px;">
            <button class="tool-btn secondary" onclick="bottomLoadSchema()">Schema</button>
            <button class="tool-btn secondary" onclick="bottomListTables()">Tables</button>
            <select id="bottom-sql-db" class="tool-input" style="width:150px;padding:4px 6px;font-size:0.78rem;">
                <option value="">(auto-detect)</option>
            </select>
        </div>
        <div style="display:flex;gap:6px;margin-bottom:8px;">
            <input type="text" id="bottom-sql-query" class="tool-input" placeholder="SELECT * FROM users LIMIT 10;" style="flex:1;padding:5px 8px;font-size:0.78rem;"
                onkeydown="if(event.key==='Enter')bottomExecSql();">
            <button class="tool-btn" onclick="bottomExecSql()" style="padding:4px 10px;font-size:0.72rem;">\u25b6 Run</button>
        </div>
        <div id="bottom-sql-results"></div>
    `;
}

async function bottomExecSql() {
    const query = document.getElementById('bottom-sql-query').value.trim();
    if (!query) return;
    const dbName = document.getElementById('bottom-sql-db')?.value || '';
    const resultsEl = document.getElementById('bottom-sql-results');
    resultsEl.innerHTML = '<div style="color:#f0883e;">\u23f3 Executing...</div>';

    try {
        const resp = await apiRequest('/api/tools/sql', 'POST', {
            project_id: currentProjectId,
            query, db_name: dbName
        });

        if (resp.databases) {
            const sel = document.getElementById('bottom-sql-db');
            if (sel) {
                sel.innerHTML = '<option value="">(auto-detect)</option>';
                resp.databases.forEach(db => {
                    sel.innerHTML += `<option value="${db}" ${db === resp.database ? 'selected' : ''}>${db}</option>`;
                });
            }
        }

        if (resp.columns) {
            let html = `<div style="font-size:0.7rem;color:var(--text-secondary);margin-bottom:4px;">${resp.total_rows} row(s)</div>`;
            html += '<table class="sql-table"><thead><tr>';
            resp.columns.forEach(c => { html += `<th>${escapeHtml(c)}</th>`; });
            html += '</tr></thead><tbody>';
            resp.rows.slice(0, 50).forEach(row => {
                html += '<tr>';
                resp.columns.forEach(c => { html += `<td>${escapeHtml(String(row[c] ?? 'NULL'))}</td>`; });
                html += '</tr>';
            });
            html += '</tbody></table>';
            resultsEl.innerHTML = html;
        } else {
            resultsEl.innerHTML = `<div style="color:#3fb950;">\u2705 ${resp.message || 'Done'}</div>`;
        }
    } catch (e) {
        resultsEl.innerHTML = `<div style="color:#f85149;">\u274c ${e.message || e}</div>`;
    }
}

async function bottomLoadSchema() {
    const resultsEl = document.getElementById('bottom-sql-results');
    resultsEl.innerHTML = '<div style="color:#f0883e;">\u23f3 Loading schema...</div>';
    try {
        const resp = await apiRequest('/api/tools/sql/schema', 'POST', {
            project_id: currentProjectId,
            db_name: document.getElementById('bottom-sql-db')?.value || ''
        });
        let html = '';
        for (const [table, info] of Object.entries(resp.schema || {})) {
            html += `<div style="margin-bottom:6px;"><strong style="color:#f0883e;">${table}</strong> (${info.row_count} rows)<br>`;
            info.columns.forEach(col => {
                html += `<span style="color:var(--text-secondary);font-size:0.72rem;margin-left:8px;">${col.name} <span style="color:#58a6ff;">${col.type}</span>${col.pk ? ' PK' : ''}</span><br>`;
            });
            html += '</div>';
        }
        resultsEl.innerHTML = html || '<div style="color:var(--text-secondary);">No tables found</div>';
    } catch (e) {
        resultsEl.innerHTML = `<div style="color:#f85149;">\u274c ${e.message || e}</div>`;
    }
}

function bottomListTables() {
    document.getElementById('bottom-sql-query').value = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;";
    bottomExecSql();
}


// ══════════════════════════════════════════════════════════════
// BOTTOM PANEL: SEARCH TAB
// ══════════════════════════════════════════════════════════════

function initSearchPanel() {
    const panel = document.getElementById('search-panel');
    if (!panel) return;
    panel.innerHTML = `
        <div style="display:flex;gap:6px;margin-bottom:8px;">
            <select id="bottom-search-type" class="tool-input" style="width:100px;padding:4px 6px;font-size:0.78rem;">
                <option value="text">Text</option>
                <option value="function">Functions</option>
                <option value="class">Classes</option>
                <option value="regex">Regex</option>
            </select>
            <input type="text" id="bottom-search-query" class="tool-input" placeholder="Search code..." style="flex:1;padding:5px 8px;font-size:0.78rem;"
                onkeydown="if(event.key==='Enter')bottomSearchCode();">
            <button class="tool-btn" onclick="bottomSearchCode()" style="padding:4px 10px;font-size:0.72rem;">\ud83d\udd0d</button>
        </div>
        <div id="bottom-search-results"></div>
    `;
}

async function bottomSearchCode() {
    const query = document.getElementById('bottom-search-query').value.trim();
    if (!query) return;
    const type = document.getElementById('bottom-search-type').value;
    const resultsEl = document.getElementById('bottom-search-results');
    resultsEl.innerHTML = '<div style="color:#f0883e;">\u23f3 Searching...</div>';

    try {
        const resp = await apiRequest('/api/tools/search', 'POST', {
            project_id: currentProjectId, query, type
        });

        if (!resp.results || resp.results.length === 0) {
            resultsEl.innerHTML = '<div style="color:var(--text-secondary);">No results</div>';
            return;
        }

        let html = `<div style="font-size:0.7rem;color:var(--text-secondary);margin-bottom:4px;">${resp.total} result(s)</div>`;
        resp.results.forEach(r => {
            html += `<div class="search-result" onclick="openFileAtLine('${escapeHtml(r.file)}', ${r.line})">
                <span class="search-file">${escapeHtml(r.file)}</span><span class="search-line">:${r.line}</span>
                <div class="search-content">${escapeHtml(r.content)}</div>
            </div>`;
        });
        resultsEl.innerHTML = html;
    } catch (e) {
        resultsEl.innerHTML = `<div style="color:#f85149;">\u274c ${e.message || e}</div>`;
    }
}


// ══════════════════════════════════════════════════════════════
// UTILITIES
// ══════════════════════════════════════════════════════════════

function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Initialize bottom panels when they become visible
const origSwitchBottomTab = typeof switchBottomTab === 'function' ? switchBottomTab : null;
document.addEventListener('DOMContentLoaded', function () {
    // Hook into bottom tab switching to initialize our panels
    const observer = new MutationObserver(function () {
        const dbPane = document.getElementById('database-pane');
        const searchPane = document.getElementById('search-pane');
        if (dbPane && dbPane.classList.contains('active') && !dbPane.dataset.initialized) {
            dbPane.dataset.initialized = 'true';
            initDatabasePanel();
        }
        if (searchPane && searchPane.classList.contains('active') && !searchPane.dataset.initialized) {
            searchPane.dataset.initialized = 'true';
            initSearchPanel();
        }
    });
    observer.observe(document.body, { subtree: true, attributes: true, attributeFilter: ['class'] });
});
