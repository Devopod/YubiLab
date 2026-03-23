// YubiLab Dashboard Module
// Use relative URLs to avoid issues with basic-auth tunnel proxies

const LANG_ICONS = {
    python: '🐍', javascript: '🟨', html: '🌐', c: '⚙️', cpp: '⚙️',
    java: '☕', go: '🐹', php: '🐘', rust: '🦀'
};

let currentUser = null;

// Check auth
(async function init() {
    try {
        const res = await apiFetch(`/api/auth/me`);
        if (!res.ok) {
            window.location.href = '/login';
            return;
        }
        const data = await res.json();
        currentUser = data.user;
        document.getElementById('user-name').textContent = currentUser.username;
        document.getElementById('user-avatar').textContent = currentUser.username[0].toUpperCase();
        loadProjects();
        loadDashboardDeployments();
    } catch (e) {
        window.location.href = '/login';
    }
})();

async function loadProjects() {
    try {
        const res = await apiFetch(`/api/projects`);
        const data = await res.json();
        renderProjects(data.projects || []);
    } catch (e) {
        showToast('Failed to load projects', 'error');
    }
}

function renderProjects(projects) {
    const grid = document.getElementById('projects-grid');
    const empty = document.getElementById('empty-state');

    if (projects.length === 0) {
        grid.innerHTML = '';
        empty.style.display = 'block';
        return;
    }

    empty.style.display = 'none';
    grid.innerHTML = projects.map(p => `
        <div class="project-card" onclick="openProject(${p.id})">
            <div class="project-card-header">
                <div class="project-card-icon">${LANG_ICONS[p.language] || '📄'}</div>
                <div class="project-card-actions">
                    <button onclick="event.stopPropagation(); renameProject(${p.id}, '${escapeHtml(p.name)}')" title="Rename">✏️</button>
                    <button onclick="event.stopPropagation(); deleteProject(${p.id}, '${escapeHtml(p.name)}')" title="Delete">🗑</button>
                </div>
            </div>
            <h3>${escapeHtml(p.name)}</h3>
            ${p.description ? `<p style="color:var(--text-muted);font-size:0.8rem;margin-top:4px;">${escapeHtml(p.description)}</p>` : ''}
            <div class="project-meta">
                <span class="project-lang-badge">${LANG_ICONS[p.language] || ''} ${p.language}</span>
                <span>${formatDate(p.created_at)}</span>
            </div>
        </div>
    `).join('');
}

function openProject(id) {
    window.location.href = `/editor?project=${id}`;
}

function showCreateModal() {
    document.getElementById('create-modal').classList.add('active');
    document.getElementById('project-name').focus();
}

function hideCreateModal() {
    document.getElementById('create-modal').classList.remove('active');
}

async function handleCreateProject(e) {
    e.preventDefault();
    const name = document.getElementById('project-name').value.trim();
    const language = document.getElementById('project-language').value;
    const description = document.getElementById('project-desc').value.trim();

    if (!name) return;

    try {
        const res = await apiFetch(`/api/projects`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, language, description })
        });

        const data = await res.json();
        if (res.ok) {
            hideCreateModal();
            showToast('Project created!', 'success');
            // Open the project immediately
            openProject(data.project.id);
        } else {
            showToast(data.error || 'Failed to create project', 'error');
        }
    } catch (e) {
        showToast('Connection error', 'error');
    }
}

async function deleteProject(id, name) {
    if (!confirm(`Delete project "${name}"? This cannot be undone.`)) return;

    try {
        const res = await apiFetch(`/api/projects/${id}`, {
            method: 'DELETE',
        });

        if (res.ok) {
            showToast('Project deleted', 'success');
            loadProjects();
        } else {
            const data = await res.json();
            showToast(data.error || 'Failed to delete', 'error');
        }
    } catch (e) {
        showToast('Connection error', 'error');
    }
}

