const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const cors = require('cors');
const { setupTerminal } = require('./terminal');
const { setupExecutor } = require('./executor');

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
    cors: {
        origin: "*",
        methods: ["GET", "POST"],
        credentials: true
    },
    pingTimeout: 60000,
    pingInterval: 25000
});

app.use(cors());
app.use(express.json());

// Health check
app.get('/health', (req, res) => {
    res.json({ status: 'ok', service: 'YubiLab Node Engine' });
});

// Code execution REST endpoint
app.post('/execute', (req, res) => {
    const { code, language, projectPath } = req.body;
    if (!code || !language) {
        return res.status(400).json({ error: 'Code and language are required' });
    }

    const { executeCode } = require('./executor');
    executeCode(code, language, projectPath)
        .then(result => res.json(result))
        .catch(err => res.status(500).json({ error: err.message }));
});

// Socket.IO connection handling
io.on('connection', (socket) => {
    console.log(`Client connected: ${socket.id}`);

    // Setup terminal for this connection
    setupTerminal(socket);

    // Setup code executor for this connection
    setupExecutor(socket);

    socket.on('disconnect', () => {
        console.log(`Client disconnected: ${socket.id}`);
    });
});

const PORT = process.env.NODE_ENGINE_PORT || 3001;
server.listen(PORT, '0.0.0.0', () => {
    console.log(`YubiLab Node Engine running on port ${PORT}`);
});
