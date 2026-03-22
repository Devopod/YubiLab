const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');
const { v4: uuidv4 } = require('uuid');

// Language configurations
const LANGUAGE_CONFIG = {
    'python': {
        extension: '.py',
        command: 'python3',
        args: (file) => [file],
        compile: null,
    },
    'javascript': {
        extension: '.js',
        command: 'node',
        args: (file) => [file],
        compile: null,
    },
    'c': {
        extension: '.c',
        command: null,
        compile: (file, out) => ({ cmd: 'gcc', args: [file, '-o', out] }),
        run: (out) => ({ cmd: out, args: [] }),
    },
    'cpp': {
        extension: '.cpp',
        command: null,
        compile: (file, out) => ({ cmd: 'g++', args: [file, '-o', out] }),
        run: (out) => ({ cmd: out, args: [] }),
    },
    'java': {
        extension: '.java',
        command: null,
        compile: (file, out) => ({ cmd: 'javac', args: [file] }),
        run: (out, dir) => ({ cmd: 'java', args: ['-cp', dir, 'Main'] }),
    },
    'go': {
        extension: '.go',
        command: 'go',
        args: (file) => ['run', file],
        compile: null,
    },
    'php': {
        extension: '.php',
        command: 'php',
        args: (file) => [file],
        compile: null,
    },
    'rust': {
        extension: '.rs',
        command: null,
        compile: (file, out) => ({ cmd: 'rustc', args: [file, '-o', out] }),
        run: (out) => ({ cmd: out, args: [] }),
    },
};

// Timeout for code execution (30 seconds)
const EXECUTION_TIMEOUT = 30000;
// Max output size (1MB)
const MAX_OUTPUT_SIZE = 1024 * 1024;

function executeCode(code, language, projectPath) {
    return new Promise((resolve, reject) => {
        const config = LANGUAGE_CONFIG[language];
        if (!config) {
            return reject(new Error(`Unsupported language: ${language}`));
        }

        const tmpDir = path.join(os.tmpdir(), `yubilab-${uuidv4()}`);
        fs.mkdirSync(tmpDir, { recursive: true });

        const filename = language === 'java' ? 'Main' + config.extension : 'main' + config.extension;
        const filepath = path.join(tmpDir, filename);
        fs.writeFileSync(filepath, code);

        const outputBinary = path.join(tmpDir, 'output');
        let stdout = '';
        let stderr = '';
        const startTime = Date.now();

        function cleanup() {
            try {
                fs.rmSync(tmpDir, { recursive: true, force: true });
            } catch (e) {}
        }

        function runProcess(cmd, args, cwd) {
            return new Promise((res, rej) => {
                const proc = spawn(cmd, args, {
                    cwd: cwd || projectPath || tmpDir,
                    timeout: EXECUTION_TIMEOUT,
                    env: { ...process.env, HOME: os.homedir() },
                });

                proc.stdout.on('data', (data) => {
                    if (stdout.length < MAX_OUTPUT_SIZE) {
                        stdout += data.toString();
                    }
                });

                proc.stderr.on('data', (data) => {
                    if (stderr.length < MAX_OUTPUT_SIZE) {
                        stderr += data.toString();
                    }
                });

                proc.on('close', (code) => {
                    res(code);
                });

                proc.on('error', (err) => {
                    rej(err);
                });

                // Kill after timeout
                setTimeout(() => {
                    try { proc.kill('SIGKILL'); } catch (e) {}
                    rej(new Error('Execution timed out (30s limit)'));
                }, EXECUTION_TIMEOUT);
            });
        }

        async function execute() {
            try {
                if (config.compile) {
                    // Compiled language
                    const compileConfig = config.compile(filepath, outputBinary);
                    const compileCode = await runProcess(compileConfig.cmd, compileConfig.args, tmpDir);

                    if (compileCode !== 0) {
                        const duration = Date.now() - startTime;
                        cleanup();
                        return resolve({
                            stdout: '',
                            stderr: stderr || 'Compilation failed',
                            exitCode: compileCode,
                            duration: duration,
                            language: language,
                        });
                    }

                    // Reset output for run
                    stderr = '';
                    stdout = '';

                    const runConfig = config.run(outputBinary, tmpDir);
                    const exitCode = await runProcess(runConfig.cmd, runConfig.args, tmpDir);
                    const duration = Date.now() - startTime;
                    cleanup();
                    resolve({ stdout, stderr, exitCode, duration, language });
                } else {
                    // Interpreted language
                    const exitCode = await runProcess(config.command, config.args(filepath), projectPath || tmpDir);
                    const duration = Date.now() - startTime;
                    cleanup();
                    resolve({ stdout, stderr, exitCode, duration, language });
                }
            } catch (err) {
                const duration = Date.now() - startTime;
                cleanup();
                resolve({
                    stdout,
                    stderr: stderr || err.message,
                    exitCode: -1,
                    duration: duration,
                    language: language,
                });
            }
        }

        execute();
    });
}


