import { spawn, spawnSync } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { mkdir, open, readFile, readdir, rm, stat, writeFile, copyFile, symlink } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ENTRY = path.join(ROOT, 'evaluation', 'ai', 'java', 'CommanderEval.java');
const MANIFEST = path.join(ROOT, 'evaluation', 'ai', 'deck-manifest.json');
const PLAN = path.join(ROOT, 'evaluation', 'ai', 'plans', 'stock-smoke.json');
const TOOLCHAIN = path.join(ROOT, '.tools', 'toolchain.json');
const JAR = path.join(ROOT, 'forge-gui-desktop', 'target', 'forge-gui-desktop-2.0.16-SNAPSHOT-jar-with-dependencies.jar');
const BUILD_INPUT_ROOTS = ['.mvn', 'forge-core', 'forge-game', 'forge-ai', 'forge-gui', 'forge-gui-desktop'];
const ALLOWED_UNTRACKED_ROOTS = ['scripts/', 'evaluation/ai/', 'docs/neo-forge/', '.audit/'];

export function classifyChild({ exitCode, timedOut, setup, terminal, failure, requestId }) {
  if (timedOut) return { outcome: 'timed_out', phase: timedOut.phase, limit_seconds: timedOut.limitSeconds,
    tree_stopped: timedOut.treeStopped, process_stopped: timedOut.processStopped };
  if (exitCode === 2 && failure?.request_id === requestId && failure.classification === 'rejected') {
    return { outcome: 'rejected', reason: failure.message, failure_type: failure.type };
  }
  if (exitCode !== 0) return { outcome: 'crashed', process_exit: exitCode, failure: 'child exited nonzero' };
  if (!setup || setup.schema_version !== 1 || setup.request_id !== requestId || setup.status !== 'ready') return { outcome: 'rejected', reason: 'missing or malformed setup receipt' };
  if (!terminal || terminal.request_id !== requestId || terminal.schema_version !== 1 || terminal.status !== 'terminal') return { outcome: 'rejected', reason: 'missing or malformed terminal receipt' };
  if (!['win', 'draw'].includes(terminal.terminal)) return { outcome: 'rejected', reason: 'unknown terminal value' };
  if (terminal.terminal === 'win' && ![0, 1].includes(terminal.winner_seat)) return { outcome: 'rejected', reason: 'winner seat is invalid' };
  if (terminal.terminal === 'draw' && terminal.winner_seat !== -1) return { outcome: 'rejected', reason: 'draw carried a winner' };
  return { outcome: 'completed', terminal: terminal.terminal, winner_seat: terminal.winner_seat, engine_end_reason: terminal.engine_end_reason,
    last_turn: terminal.last_turn, first_player_seat: terminal.first_player_seat, game_log: terminal.game_log };
}

export function verifyFixtureHash(expected, actual) {
  if (!/^[a-f0-9]{64}$/.test(expected) || expected !== actual) throw new Error('fixture hash mismatch');
  return true;
}

export function assertCleanEngineStatus(statusText) {
  const paths = statusText.trimEnd().split(/\r?\n/).filter(Boolean).map(line => line.slice(3));
  for (const file of paths) {
    if (file === 'pom.xml' || file.startsWith('.mvn/') || BUILD_INPUT_ROOTS.some(root => file === root || file.startsWith(`${root}/`))) {
      throw new Error(`dirty engine build input: ${file}`);
    }
  }
  return paths;
}

async function hashFile(file) {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(file)) hash.update(chunk);
  return hash.digest('hex');
}

function git(args, { allowFailure = false } = {}) {
  const result = spawnSync('git', args, { cwd: ROOT, encoding: 'utf8', windowsHide: true });
  if (result.status !== 0 && !allowFailure) throw new Error(`git ${args[0]} failed: ${(result.stderr || result.stdout).trim()}`);
  return (result.stdout ?? '').trim();
}

function gitBuffer(args) {
  const result = spawnSync('git', args, { cwd: ROOT, encoding: 'buffer', windowsHide: true });
  if (result.status !== 0) throw new Error(`git ${args[0]} failed: ${result.stderr.toString('utf8').trim()}`);
  return result.stdout;
}

