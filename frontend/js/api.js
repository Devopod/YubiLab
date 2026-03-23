// YubiLab API Helper
// Uses XMLHttpRequest instead of fetch to work around browser security restriction
// that blocks fetch() when the page URL contains basic-auth credentials (user:pass@host)

function apiFetch(url, options = {}) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        const method = (options.method || 'GET').toUpperCase();
        xhr.open(method, url, true);
        xhr.timeout = options.timeout || 30000;

        // Set headers
        if (options.headers) {
            for (const [key, value] of Object.entries(options.headers)) {
                xhr.setRequestHeader(key, value);
            }
        }

        xhr.onload = function () {
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
                        // Detect specific error scenarios for better messages
                        const text = xhr.responseText || '';
                        let errorMsg = 'Server returned an invalid response';

                        if (xhr.status === 0) {
                            errorMsg = 'Cannot connect to server. Please check if the backend is running.';
                        } else if (xhr.status === 502 || xhr.status === 503 || xhr.status === 504) {
                            errorMsg = 'Server is temporarily unavailable. Please try again in a moment.';
                        } else if (xhr.status === 401) {
                            errorMsg = 'Session expired. Please log in again.';
                        } else if (text.includes('<!DOCTYPE') || text.includes('<html') || text.includes('ngrok')) {
                            errorMsg = 'Backend server is not responding properly. It may be restarting.';
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
            reject(new TypeError('Cannot connect to server. Please check your connection and try again.'));
        };

        xhr.ontimeout = function () {
            reject(new TypeError('Request timed out. The server may be busy - please try again.'));
        };

        xhr.send(options.body || null);
    });
}

// Connection status checker
let _connectionOk = true;
async function checkBackendHealth() {
    try {
        const res = await apiFetch('/api/health', { timeout: 5000 });
        _connectionOk = res.ok;
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