function setupExecutor(socket) {
    socket.on('code:run', async (data) => {
        const { code, language, projectPath } = data;

        socket.emit('code:output', { type: 'info', data: `Running ${language} code...\n` });

        try {
            const result = await executeCode(code, language, projectPath);

            if (result.stdout) {
                socket.emit('code:output', { type: 'stdout', data: result.stdout });
            }
            if (result.stderr) {
                socket.emit('code:output', { type: 'stderr', data: result.stderr });
            }

            socket.emit('code:done', {
                exitCode: result.exitCode,
                duration: result.duration,
                language: result.language,
            });
        } catch (err) {
            socket.emit('code:output', { type: 'stderr', data: err.message });
            socket.emit('code:done', { exitCode: -1, duration: 0, language });
        }
    });

    // Stream execution (for real-time output)
    socket.on('code:run-stream', (data) => {
        const { code, language, projectPath } = data;
        const config = LANGUAGE_CONFIG[language];

        if (!config) {
            socket.emit('code:output', { type: 'stderr', data: `Unsupported language: ${language}\n` });
            socket.emit('code:done', { exitCode: -1 });
            return;
        }

        const tmpDir = path.join(os.tmpdir(), `yubilab-${uuidv4()}`);
        fs.mkdirSync(tmpDir, { recursive: true });

        const filename = language === 'java' ? 'Main.java' : 'main' + config.extension;
        const filepath = path.join(tmpDir, filename);
        fs.writeFileSync(filepath, code);

        socket.emit('code:output', { type: 'info', data: `▶ Running ${language}...\n` });

        function runStreaming(cmd, args, cwd) {
            const proc = spawn(cmd, args, {
                cwd: cwd || tmpDir,
                env: { ...process.env, HOME: os.homedir() },
            });

            proc.stdout.on('data', (chunk) => {
                socket.emit('code:output', { type: 'stdout', data: chunk.toString() });
            });

            proc.stderr.on('data', (chunk) => {
                socket.emit('code:output', { type: 'stderr', data: chunk.toString() });
            });

            proc.on('close', (code) => {
                socket.emit('code:done', { exitCode: code, language });
                try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (e) {}
            });

            proc.on('error', (err) => {
                socket.emit('code:output', { type: 'stderr', data: err.message + '\n' });
                socket.emit('code:done', { exitCode: -1, language });
            });

            const timeout = setTimeout(() => {
                try { proc.kill('SIGKILL'); } catch (e) {}
                socket.emit('code:output', { type: 'stderr', data: '\n⏱ Execution timed out (30s limit)\n' });
                socket.emit('code:done', { exitCode: -1, language });
            }, EXECUTION_TIMEOUT);

            proc.on('close', () => clearTimeout(timeout));

            // Allow stopping
            socket.on('code:stop', () => {
                try { proc.kill('SIGKILL'); } catch (e) {}
            });
        }

        if (config.compile) {
            const outputBinary = path.join(tmpDir, 'output');
            const compileConfig = config.compile(filepath, outputBinary);

            socket.emit('code:output', { type: 'info', data: `Compiling...\n` });

            const compProc = spawn(compileConfig.cmd, compileConfig.args, { cwd: tmpDir });
            let compErr = '';

            compProc.stderr.on('data', (d) => { compErr += d.toString(); });
            compProc.on('close', (code) => {
                if (code !== 0) {
                    socket.emit('code:output', { type: 'stderr', data: compErr || 'Compilation failed\n' });
                    socket.emit('code:done', { exitCode: code, language });
                    return;
                }
                const runConfig = config.run(outputBinary, tmpDir);
                runStreaming(runConfig.cmd, runConfig.args, tmpDir);
            });
        } else {
            runStreaming(config.command, config.args(filepath), projectPath || tmpDir);
        }
    });
}

module.exports = { setupExecutor, executeCode };