function assertEngineInputs(enginePin) {
  const head = git(['rev-parse', 'HEAD']);
  const ancestry = spawnSync('git', ['merge-base', '--is-ancestor', enginePin, head], { cwd: ROOT, windowsHide: true });
  if (ancestry.status !== 0) throw new Error(`pinned engine commit ${enginePin} is not an ancestor of HEAD ${head}`);
  const statusResult = spawnSync('git', ['status', '--porcelain=v1', '--untracked-files=all'], { cwd: ROOT, encoding: 'utf8', windowsHide: true });
  if (statusResult.status !== 0) throw new Error(`git status failed: ${statusResult.stderr.trim()}`);
  const status = statusResult.stdout.trimEnd();
  const statusLines = status.split(/\r?\n/).filter(Boolean);
  assertCleanEngineStatus(status);
  for (const file of git(['ls-files', '--others', '--exclude-standard']).split(/\r?\n/).filter(Boolean)) {
    if (BUILD_INPUT_ROOTS.some(root => file === root || file.startsWith(`${root}/`))) throw new Error(`untracked engine input: ${file}`);
    if (!ALLOWED_UNTRACKED_ROOTS.some(root => file.startsWith(root))) throw new Error(`unapproved untracked file: ${file}`);
  }
  const inputTrees = {};
  for (const root of BUILD_INPUT_ROOTS) {
    const baseline = git(['rev-parse', `${enginePin}:${root}`]);
    const current = git(['rev-parse', `${head}:${root}`]);
    if (baseline !== current) throw new Error(`committed engine build input changed since baseline: ${root}`);
    inputTrees[root] = baseline;
  }
  for (const file of ['pom.xml']) {
    const baseline = git(['rev-parse', `${enginePin}:${file}`]);
    const current = git(['rev-parse', `${head}:${file}`]);
    if (baseline !== current) throw new Error(`committed engine build input changed since baseline: ${file}`);
    inputTrees[file] = baseline;
  }
  const untracked = git(['ls-files', '--others', '--exclude-standard']).split(/\r?\n/).filter(Boolean);
  return { engine_baseline: enginePin, actual_head: head, input_trees: inputTrees,
    workspace_changes: [...new Set([...statusLines.map(line => line.slice(3)), ...untracked])].sort() };
}

async function readPlan(planPath, overrides = {}) {
  const bytes = await readFile(planPath);
  const plan = JSON.parse(bytes);
  if (plan.schema_version !== 1 || !/^[a-f0-9]{40}$/.test(plan.engine_commit) || !Array.isArray(plan.deck_ids) || plan.deck_ids.length !== 2 ||
      !Array.isArray(plan.seeds) || !plan.seeds.length || !['both', 'cross'].includes(plan.seat_orders) ||
      !Number.isInteger(plan.game_wall_seconds) || !Number.isInteger(plan.startup_wall_seconds) ||
      !['off', 'standard', 'desktop-max'].includes(plan.ai?.monte_carlo) || plan.ai?.profile !== 'Default') {
    throw new Error('unsupported or incomplete evaluation plan');
  }
  const gameLimit = overrides.gameLimit ?? plan.game_wall_seconds;
  const startupLimit = overrides.startupLimit ?? plan.startup_wall_seconds;
  if (!Number.isInteger(gameLimit) || gameLimit < 1 || gameLimit > 3600 || !Number.isInteger(startupLimit) || startupLimit < 1 || startupLimit > 900) {
    throw new Error('timeout override is outside the supported range');
  }
  return { plan, planBytes: bytes, planHash: createHash('sha256').update(bytes).digest('hex'), gameLimit, startupLimit };
}

async function loadFixtures(plan) {
  const manifestPath = path.resolve(ROOT, plan.deck_manifest);
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
  const decks = plan.deck_ids.map(id => {
    const entry = manifest.decks.find(deck => deck.id === id);
    if (!entry) throw new Error(`deck ${id} is absent from the fixture manifest`);
    if (!/^[a-f0-9]{40}$/.test(entry.upstream_commit)) throw new Error(`deck ${id} manifest has an invalid upstream commit`);
    const ancestry = spawnSync('git', ['merge-base', '--is-ancestor', entry.upstream_commit, plan.engine_commit], { cwd: ROOT, windowsHide: true });
    if (ancestry.status !== 0) throw new Error(`deck ${id} source commit is not an ancestor of the selected engine commit`);
    return { ...entry, source: path.resolve(path.dirname(manifestPath), entry.file) };
  });
  for (const deck of decks) {
    const actual = await hashFile(deck.source);
    verifyFixtureHash(deck.sha256, actual);
    const pinned = gitBuffer(['show', `${deck.upstream_commit}:${deck.upstream_path}`]);
    const upstreamHash = createHash('sha256').update(pinned).digest('hex');
    if (upstreamHash !== deck.sha256) throw new Error(`pinned upstream fixture bytes differ for ${deck.id}`);
  }
  return { manifest, decks };
}

