// YubiLab Dashboard Module
const API_BASE = window.location.origin;

const LANG_ICONS = {
    python: '🐍', javascript: '🟨', html: '🌐', c: '⚙️', cpp: '⚙️',
    java: '☕', go: '🐹', php: '🐘', rust: '🦀'
};

let currentUser = null;

// Check auth
(async function init() {
    try {
        const res = await fetch(`${API_BASE}/api/auth/me`, { credentials: 'include' });
        if (!res.ok) {
            window.location.href = '/login';
            return;
        }
        const data = await res.json();
        currentUser = data.user;
        document.getElementById('user-name').textContent = currentUser.username;
        document.getElementById('user-avatar').textContent = currentUser.username[0].toUpperCase();
        loadProjects();
    } catch (e) {
        window.location.href = '/login';
    }
})();

async function loadProjects() {
    try {
        const res = await fetch(`${API_BASE}/api/projects`, { credentials: 'include' });
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
        const res = await fetch(`${API_BASE}/api/projects`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
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
        const res = await fetch(`${API_BASE}/api/projects/${id}`, {
            method: 'DELETE',
            credentials: 'include'
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
        const res = await fetch(`${API_BASE}/api/projects/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
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
        await fetch(`${API_BASE}/api/auth/logout`, {
            method: 'POST',
            credentials: 'include'
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

// Close modal on escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') hideCreateModal();
});

// Close modal on outside click
document.getElementById('create-modal').addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay')) hideCreateModal();
});
