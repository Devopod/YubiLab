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
                json: () => Promise.resolve(JSON.parse(xhr.responseText)),
            };
            resolve(response);
        };

        xhr.onerror = function () {
            reject(new TypeError('Network request failed'));
        };

        xhr.ontimeout = function () {
            reject(new TypeError('Request timeout'));
        };

        xhr.send(options.body || null);
    });
}