async function writeJson(file, value) {
  await mkdir(path.dirname(file), { recursive: true });
  const temp = `${file}.${randomUUID()}.tmp`;
  await writeFile(temp, `${JSON.stringify(value, null, 2)}\n`);
  await import('node:fs/promises').then(({ rename }) => rename(temp, file));
}

function waitForExit(child, milliseconds) {
  if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve(true);
  return new Promise(resolve => {
    const done = stopped => { clearTimeout(timer); child.off('exit', exited); resolve(stopped); };
    const exited = () => done(true);
    const timer = setTimeout(() => done(false), milliseconds);
    child.once('exit', exited);
  });
}

async function terminateTree(child) {
  if (child.exitCode !== null || child.signalCode !== null) return { treeStopped: false, processStopped: true };
  let treeStopped = false;
  if (process.platform === 'win32') {
    const systemRoot = process.env.SystemRoot ?? 'C:\\Windows';
    const result = spawnSync(path.join(systemRoot, 'System32', 'taskkill.exe'), ['/PID', String(child.pid), '/T', '/F'],
      { encoding: 'utf8', windowsHide: true, timeout: 5000 });
    treeStopped = result.status === 0;
  } else {
    try { process.kill(-child.pid, 'SIGKILL'); treeStopped = true; } catch { }
  }
  if (!treeStopped) { try { child.kill('SIGKILL'); } catch { } }
  const processStopped = await waitForExit(child, 5000);
  return { treeStopped: treeStopped && processStopped, processStopped };
}

export async function superviseProcess(command, args, options = {}) {
  const logs = [];
  try {
    for (const file of [options.stdoutFile, options.stderrFile]) logs.push(file ? await open(file, 'w') : null);
    const result = await new Promise((resolve, reject) => {
      const child = spawn(command, args, { cwd: options.cwd ?? ROOT, env: options.env ?? process.env,
        windowsHide: options.windowsHide ?? true, detached: true,
        stdio: ['ignore', logs[0]?.fd ?? 'pipe', logs[1]?.fd ?? 'pipe'] });
      const state = { phase: options.startupReceipt ? 'startup' : 'game', timeout: null,
        code: null, signal: null, stdout: '', stderr: '', receipt: null, settled: false, spawned: false };
      let deadline;
      let poll;
      const settle = async error => {
        if (state.settled) return;
        state.settled = true;
        clearTimeout(deadline); clearTimeout(poll);
        if (state.timeout) Object.assign(state.timeout, await terminateTree(child));
        if (options.detachAfterStartup || state.timeout?.processStopped === false) {
          child.unref(); child.stdout?.destroy(); child.stderr?.destroy();
        }
        if (error) reject(error);
        else resolve({ code: state.code, signal: state.signal, stdout: state.stdout, stderr: state.stderr,
          pid: child.pid, started: Boolean(state.receipt), receipt: state.receipt,
          ...(state.timeout ? { timedOut: true, timeout: state.timeout, ...state.timeout } : {}) });
      };
      const armDeadline = seconds => {
        clearTimeout(deadline);
        if (seconds) deadline = setTimeout(() => {
          state.timeout = { phase: state.phase, limitSeconds: seconds };
          state.phase = 'timed_out';
          void settle();
        }, seconds * 1000);
      };
      const pollReceipt = async () => {
        const receipt = await tryReadJson(options.startupReceipt.file);
        if (state.settled) return;
        const expected = options.startupReceipt;
        let processAlive = false;
        try { process.kill(child.pid, 0); processAlive = true; } catch { }
        if (state.spawned && processAlive && receipt?.schema_version === 1 && receipt.request_id === expected.requestId &&
            receipt.status === expected.status && (!expected.matchPid || receipt.pid === child.pid) &&
            child.exitCode === null && child.signalCode === null) {
          state.receipt = receipt;
          if (options.detachAfterStartup) { void settle(); return; }
          state.phase = 'game'; armDeadline(options.timeoutSeconds);
          return;
        }
        poll = setTimeout(() => { void pollReceipt(); }, 25);
      };
      child.stdout?.setEncoding('utf8').on('data', chunk => { state.stdout += chunk; });
      child.stderr?.setEncoding('utf8').on('data', chunk => { state.stderr += chunk; });
      child.once('spawn', () => { state.spawned = true; });
      child.once('error', error => { void settle(error); });
      child.once('close', (code, signal) => {
        state.code = code; state.signal = signal;
        if (!state.timeout) { state.phase = 'closed'; void settle(); }
      });
      armDeadline(options.startupReceipt ? options.startupSeconds : options.timeoutSeconds);
      if (options.startupReceipt) void pollReceipt();
    });
    await Promise.all(logs.map(log => log?.close()));
    logs.length = 0;
    if (options.stdoutFile) result.stdout = await readFile(options.stdoutFile, 'utf8');
    if (options.stderrFile) result.stderr = await readFile(options.stderrFile, 'utf8');
    return result;
  } finally {
    await Promise.all(logs.map(log => log?.close()));
  }
}

