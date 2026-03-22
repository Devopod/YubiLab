const pty = require('node-pty');
const os = require('os');
const path = require('path');

// Track active terminals
const terminals = new Map();

function setupTerminal(socket) {
    let currentTerminal = null;

    socket.on('terminal:start', (data) => {
        const { projectPath, cols, rows } = data;

        // Kill existing terminal for this socket
        if (currentTerminal) {
            try { currentTerminal.kill(); } catch (e) {}
        }

        const shell = os.platform() === 'win32' ? 'powershell.exe' : '/bin/bash';
        const cwd = projectPath && require('fs').existsSync(projectPath) ? projectPath : os.homedir();

        try {
            const term = pty.spawn(shell, [], {
                name: 'xterm-256color',
                cols: cols || 80,
                rows: rows || 24,
                cwd: cwd,
                env: {
                    ...process.env,
                    TERM: 'xterm-256color',
                    COLORTERM: 'truecolor',
                    HOME: os.homedir(),
                    PATH: process.env.PATH
                }
            });

            currentTerminal = term;
            terminals.set(socket.id, term);

            term.onData((data) => {
                socket.emit('terminal:output', data);
            });

            term.onExit(({ exitCode }) => {
                socket.emit('terminal:exit', { exitCode });
                terminals.delete(socket.id);
                currentTerminal = null;
            });

            socket.emit('terminal:ready', { pid: term.pid });
            console.log(`Terminal started for ${socket.id}, PID: ${term.pid}, CWD: ${cwd}`);
        } catch (err) {
            console.error('Failed to start terminal:', err);
            socket.emit('terminal:error', { error: err.message });
        }
    });

    socket.on('terminal:input', (data) => {
        if (currentTerminal) {
            currentTerminal.write(data);
        }
    });

    socket.on('terminal:resize', ({ cols, rows }) => {
        if (currentTerminal) {
            try {
                currentTerminal.resize(cols, rows);
            } catch (e) {}
        }
    });

    socket.on('terminal:stop', () => {
        if (currentTerminal) {
            try { currentTerminal.kill(); } catch (e) {}
            terminals.delete(socket.id);
            currentTerminal = null;
        }
    });

    socket.on('disconnect', () => {
        if (currentTerminal) {
            try { currentTerminal.kill(); } catch (e) {}
            terminals.delete(socket.id);
            currentTerminal = null;
        }
    });
}

module.exports = { setupTerminal };
