import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { assertCleanEngineStatus, classifyChild, isolatedEnvironment, runProcess, superviseCommand, superviseProcess, verifyFixtureHash } from './neo-forge.mjs';

const setup = { schema_version: 1, request_id: 'r1', status: 'ready' };
const terminal = { schema_version: 1, request_id: 'r1', status: 'terminal', terminal: 'win', winner_seat: 0 };

async function assertProcessStopped(pid) {
  try { process.kill(pid, 0); }
  catch (error) { if (error.code === 'ESRCH') return; throw error; }
  if (process.platform === 'linux') {
    try {
      const status = await readFile(`/proc/${pid}/stat`, 'utf8');
      assert.equal(status.slice(status.lastIndexOf(')') + 2).split(' ')[0], 'Z');
      return;
    } catch (error) { if (error.code === 'ENOENT') return; throw error; }
  }
  assert.fail(`Process ${pid} is still running`);
}

test('fixture tampering is rejected before loading', () => {
  assert.throws(() => verifyFixtureHash('a'.repeat(64), 'b'.repeat(64)), /fixture hash mismatch/);
  assert.equal(verifyFixtureHash('a'.repeat(64), 'a'.repeat(64)), true);
});

test('one modified upstream engine file is rejected from porcelain status', () => {
  assert.throws(() => assertCleanEngineStatus(' M forge-ai/src/main/java/forge/ai/AiController.java\n'), /dirty engine build input/);
  assert.throws(() => assertCleanEngineStatus(' M .mvn/maven.config\n'), /dirty engine build input/);
  assert.deepEqual(assertCleanEngineStatus(' M .gitignore\n'), ['.gitignore']);
});

test('only a matching terminal receipt after a clean exit completes', () => {
  assert.equal(classifyChild({ exitCode: 0, setup, terminal, requestId: 'r1' }).outcome, 'completed');
  assert.equal(classifyChild({ exitCode: 0, setup: null, terminal, requestId: 'r1' }).outcome, 'rejected');
  assert.equal(classifyChild({ exitCode: 0, setup, terminal: null, requestId: 'r1' }).outcome, 'rejected');
  assert.equal(classifyChild({ exitCode: 0, setup, terminal: { ...terminal, winner_seat: 3 }, requestId: 'r1' }).outcome, 'rejected');
});

test('watchdog expiry cannot become an engine draw', () => {
  const result = classifyChild({ exitCode: null, timedOut: { phase: 'game', limitSeconds: 1, treeStopped: true, processStopped: true }, setup, terminal: { ...terminal, terminal: 'draw', winner_seat: -1 }, requestId: 'r1' });
  assert.deepEqual(result, { outcome: 'timed_out', phase: 'game', limit_seconds: 1, tree_stopped: true, process_stopped: true });
});

test('a real child process is stopped and marked timed out', async t => {
  const result = await runProcess(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { timeoutSeconds: 1 });
  assert.equal(result.timedOut, true);
  assert.equal(result.processStopped, true);
  assert.equal(typeof result.treeStopped, 'boolean');
  t.diagnostic(`process_stopped=${result.processStopped}, tree_stopped=${result.treeStopped}`);
});

test('a supervised game retains its timeout when termination closes the child', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'neo forge game timeout '));
  try {
    const request = { id: 'r1', output_directory: directory };
    const code = `const fs = require('node:fs'); const path = require('node:path');
      fs.writeFileSync(path.join(process.argv[1], 'started.json'), JSON.stringify({schema_version:1, request_id:'r1',status:'started'}));
      fs.writeFileSync(path.join(process.argv[1], 'pid'), String(process.pid));
      console.log('child started'); setInterval(() => {}, 1000);`;
    const result = await superviseCommand(process.execPath, ['-e', code, directory], request, directory, 2, 0.2);
    assert.equal(result.outcome, 'timed_out');
    assert.equal(result.phase, 'game');
    assert.equal(result.process_stopped, true);
    assert.equal(typeof result.tree_stopped, 'boolean');
    assert.equal(await readFile(path.join(directory, 'stdout.log'), 'utf8'), 'child started\n');
    const pid = Number(await readFile(path.join(directory, 'pid'), 'utf8'));
    assert.throws(() => process.kill(pid, 0), error => error.code === 'ESRCH');
  } finally {
    const relative = path.relative(path.resolve(os.tmpdir()), path.resolve(directory));
    assert.ok(relative && !relative.startsWith('..') && !path.isAbsolute(relative));
    await rm(directory, { recursive: true, force: true });
  }
});