export function runProcess(command, args, options = {}) {
  return superviseProcess(command, args, options);
}

export async function superviseCommand(command, args, request, gameDir, startupLimit, gameLimit) {
  await writeJson(path.join(gameDir, 'request.json'), request);
  await Promise.all(['appdata', 'localappdata', 'tmp'].map(name => mkdir(path.join(request.output_directory, name), { recursive: true })));
  const child = await superviseProcess(command, args, {
    env: isolatedEnvironment(request.output_directory), stdoutFile: path.join(gameDir, 'stdout.log'), stderrFile: path.join(gameDir, 'stderr.log'),
    startupReceipt: { file: path.join(gameDir, 'started.json'), requestId: request.id, status: 'started' },
    startupSeconds: startupLimit, timeoutSeconds: gameLimit,
  });
  return classifyChild({ exitCode: child.code, timedOut: child.timeout, setup: await tryReadJson(path.join(gameDir, 'setup.json')),
    terminal: await tryReadJson(path.join(gameDir, 'terminal.json')), failure: await tryReadJson(path.join(gameDir, 'failure.json')), requestId: request.id });
}

function superviseGame(java, classpath, request, gameDir, startupLimit, gameLimit) {
  return superviseCommand(java, ['-Djava.awt.headless=true', '-cp', classpath, 'CommanderEval', path.join(gameDir, 'request.json')],
    request, gameDir, startupLimit, gameLimit);
}

async function tryReadJson(file) { try { return JSON.parse(await readFile(file, 'utf8')); } catch { return null; } }

export function isolatedEnvironment(outputDir) {
  const root = path.resolve(outputDir);
  const env = { ...process.env, APPDATA: path.join(root, 'appdata'), LOCALAPPDATA: path.join(root, 'localappdata'),
    TEMP: path.join(root, 'tmp'), TMP: path.join(root, 'tmp') };
  return env;
}

async function readToolchain() {
  try { return JSON.parse(await readFile(TOOLCHAIN, 'utf8')); }
  catch (error) {
    if (error.code !== 'ENOENT') throw error;
    if (process.env.NEO_FORGE_JAVA_HOME && process.env.NEO_FORGE_MAVEN_HOME) return {};
    throw new Error('Missing .tools/toolchain.json. Set both NEO_FORGE_JAVA_HOME and NEO_FORGE_MAVEN_HOME to existing installations, or provide the toolchain file.');
  }
}

function mavenLauncherArgs(runtime) {
  return ['-classpath', runtime.classworlds, `-Dmaven.multiModuleProjectDirectory=${ROOT}`,
    `-Dmaven.repo.local=${path.join(ROOT, '.tools', 'm2')}`,
    `-Dclassworlds.conf=${path.join(runtime.mavenHome, 'bin', 'm2.conf')}`,
    `-Dmaven.home=${runtime.mavenHome}`, 'org.codehaus.plexus.classworlds.launcher.Launcher',
    ...(runtime.mavenSettings ? ['-s', runtime.mavenSettings] : [])];
}

async function resolveRuntime(toolchain) {
  const javaHome = process.env.NEO_FORGE_JAVA_HOME ?? toolchain.javaHome;
  const mavenHome = process.env.NEO_FORGE_MAVEN_HOME ?? toolchain.mavenHome;
  if (!javaHome || !mavenHome) throw new Error('Set both NEO_FORGE_JAVA_HOME and NEO_FORGE_MAVEN_HOME, or define javaHome and mavenHome in .tools/toolchain.json');
  const executableSuffix = process.platform === 'win32' ? '.exe' : '';
  const java = path.join(javaHome, 'bin', `java${executableSuffix}`);
  const javac = path.join(javaHome, 'bin', `javac${executableSuffix}`);
  const boot = path.join(mavenHome, 'boot');
  const classworlds = (await readdir(boot)).find(file => /^plexus-classworlds.*\.jar$/i.test(file));
  if (!classworlds) throw new Error('Maven classworlds jar is missing');
  const runtime = { java, javac, mavenHome, classworlds: path.join(boot, classworlds),
    mavenSettings: process.env.NEO_FORGE_MAVEN_SETTINGS ?? toolchain.mavenSettings };
  const versions = await Promise.all([
    runProcess(java, ['-version'], { timeoutSeconds: 30 }),
    runProcess(java, [...mavenLauncherArgs(runtime), '-version'], { timeoutSeconds: 30 })]);
  if (versions.some(version => version.code !== 0 || version.timedOut)) throw new Error('Could not observe Java and Maven versions from the configured runtime');
  return { ...runtime, javaVersion: (versions[0].stderr || versions[0].stdout).trim().split(/\r?\n/)[0],
    mavenVersion: (versions[1].stdout + versions[1].stderr).trim().split(/\r?\n/)[0] };
}

