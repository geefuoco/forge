# Installed client verification status

The accepted target is [the player-hosted client and relay plan](player-hosted-plan.md). The current published Site is the earlier companion prototype. No public relay or native Windows release has been deployed by this change.

The relay HTTP suite passes nine tests. The Java client socket checks pass for local origin boundaries, profile persistence across ports, and lost acknowledgement behavior using a stub relay. Four packaging tests pass for release identity, relay URL validation, manifest folding, and exact payload contents. These checks are component evidence, not proof that two installed clients can play.

Integrated native package, real-engine browser checks, and exactly two independent verifier results are pending. Native Windows and public separate-network checks remain release gates. No general AI-quality, durable recovery, or rendering-performance claim is made.