const receiptWriter = `const fs = require('node:fs'); const path = require('node:path');
  const dir = process.argv[1];
  const write = (name, data) => fs.writeFileSync(path.join(dir, name + '.json'), JSON.stringify(data));
  fs.writeFileSync(path.join(dir, 'pid'), String(process.pid));
  const started = {schema_version:1,request_id:'r1',status:'started'};
  const setup = ${JSON.stringify(setup)}; const terminal = ${JSON.stringify(terminal)};`;

async function withChild(code, check, startupLimit = 0.3) {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'neo forge supervised child '));
  try {
    const request = { id: 'r1', output_directory: directory };
    const result = await superviseCommand(process.execPath, ['-e', receiptWriter + code, directory], request, directory, startupLimit, 1);
    const pid = Number(await readFile(path.join(directory, 'pid'), 'utf8'));
    assert.throws(() => process.kill(pid, 0), error => error.code === 'ESRCH');
    await check(result, directory);
  } finally {
    const relative = path.relative(path.resolve(os.tmpdir()), path.resolve(directory));
    assert.ok(relative && !relative.startsWith('..') && !path.isAbsolute(relative));
    await rm(directory, { recursive: true, force: true });
  }
}

test('missing and invalid startup receipts time out and stop the owned process', async t => {
  for (const receipt of [null, { schema_version: 1, request_id: 'wrong', status: 'started' }, { request_id: 'r1', status: 'started' }]) {
    await withChild(`if (${JSON.stringify(receipt)}) write('started', ${JSON.stringify(receipt)}); setInterval(() => {}, 1000);`, result => {
      assert.equal(result.outcome, 'timed_out');
      assert.equal(result.phase, 'startup');
      assert.equal(result.process_stopped, true);
      assert.equal(typeof result.tree_stopped, 'boolean');
      t.diagnostic(`startup teardown process_stopped=${result.process_stopped}, tree_stopped=${result.tree_stopped}`);
    });
  }
});

test('reported tree teardown stops an actual descendant as well as the owned PID', async t => {
  await assert.rejects(assertProcessStopped(process.pid), assert.AssertionError);
  await withChild(`const {spawn} = require('node:child_process');
    const descendant = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], {stdio:'ignore'});
    fs.writeFileSync(path.join(dir, 'descendant-pid'), String(descendant.pid));
    write('started', started); setInterval(() => {}, 1000);`, async (result, directory) => {
    const descendantPid = Number(await readFile(path.join(directory, 'descendant-pid'), 'utf8'));
    try {
      assert.equal(result.outcome, 'timed_out');
      assert.equal(result.process_stopped, true);
      t.diagnostic(`descendant teardown process_stopped=${result.process_stopped}, tree_stopped=${result.tree_stopped}`);
      if (result.tree_stopped) await assertProcessStopped(descendantPid);
    } finally {
      try { process.kill(descendantPid, 'SIGKILL'); } catch (error) { if (error.code !== 'ESRCH') throw error; }
    }
  });
});

test('natural completion keeps matching evidence and complete child logs', async () => {
  await withChild(`write('started', started); write('setup', setup); write('terminal', terminal);
    for(let i=0;i<1000;i++) console.log('line ' + i); console.error('final stderr');`, async (result, directory) => {
    assert.equal(result.outcome, 'completed');
    assert.equal(result.winner_seat, 0);
    assert.equal(await readFile(path.join(directory, 'stdout.log'), 'utf8'), Array.from({ length: 1000 }, (_, i) => `line ${i}\n`).join(''));
    assert.equal(await readFile(path.join(directory, 'stderr.log'), 'utf8'), 'final stderr\n');
  });
});

test('actual child exits classify a crash and reject missing or invalid terminal receipts', async () => {
  await withChild('process.exit(7);', result => {
    assert.equal(result.outcome, 'crashed');
    assert.equal(result.process_exit, 7);
  });
  await withChild('process.exit(0);', result => assert.equal(result.outcome, 'rejected'));
  await withChild("write('started', started); write('setup', setup);", result => assert.equal(result.outcome, 'rejected'));
  await withChild("write('started', started); write('setup', setup); write('terminal', {...terminal,request_id:'wrong'});", result => assert.equal(result.outcome, 'rejected'));
});