function assertContained(parent, target) {
  const relative = path.relative(path.resolve(parent), path.resolve(target));
  if (!relative || relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) throw new Error(`directory escaped intended parent: ${target}`);
}

async function compileRunner(runtime) {
  const evalClasses = path.resolve(ROOT, '.tools', 'eval-classes');
  assertContained(path.join(ROOT, '.tools'), evalClasses);
  await rm(evalClasses, { recursive: true, force: true });
  await mkdir(evalClasses, { recursive: true });
  const compiled = await runProcess(runtime.javac, ['--release', '17', '-cp', JAR, '-d', evalClasses, ENTRY]);
  if (compiled.code !== 0) throw new Error(`evaluation runner compilation failed\n${compiled.stderr}`);
  const hashes = {};
  for (const file of (await readdir(evalClasses, { recursive: true })).sort()) {
    if (file.endsWith('.class')) hashes[file.replaceAll('\\', '/')] = await hashFile(path.join(evalClasses, file));
  }
  if (!hashes['CommanderEval.class']) throw new Error('evaluation runner compilation produced no CommanderEval.class');
  return { evalClasses, hashes };
}

async function build(enginePin, planPath = PLAN) {
  const provenance = assertEngineInputs(enginePin);
  const toolchain = await readToolchain();
  const runtime = await resolveRuntime(toolchain);
  const mavenArgs = [...mavenLauncherArgs(runtime), '-f', 'pom.xml',
    '-pl', 'forge-gui-desktop', '-am', 'clean', 'package', '-DskipTests'];
  const built = await runProcess(runtime.java, mavenArgs, { windowsHide: true });
  if (built.code !== 0) throw new Error(`pinned Maven build failed (${built.code})\n${built.stderr.slice(-5000)}\n${built.stdout.slice(-5000)}`);
  const jarHash = await hashFile(JAR);
  const { evalClasses, hashes } = await compileRunner(runtime);
  const receipt = { schema_version: 1, ...provenance, java_version: runtime.javaVersion, maven_version: runtime.mavenVersion,
    build_command: ['java', ...mavenArgs], jar: path.relative(ROOT, JAR), jar_sha256: jarHash,
    runner_source_sha256: await hashFile(ENTRY), runner_classes_sha256: hashes,
    harness_sha256: { node: await hashFile(path.join(ROOT, 'scripts', 'neo-forge.mjs')),
      node_tests: await hashFile(path.join(ROOT, 'scripts', 'neo-forge.test.mjs')),
      java: await hashFile(ENTRY), plan: await hashFile(planPath), manifest: await hashFile(MANIFEST) },
    built_at: new Date().toISOString() };
  await writeJson(path.join(ROOT, '.tools', 'eval-build-receipt.json'), receipt);
  return { runtime, receipt, classpath: `${evalClasses}${path.delimiter}${JAR}` };
}

async function ensureBuild(enginePin, planPath = PLAN) {
  const provenance = assertEngineInputs(enginePin);
  const toolchain = await readToolchain();
  const receipt = await tryReadJson(path.join(ROOT, '.tools', 'eval-build-receipt.json'));
  if (receipt && receipt.engine_baseline === enginePin && receipt.jar_sha256 === await hashFile(JAR).catch(() => null) &&
      JSON.stringify(receipt.input_trees) === JSON.stringify(provenance.input_trees)) {
    const runtime = await resolveRuntime(toolchain);
    const { evalClasses, hashes } = await compileRunner(runtime);
    receipt.runner_source_sha256 = await hashFile(ENTRY);
    receipt.runner_classes_sha256 = hashes;
    delete receipt.runner_class_sha256;
    receipt.java_version = runtime.javaVersion;
    receipt.maven_version = runtime.mavenVersion;
    receipt.actual_head = provenance.actual_head;
    receipt.workspace_changes = provenance.workspace_changes;
    receipt.harness_sha256 = { node: await hashFile(path.join(ROOT, 'scripts', 'neo-forge.mjs')),
      node_tests: await hashFile(path.join(ROOT, 'scripts', 'neo-forge.test.mjs')),
      java: await hashFile(ENTRY), plan: await hashFile(planPath), manifest: await hashFile(MANIFEST) };
    await writeJson(path.join(ROOT, '.tools', 'eval-build-receipt.json'), receipt);
    return { runtime, receipt, classpath: `${evalClasses}${path.delimiter}${JAR}` };
  }
  return build(enginePin, planPath);
}

