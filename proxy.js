// Simple reverse proxy to serve both Flask (5000) and Node.js Socket.IO (3001) on a single port
const http = require('http');
const httpProxy = require('http-proxy');

// Long timeout for agent requests (up to 10 minutes)
const proxy = httpProxy.createProxyServer({ timeout: 600000, proxyTimeout: 600000 });
const PORT = 8888;

const server = http.createServer((req, res) => {
    if (req.url.startsWith('/socket.io')) {
        proxy.web(req, res, { target: 'http://127.0.0.1:3001' }, (err) => {
            res.writeHead(502, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'Node engine unavailable' }));
        });
    } else {
        proxy.web(req, res, { target: 'http://127.0.0.1:5000' }, (err) => {
            res.writeHead(502, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'Flask backend unavailable. Please try again.' }));
        });
    }
});

server.on('upgrade', (req, socket, head) => {
    proxy.ws(req, socket, head, { target: 'http://127.0.0.1:3001' });
});

server.listen(PORT, '0.0.0.0', () => {
    console.log(`YubiLab proxy running on port ${PORT}`);
});