test('spawn errors cancel the startup watchdog and receipt polling', async () => {
  await assert.rejects(superviseProcess(path.join(os.tmpdir(), 'no such executable neo forge.exe'), [], {
    startupReceipt: { file: path.join(os.tmpdir(), 'absent neo forge receipt.json'), requestId: 'r1', status: 'started' },
    startupSeconds: 0.1,
  }), error => error.code === 'ENOENT');
});

test('desktop startup accepts only a matching live PID and preserves logs', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'neo forge desktop receipt '));
  let pid;
  try {
    const result = await superviseProcess(process.execPath, ['-e', receiptWriter + `console.log('desktop initialized');
      write('desktop-started', {schema_version:1, request_id:'r1',status:'desktop-started',pid:process.pid});
      setInterval(() => {}, 1000);`, directory], {
      startupReceipt: { file: path.join(directory, 'desktop-started.json'), requestId: 'r1', status: 'desktop-started', matchPid: true },
      startupSeconds: 2, detachAfterStartup: true,
      stdoutFile: path.join(directory, 'stdout.log'), stderrFile: path.join(directory, 'stderr.log'),
    });
    pid = result.pid;
    assert.equal(result.started, true);
    assert.equal(result.receipt.pid, pid);
    assert.equal(process.kill(pid, 0), true);
    assert.equal(await readFile(path.join(directory, 'stdout.log'), 'utf8'), 'desktop initialized\n');
  } finally {
    if (pid) {
      process.kill(pid, 'SIGKILL');
      for (let attempt = 0; attempt < 100; attempt++) {
        try { process.kill(pid, 0); } catch (error) { if (error.code === 'ESRCH') break; throw error; }
        await new Promise(resolve => setTimeout(resolve, 10));
      }
      assert.throws(() => process.kill(pid, 0), error => error.code === 'ESRCH');
    }
    const relative = path.relative(path.resolve(os.tmpdir()), path.resolve(directory));
    assert.ok(relative && !relative.startsWith('..') && !path.isAbsolute(relative));
    await rm(directory, { recursive: true, force: true });
  }
});

test('desktop startup rejects a receipt carrying another PID', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'neo forge wrong desktop pid '));
  try {
    const result = await superviseProcess(process.execPath, ['-e', receiptWriter + `
      write('desktop-started', {schema_version:1, request_id:'r1',status:'desktop-started',pid:process.pid+1});
      setInterval(() => {}, 1000);`, directory], {
      startupReceipt: { file: path.join(directory, 'desktop-started.json'), requestId: 'r1', status: 'desktop-started', matchPid: true },
      startupSeconds: 0.3, detachAfterStartup: true,
    });
    assert.equal(result.started, false);
    assert.equal(result.timedOut, true);
    assert.equal(result.phase, 'startup');
    assert.equal(result.processStopped, true);
    assert.throws(() => process.kill(result.pid, 0), error => error.code === 'ESRCH');
  } finally {
    const relative = path.relative(path.resolve(os.tmpdir()), path.resolve(directory));
    assert.ok(relative && !relative.startsWith('..') && !path.isAbsolute(relative));
    await rm(directory, { recursive: true, force: true });
  }
});

test('isolation preserves system home variables and redirects Forge writable environment', () => {
  const directory = path.resolve(os.tmpdir(), 'neo forge isolation');
  const env = isolatedEnvironment(directory);
  assert.equal(env.HOME, process.env.HOME);
  assert.equal(env.USERPROFILE, process.env.USERPROFILE);
  assert.equal(env.APPDATA, path.join(directory, 'appdata'));
  assert.equal(env.LOCALAPPDATA, path.join(directory, 'localappdata'));
  assert.equal(env.TMP, path.join(directory, 'tmp'));
  assert.equal(env.TEMP, path.join(directory, 'tmp'));
});

test('nonzero child exit is a crash even if it left a win receipt', () => {
  assert.equal(classifyChild({ exitCode: 1, setup, terminal, requestId: 'r1' }).outcome, 'crashed');
});

test('draw receipt carries no winning seat', () => {
  assert.equal(classifyChild({ exitCode: 0, setup, terminal: { ...terminal, terminal: 'draw', winner_seat: -1 }, requestId: 'r1' }).outcome, 'completed');
  assert.equal(classifyChild({ exitCode: 0, setup, terminal: { ...terminal, terminal: 'draw', winner_seat: 0 }, requestId: 'r1' }).outcome, 'rejected');
});