function pairings(deckIds, pairing, seatOrders) {
  let raw = pairing === 'cross' ? [[deckIds[0], deckIds[1]]] : [[deckIds[0], deckIds[0]], [deckIds[0], deckIds[1]], [deckIds[1], deckIds[1]]];
  return raw.flatMap(([a, b]) => seatOrders === 'both' && (a !== b || pairing !== 'cross') ? [[a, b], [b, a]] : [[a, b]]);
}

async function runValidate({ planPath = PLAN } = {}) {
  const loadedPlan = await readPlan(planPath);
  const provenance = assertEngineInputs(loadedPlan.plan.engine_commit);
  const { manifest, decks } = await loadFixtures(loadedPlan.plan);
  const buildInfo = await ensureBuild(loadedPlan.plan.engine_commit, planPath);
  const id = `validate-${new Date().toISOString().replaceAll(':', '-')}-${randomUUID().slice(0, 8)}`;
  const out = path.join(ROOT, '.audit', 'ai-runs', id); const gameDir = path.join(out, 'preflight');
  await mkdir(gameDir, { recursive: true });
  await Promise.all(['appdata', 'localappdata', 'tmp'].map(name => mkdir(path.join(gameDir, name), { recursive: true })));
  const copied = [];
  for (const deck of decks) {
    const file = path.join(gameDir, `${deck.id}.dck`); await copyFile(deck.source, file);
    copied.push({ ...deck, staged: file });
  }
  await mkdir(path.join(gameDir, 'assets'), { recursive: true });
  await symlink(path.join(ROOT, 'forge-gui', 'res'), path.join(gameDir, 'assets', 'res'), 'junction');
  const requestId = randomUUID();
  const request = { schema_version: 1, mode: 'validate', id: requestId, seed: 0,
    seats: copied.map(deck => ({ deckId: deck.id, deckFile: deck.staged, commander: deck.commander,
      totalCards: deck.total_cards, expectedSha256: deck.sha256 })),
    profile: 'Default', monte_carlo: 'desktop-max', ai_timeout_seconds: 5, output_directory: gameDir,
    assets_directory: path.join(gameDir, 'assets'), resource_root: path.join(ROOT, 'forge-gui', 'res') };
  await writeJson(path.join(gameDir, 'request.json'), request);
  const result = await runProcess(buildInfo.runtime.java, ['-Djava.awt.headless=true', '-cp', buildInfo.classpath, 'CommanderEval', path.join(gameDir, 'request.json')],
    { env: isolatedEnvironment(gameDir), timeoutSeconds: loadedPlan.startupLimit });
  await writeFile(path.join(gameDir, 'stdout.log'), result.stdout); await writeFile(path.join(gameDir, 'stderr.log'), result.stderr);
  const setup = await tryReadJson(path.join(gameDir, 'setup.json'));
  if (result.code !== 0 || result.timedOut || !setup || setup.status !== 'ready' || setup.request_id !== requestId) throw new Error(`fixture validation failed (exit ${result.code}, timeout ${Boolean(result.timedOut)})\n${result.stderr}`);
  await writeJson(path.join(out, 'validation.json'), { schema_version: 1, plan_sha256: loadedPlan.planHash,
    manifest_sha256: await hashFile(MANIFEST), engine: provenance, build: buildInfo.receipt, validation: setup, decks: decks.map(deck => ({ id: deck.id, sha256: deck.sha256 })) });
  console.log(`Validation evidence: ${out}`);
}