async function renameProject(id, currentName) {
    const newName = prompt('New project name:', currentName);
    if (!newName || newName === currentName) return;

    try {
        const res = await apiFetch(`/api/projects/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: newName })
        });

        if (res.ok) {
            showToast('Project renamed', 'success');
            loadProjects();
        } else {
            const data = await res.json();
            showToast(data.error || 'Failed to rename', 'error');
        }
    } catch (e) {
        showToast('Connection error', 'error');
    }
}

async function handleLogout() {
    try {
        await apiFetch(`/api/auth/logout`, {
            method: 'POST',
        });
    } catch (e) {}
    window.location.href = '/login';
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

function formatDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

// ============================================
// DEPLOYMENTS MANAGEMENT
// ============================================

async function loadDashboardDeployments() {
    const container = document.getElementById('dashboard-deployments');
    const empty = document.getElementById('deployments-empty');
    if (!container) return;

    try {
        const res = await apiFetch(`/api/deployments`);
        const deployments = await res.json();

        if (!deployments.length) {
            container.innerHTML = '';
            empty.style.display = 'block';
            return;
        }

        empty.style.display = 'none';
        container.innerHTML = deployments.map(dep => {
            const statusColor = dep.status === 'running' ? '#3fb950' : dep.status === 'crashed' ? '#f85149' : '#8b949e';
            const statusIcon = dep.status === 'running' ? '\ud83d\udfe2' : dep.status === 'crashed' ? '\ud83d\udd34' : '\u26aa';
            const previewUrl = `/preview-app/${dep.project_id}`;
            const createdAt = dep.created_at ? new Date(dep.created_at).toLocaleString() : '';
            const langIcon = LANG_ICONS[dep.project_language] || '\ud83d\udcc4';

            return `
            <div class="project-card" style="cursor:default;">
                <div class="project-card-header">
                    <div class="project-card-icon">${langIcon}</div>
                    <div style="display:flex;align-items:center;gap:6px;">
                        <span style="background:color-mix(in srgb, ${statusColor} 20%, transparent);color:${statusColor};padding:2px 8px;border-radius:12px;font-size:0.7rem;font-weight:600;">${statusIcon} ${dep.status}</span>
                    </div>
                </div>
                <h3>${escapeHtml(dep.project_name || 'Project #' + dep.project_id)}</h3>
                <div style="display:flex;gap:10px;font-size:0.8rem;color:var(--text-muted);margin:6px 0 10px;">
                    <span>Port: <strong style="color:var(--text-secondary);">${dep.deploy_port}</strong></span>
                    <span>PID: <strong style="color:var(--text-secondary);">${dep.deploy_pid || '-'}</strong></span>
                </div>
                <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:auto;">
                    ${dep.status === 'running' ? `
                        <button onclick="event.stopPropagation(); window.open('${previewUrl}','_blank')" class="btn btn-sm" style="background:var(--accent-blue);color:white;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:0.75rem;">\ud83c\udf10 Open</button>
                        <button onclick="event.stopPropagation(); dashRestartDeploy(${dep.project_id})" class="btn btn-sm" style="background:var(--accent-purple);color:white;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:0.75rem;">\ud83d\udd04 Restart</button>
                        <button onclick="event.stopPropagation(); dashStopDeploy(${dep.project_id})" class="btn btn-sm" style="background:var(--accent-orange, #d29922);color:white;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:0.75rem;">\u23f9 Stop</button>
                    ` : `
                        <button onclick="event.stopPropagation(); dashRedeployProject(${dep.project_id})" class="btn btn-sm" style="background:var(--accent-green);color:white;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:0.75rem;">\ud83d\ude80 Redeploy</button>
                    `}
                    <button onclick="event.stopPropagation(); dashDeleteDeploy(${dep.id})" class="btn btn-sm" style="background:var(--danger);color:white;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:0.75rem;">\ud83d\uddd1 Delete</button>
                </div>
                <div class="project-meta">
                    <span class="project-lang-badge">${langIcon} ${dep.project_language || 'unknown'}</span>
                    <span>${createdAt}</span>
                </div>
            </div>`;
        }).join('');
    } catch (e) {
        container.innerHTML = `<div style="color:var(--danger);padding:20px;text-align:center;">Failed to load deployments</div>`;
    }
}

async function dashStopDeploy(projectId) {
    try {
        const res = await apiFetch(`/api/deploy/${projectId}`, { method: 'DELETE' });
        if (res.ok) { showToast('Deployment stopped', 'success'); loadDashboardDeployments(); }
        else { const d = await res.json(); showToast(d.error || 'Failed', 'error'); }
    } catch (e) { showToast('Error: ' + e.message, 'error'); }
}

async function dashRestartDeploy(projectId) {
    showToast('Restarting...', 'info');
    try {
        const res = await apiFetch(`/api/deploy/${projectId}/restart`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
        });
        const d = await res.json();
        if (res.ok) { showToast(`Restarted on port ${d.port}!`, 'success'); loadDashboardDeployments(); }
        else { showToast(d.error || 'Failed', 'error'); }
    } catch (e) { showToast('Error: ' + e.message, 'error'); }
}

async function dashRedeployProject(projectId) {
    showToast('Deploying...', 'info');
    try {
        const res = await apiFetch(`/api/deploy/${projectId}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
        });
        const d = await res.json();
        if (res.ok) { showToast(`Deployed on port ${d.port}!`, 'success'); loadDashboardDeployments(); }
        else { showToast(d.error || 'Failed', 'error'); }
    } catch (e) { showToast('Error: ' + e.message, 'error'); }
}

async function dashDeleteDeploy(deployId) {
    if (!confirm('Delete this deployment record?')) return;
    try {
        const res = await apiFetch(`/api/deploy/${deployId}/delete`, { method: 'DELETE' });
        if (res.ok) { showToast('Deployment deleted', 'success'); loadDashboardDeployments(); }
        else { const d = await res.json(); showToast(d.error || 'Failed', 'error'); }
    } catch (e) { showToast('Error: ' + e.message, 'error'); }
}

// Close modal on escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') hideCreateModal();
});

// Close modal on outside click
document.getElementById('create-modal').addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay')) hideCreateModal();
});
