# Provenance

This skill is a new implementation created from functional requirements for portable long-form fiction work: append-only canon state, rebuildable retrieval, explicit draft transactions, periodic audits, and human approval before manuscript changes.

No source files from `leenbj/novel-creator-skill` are included in this directory. The implementation uses a distinct event-ledger and snapshot architecture, one standard-library command-line tool, and independently written tests and documentation.

Existing novel projects may be used as read-only compatibility fixtures. Their manuscripts, indexes, generated context packs, author corpora, and legacy tool artifacts are not part of this skill and must not be committed when publishing it.

Before public release, choose and add a license for this new code. This provenance note does not grant rights to any third-party corpus or manuscript processed by the skill.
