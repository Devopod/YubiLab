// YubiLab Auth Module
const API_BASE = window.location.origin;

// Check if already logged in
(async function checkAuth() {
    try {
        const res = await fetch(`${API_BASE}/api/auth/me`, { credentials: 'include' });
        if (res.ok) {
            window.location.href = '/';
        }
    } catch (e) {}

    // Only show login page if on login page
    if (!window.location.pathname.includes('login')) {
        try {
            const res = await fetch(`${API_BASE}/api/auth/me`, { credentials: 'include' });
            if (!res.ok) {
                window.location.href = '/login';
            }
        } catch (e) {
            window.location.href = '/login';
        }
    }
})();

function switchTab(tab) {
    document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`.auth-tab:${tab === 'login' ? 'first-child' : 'last-child'}`).classList.add('active');

    document.getElementById('login-form').style.display = tab === 'login' ? 'flex' : 'none';
    document.getElementById('register-form').style.display = tab === 'register' ? 'flex' : 'none';
    document.getElementById('auth-error').style.display = 'none';
}

function showError(msg) {
    const el = document.getElementById('auth-error');
    el.textContent = msg;
    el.style.display = 'block';
}

async function handleLogin(e) {
    e.preventDefault();
    const btn = document.getElementById('login-btn');
    btn.disabled = true;
    btn.textContent = 'Logging in...';

    try {
        const res = await fetch(`${API_BASE}/api/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
                username: document.getElementById('login-username').value,
                password: document.getElementById('login-password').value,
            })
        });

        const data = await res.json();
        if (res.ok) {
            window.location.href = '/';
        } else {
            showError(data.error || 'Login failed');
        }
    } catch (e) {
        showError('Connection error. Please try again.');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Login';
    }
}

async function handleRegister(e) {
    e.preventDefault();
    const btn = document.getElementById('reg-btn');
    btn.disabled = true;
    btn.textContent = 'Creating account...';

    try {
        const res = await fetch(`${API_BASE}/api/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
                username: document.getElementById('reg-username').value,
                email: document.getElementById('reg-email').value,
                password: document.getElementById('reg-password').value,
            })
        });

        const data = await res.json();
        if (res.ok) {
            window.location.href = '/';
        } else {
            showError(data.error || 'Registration failed');
        }
    } catch (e) {
        showError('Connection error. Please try again.');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Create Account';
    }
}
