// Simple reverse proxy to serve both Flask (5000) and Node.js Socket.IO (3001) on a single port
const http = require('http');
const httpProxy = require('http-proxy');

const proxy = httpProxy.createProxyServer({});
const PORT = 8888;

const server = http.createServer((req, res) => {
    if (req.url.startsWith('/socket.io')) {
        proxy.web(req, res, { target: 'http://127.0.0.1:3001' }, (err) => {
            res.writeHead(502);
            res.end('Node engine unavailable');
        });
    } else {
        proxy.web(req, res, { target: 'http://127.0.0.1:5000' }, (err) => {
            res.writeHead(502);
            res.end('Flask backend unavailable');
        });
    }
});

server.on('upgrade', (req, socket, head) => {
    proxy.ws(req, socket, head, { target: 'http://127.0.0.1:3001' });
});

server.listen(PORT, '0.0.0.0', () => {
    console.log(`YubiLab proxy running on port ${PORT}`);
});