async function evaluate({ planPath = PLAN, pairing = 'plan', gameLimit, startupLimit } = {}) {
  const loadedPlan = await readPlan(planPath, { gameLimit, startupLimit });
  const { planBytes, planHash } = loadedPlan;
  const plan = loadedPlan.plan;
  const provenance = assertEngineInputs(plan.engine_commit);
  const { manifest, decks } = await loadFixtures(loadedPlan.plan);
  const buildInfo = await ensureBuild(plan.engine_commit, planPath);
  const runId = `${new Date().toISOString().replaceAll(':', '-')}-${randomUUID().slice(0, 8)}`;
  const out = path.join(ROOT, '.audit', 'ai-runs', runId); const gamesDir = path.join(out, 'games');
  await mkdir(gamesDir, { recursive: true });
  const planDecks = new Map(decks.map(deck => [deck.id, deck]));
  const jobs = pairings(plan.deck_ids, pairing, plan.seat_orders).flatMap(seats => plan.seeds.map(seed => ({ seats, seed })));
  const manifestHash = await hashFile(MANIFEST);
  const games = [];
  await writeJson(path.join(out, 'request.json'), { schema_version: 1, plan_path: path.relative(ROOT, planPath), plan_sha256: planHash,
    manifest_sha256: manifestHash, engine_commit: plan.engine_commit, ai: plan.ai, game_wall_seconds: loadedPlan.gameLimit,
    startup_wall_seconds: loadedPlan.startupLimit, jobs: jobs.map((job, index) => ({ id: `game-${String(index + 1).padStart(3, '0')}`, ...job })) });
  await writeJson(path.join(out, 'provenance.json'), { engine: provenance, build: buildInfo.receipt,
    harness_sha256: { node: await hashFile(path.join(ROOT, 'scripts', 'neo-forge.mjs')),
      node_tests: await hashFile(path.join(ROOT, 'scripts', 'neo-forge.test.mjs')),
      java: await hashFile(ENTRY), plan: await hashFile(planPath), manifest: manifestHash },
    manifest_sha256: manifestHash,
    plan_sha256: planHash, java_version: buildInfo.runtime.javaVersion, maven_version: buildInfo.runtime.mavenVersion,
    resource_tree: git(['rev-parse', `${plan.engine_commit}:forge-gui/res`]), ai: plan.ai });
  for (const [index, job] of jobs.entries()) {
    if (!Buffer.from(await readFile(planPath)).equals(planBytes)) throw new Error('plan changed while evaluation was running');
    const id = `game-${String(index + 1).padStart(3, '0')}`;
    const gameDir = path.join(gamesDir, id); await mkdir(gameDir, { recursive: true });
    const seats = job.seats.map(deckId => planDecks.get(deckId));
    const staged = [];
    for (let i = 0; i < seats.length; i++) {
      const file = path.join(gameDir, `seat-${i}.dck`); await copyFile(seats[i].source, file);
      staged.push({ deckId: seats[i].id, deckFile: file, commander: seats[i].commander,
        totalCards: seats[i].total_cards, expectedSha256: seats[i].sha256 });
    }
    await mkdir(path.join(gameDir, 'assets'), { recursive: true });
    await symlink(path.join(ROOT, 'forge-gui', 'res'), path.join(gameDir, 'assets', 'res'), 'junction');
    const requestId = randomUUID();
    const request = { schema_version: 1, mode: 'evaluate', id: requestId, seed: job.seed, seats: staged,
      profile: plan.ai.profile, monte_carlo: plan.ai.monte_carlo, ai_timeout_seconds: plan.ai.timeout_seconds,
      output_directory: gameDir, assets_directory: path.join(gameDir, 'assets'), resource_root: path.join(ROOT, 'forge-gui', 'res') };
    const result = await superviseGame(buildInfo.runtime.java, buildInfo.classpath, request, gameDir, loadedPlan.startupLimit, loadedPlan.gameLimit);
    const record = { id, seed: job.seed, seat_decks: job.seats, ...result };
    games.push(record); await writeJson(path.join(gameDir, 'result.json'), record);
    if (result.tree_stopped === false) break;
  }
  if (!Buffer.from(await readFile(planPath)).equals(planBytes)) throw new Error('plan changed during evaluation');
  const counts = Object.fromEntries(['completed', 'timed_out', 'crashed', 'rejected'].map(outcome => [outcome, games.filter(game => game.outcome === outcome).length]));
  const summary = { schema_version: 1, run_id: runId, created_at: new Date().toISOString(), planned_games: jobs.length, recorded_games: games.length,
    counts, all_completed: games.length === jobs.length && counts.completed === jobs.length, games };
  await writeJson(path.join(out, 'summary.json'), summary);
  console.log(`Evaluation evidence: ${out}`);
  console.log(`Outcomes: ${JSON.stringify(counts)}`);
  if (!summary.all_completed) process.exitCode = 3;
}

