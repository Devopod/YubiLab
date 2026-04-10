// YubiLab API Helper
// Uses XMLHttpRequest instead of fetch to work around browser security restriction
// that blocks fetch() when the page URL contains basic-auth credentials (user:pass@host)

// Internal single-attempt XHR call
function _apiFetchOnce(url, options = {}) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        const method = (options.method || 'GET').toUpperCase();
        xhr.open(method, url, true);
        xhr.timeout = options.timeout || 120000;  // 2 min default (agent calls pass 10 min)

        // Set headers
        if (options.headers) {
            for (const [key, value] of Object.entries(options.headers)) {
                xhr.setRequestHeader(key, value);
            }
        }
        // Always skip ngrok browser warning (free tier shows HTML interstitial)
        xhr.setRequestHeader('ngrok-skip-browser-warning', 'true');

        xhr.onload = function () {
            // Detect ngrok/proxy 502/503/504 errors (they return HTML, not JSON)
            // These are tunnel-level errors, NOT backend errors
            const isGatewayError = xhr.status === 502 || xhr.status === 503 || xhr.status === 504;
            const text = xhr.responseText || '';
            const isHtmlError = text.includes('<!DOCTYPE') || text.includes('<html');
            if (isGatewayError || (isHtmlError && xhr.status !== 200)) {
                // Signal this as a retryable gateway error
                reject({ retryable: true, status: xhr.status, text: text });
                return;
            }

            const response = {
                ok: xhr.status >= 200 && xhr.status < 300,
                status: xhr.status,
                statusText: xhr.statusText,
                headers: {
                    get: (name) => xhr.getResponseHeader(name),
                },
                text: () => Promise.resolve(xhr.responseText),
                json: () => {
                    try {
                        return Promise.resolve(JSON.parse(xhr.responseText));
                    } catch (e) {
                        const text = xhr.responseText || '';
                        let errorMsg = 'Server returned an invalid response';
                        if (xhr.status === 0) {
                            errorMsg = 'Cannot connect to server. Please check if the backend is running.';
                        } else if (xhr.status === 401) {
                            errorMsg = 'Session expired. Please log in again.';
                        } else if (text.includes('ngrok') && (text.includes('<!DOCTYPE') || text.includes('<html'))) {
                            errorMsg = 'Connecting to server... Please try again.';
                        } else if (text.includes('<!DOCTYPE') || text.includes('<html')) {
                            errorMsg = 'Backend server returned unexpected HTML. It may be restarting.';
                        } else if (text.length === 0) {
                            errorMsg = 'Server returned an empty response.';
                        }
                        return Promise.reject(new SyntaxError(errorMsg));
                    }
                },
            };
            resolve(response);
        };

        xhr.onerror = function () {
            reject({ retryable: true, status: 0, text: 'Connection error' });
        };

        xhr.ontimeout = function () {
            reject(new TypeError('Request timed out. The server may be busy - please try again.'));
        };

        xhr.send(options.body || null);
    });
}

// apiFetch with automatic retry on gateway/tunnel errors (502, 503, 504, connection errors)
// Ngrok free tier often returns 502/503 HTML when upstream is slow — this retries transparently
async function apiFetch(url, options = {}) {
    const maxRetries = options.maxRetries || 5;
    const retryDelay = options.retryDelay || 3000;  // 3 seconds between retries
    let lastError = null;

    for (let attempt = 0; attempt < maxRetries; attempt++) {
        try {
            return await _apiFetchOnce(url, options);
        } catch (e) {
            if (e && e.retryable && attempt < maxRetries - 1) {
                lastError = e;
                console.warn(`[apiFetch] Gateway error (${e.status}), retrying in ${retryDelay/1000}s... (attempt ${attempt + 1}/${maxRetries})`);
                await new Promise(r => setTimeout(r, retryDelay));
                continue;
            }
            // Non-retryable or exhausted retries
            if (e && e.retryable) {
                throw new TypeError('Server is temporarily unavailable after multiple retries. Please try again.');
            }
            throw e;
        }
    }
    throw new TypeError('Server is temporarily unavailable. Please try again.');
}

// High-level API request helper (used by tools.js)
// Returns parsed JSON directly, throws on error
async function apiRequest(url, method = 'GET', body = null) {
    const options = { method };
    if (body && method !== 'GET') {
        options.headers = { 'Content-Type': 'application/json' };
        options.body = JSON.stringify(body);
    }
    const res = await apiFetch(url, options);
    const data = await res.json();
    if (!res.ok) {
        throw new Error(data.error || `HTTP ${res.status}`);
    }
    return data;
}

// Connection status checker
let _connectionOk = true;
async function checkBackendHealth() {
    try {
        const res = await apiFetch('/api/health', { timeout: 8000 });
        if (res.ok) {
            const data = await res.json();
            _connectionOk = data && data.status === 'ok';
        } else {
            _connectionOk = false;
        }
    } catch (e) {
        _connectionOk = false;
    }
    // Update status indicator if it exists
    const indicator = document.getElementById('connection-status');
    if (indicator) {
        indicator.className = _connectionOk ? 'conn-status conn-ok' : 'conn-status conn-err';
        indicator.title = _connectionOk ? 'Backend connected' : 'Backend offline';
    }
}

// Check health every 30 seconds
setInterval(checkBackendHealth, 30000);
// Initial check after 2 seconds
setTimeout(checkBackendHealth, 2000);
