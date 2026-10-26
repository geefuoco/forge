# AI evaluation runner design

## Problem and usage

The first milestone needs real Commander games with trusted results and preserved upstream behavior. Upstream `SimulateMatch` catches exceptions and timeouts and forces an unfinished game to a draw; it is not the authoritative outcome boundary for this evaluation.

The caller uses `node scripts/neo-forge.mjs build`, then `node scripts/neo-forge.mjs validate`, `node scripts/neo-forge.mjs evaluate`, or `node scripts/neo-forge.mjs play`. All commands run from a checkout and resolve paths independently of the caller's current directory. Evaluation creates a new result directory and prints its path. Build and evaluation failures return nonzero.

## Shape

Keep the upstream Java source unchanged. One external Java main owns Forge setup, strict fixture loading, Commander legality, match creation, explicit AI configuration, and a natural terminal receipt. A Node 22 command uses built-in modules to build, compile that main, supervise a separate JVM per game, isolate writable profiles, classify outcomes, and aggregate evidence. It also opens the existing desktop application in an isolated baseline profile for a later human playtest.

The input is a versioned request with `mode`, `seed`, two ordered deck IDs, a named AI profile, an explicit Monte Carlo mode, paths to the authoritative fixture manifest and output directory, and an absolute resource root. The fixture manifest remains the sole list of deck identities, expected commanders, counts, and hashes. A suite plan defines seeds and pairings without repeating fixture metadata.

Each game has one of `completed`, `timed_out`, `crashed`, or `rejected` outcomes. Only a completed game can carry an engine win or draw. The Java child owns its atomic setup and terminal receipts; the Node parent alone owns the final game result. A clean process exit without valid matching evidence is not completion. The supervisor owns process deadlines and teardown rather than assuming engine thread interruption is safe. Startup and game execution have separate deadlines.

Every child receives a unique writable profile, cache, temporary directory, and log destination. Its absolute asset overlay uses the pinned read-only `res` tree and a private `forge.profile.properties`, or it receives a proven equivalent profile isolation mechanism. Never edit the user's normal Forge profile. A GUI playtest has its own persistent profile, separate from evaluation games.

Build provenance identifies the full upstream SHA, unchanged upstream build inputs, harness source hashes, actual JAR and runner hashes, fixture hashes, selected plan, runtime versions, and AI settings. Local documentation and harness changes are allowed and recorded; they must not masquerade as a clean whole repository. Rebuild rather than reusing unverified stale outputs. A seed fixes input randomness but does not guarantee identical Monte Carlo decisions under different timing and scheduling.

The runtime record contains native Java and compiler paths, Maven home, the classworlds JAR, and optional Maven settings. Version checks and package builds use the same settings. Machine paths stay in ignored toolchain configuration. The cloud setup command connects that configuration to installed tools and the shared dependency cache. Fixture attributes disable line-ending conversion to preserve manifest hashes.

The desktop JVM receives the module-access options declared by the pinned desktop POM. The classpath launch bypasses Forge's generated platform launcher, so it supplies those arguments itself. Headless evaluation does not use them.

## Synthesis decision

The original design records three architect candidates and a cross-judge under local `.audit/architecture/`. Those review artifacts are unavailable in this restored workspace. The recorded decision selects Candidate B because one external game process gives strong failure classification and isolation while preserving upstream. Candidate A contributes strict loaded-card comparison and explicit asset/profile isolation. Candidate C's additional upstream classes and in-process cancellation are rejected as unnecessary for this bounded milestone.

Node replaces the candidates' PowerShell supervisor proposal. Node 22 is already available, has argument-array process APIs and a built-in test runner, and removes shell quoting from normal Java execution. The original design records cross-judge acceptance in the unavailable `.audit/architecture/judge.md`. Current runtime verification is in the [baseline report](ai-baseline-report.md). Keep one command module and one Java class with private helpers; do not introduce a framework or a new reactor module.

The Model the Domain principle determines the outcome records. Separate Before Serializing Shared State determines per-game JVMs and single ownership of each receipt. Build the Lever determines the repeatable command. Prove It Works determines real startup, timeout, bad-input, and natural-completion checks.

## Reconciliation and limits

This is a mechanical engine integration, not a new frontend architecture. No additional human checkpoint is needed under the user's implementation instruction. Runtime findings must update this design before the unit closes if they change ownership or outcomes.

The first implementation establishes setup, legality, execution, and honest evidence. It does not establish human enjoyment, 60 FPS, one-second CPU decisions, remote invites, durable saves, or faithful replay. Those remain the milestones in the accepted product specification.