async function play({ planPath = PLAN } = {}) {
  const { plan } = await readPlan(planPath);
  if (plan.ai.monte_carlo === 'standard') throw new Error('Desktop Forge uses the desktop-max simulation budget. Select desktop-max or off for a playtest.');
  const { runtime, classpath } = await ensureBuild(plan.engine_commit, planPath);
  const desktopPom = await readFile(path.join(ROOT, 'forge-gui-desktop', 'pom.xml'), 'utf8');
  const desktopOptions = desktopPom.match(/<addopen\.java\.args>([^<]+)<\/addopen\.java\.args>/)?.[1].trim();
  if (!desktopOptions) throw new Error('Pinned desktop POM is missing addopen.java.args');
  const baseline = path.join(ROOT, '.tools', 'human-baseline');
  const user = path.join(ROOT, '.tools', 'human-baseline', 'profile');
  const cache = path.join(ROOT, '.tools', 'human-baseline', 'cache');
  const assets = path.join(ROOT, '.tools', 'human-baseline', 'assets');
  await mkdir(user, { recursive: true }); await mkdir(cache, { recursive: true }); await mkdir(assets, { recursive: true });
  await mkdir(path.join(user, 'appdata'), { recursive: true }); await mkdir(path.join(cache, 'local'), { recursive: true });
  await mkdir(path.join(user, 'tmp'), { recursive: true });
  const res = path.join(assets, 'res'); if (!(await stat(res).catch(() => null))) await symlink(path.join(ROOT, 'forge-gui', 'res'), res, 'junction');
  await writeFile(path.join(assets, 'forge.profile.properties'), `userDir=${user.replaceAll('\\', '/')}/\ncacheDir=${cache.replaceAll('\\', '/')}/\n`);
  const baselineDecks = path.join(user, 'decks', 'commander'); await mkdir(baselineDecks, { recursive: true });
  const { decks } = await loadFixtures(plan);
  for (const deck of decks) await copyFile(deck.source, path.join(baselineDecks, `${deck.id}.dck`));
  const requestPath = path.join(baseline, 'play-request.json');
  const startupReceipt = path.join(baseline, 'desktop-started.json');
  await rm(startupReceipt, { force: true });
  await writeJson(requestPath, { schema_version: 1, mode: 'play', id: 'baseline', seed: 0, seats: [], profile: 'Default',
    monte_carlo: plan.ai.monte_carlo, ai_timeout_seconds: plan.ai.timeout_seconds, output_directory: user,
    assets_directory: assets, resource_root: path.join(ROOT, 'forge-gui', 'res') });
  const child = await superviseProcess(runtime.java, [...desktopOptions.split(/\s+/), '-Djava.awt.headless=false', '-cp', classpath, 'CommanderEval', '--play', requestPath], {
    cwd: ROOT, env: { ...process.env, APPDATA: path.join(user, 'appdata'), LOCALAPPDATA: path.join(cache, 'local'), TEMP: path.join(user, 'tmp'), TMP: path.join(user, 'tmp') },
    windowsHide: false, detachAfterStartup: true, startupSeconds: 120,
    startupReceipt: { file: startupReceipt, requestId: 'baseline', status: 'desktop-started', matchPid: true },
    stdoutFile: path.join(baseline, 'stdout.log'), stderrFile: path.join(baseline, 'stderr.log'),
  });
  if (!child.started || child.timedOut) throw new Error(`Forge desktop startup failed (exit ${child.code}, timeout ${Boolean(child.timedOut)}). See ${baseline}`);
  console.log(`Forge desktop initialized (PID ${child.pid}) with baseline profile ${baseline}. Startup evidence: ${startupReceipt}`);
}

function parseArgs(args) {
  const [command, ...rest] = args;
  const options = {};
  for (let index = 0; index < rest.length; index++) {
    const key = rest[index];
    if (key === '--plan') options.planPath = path.resolve(ROOT, rest[++index]);
    else if (key === '--pairing') options.pairing = rest[++index];
    else if (key === '--timeout-seconds') options.gameLimit = Number(rest[++index]);
    else if (key === '--startup-timeout-seconds') options.startupLimit = Number(rest[++index]);
    else if (key === '--help' || key === '-h') return { command: 'help', options: {} };
    else throw new Error(`unknown argument ${key}`);
  }
  if (options.pairing && !['cross', 'plan'].includes(options.pairing)) throw new Error('--pairing must be cross or plan');
  return { command, options };
}

async function main() {
  try {
    const { command, options } = parseArgs(process.argv.slice(2));
    if (command === 'help' || !command) {
      console.log('Usage: node scripts/neo-forge.mjs <build|validate|evaluate|play> [--plan path] [--timeout-seconds n] [--startup-timeout-seconds n] [--pairing cross]');
      return;
    }
    if (command === 'build') { const planPath = options.planPath ?? PLAN; const { plan } = await readPlan(planPath); const result = await build(plan.engine_commit, planPath); console.log(`Pinned build complete. JAR SHA-256 ${result.receipt.jar_sha256}`); }
    else if (command === 'validate') await runValidate(options);
    else if (command === 'evaluate') await evaluate(options);
    else if (command === 'play') await play(options);
    else throw new Error(`unknown command ${command}`);
  } catch (error) {
    console.error(error.stack ?? error.message);
    process.exitCode = 2;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
