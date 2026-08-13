"""Reference host implementation for the ext/v1 extension contract.

`runtime/` is deliberately *not* named after any vendor: it is one binding of
the contract (see portability/ for a second). Layout:

    runtime/host/      the trusted core: loader, registry, gate, broker, egress,
                       sandbox, audit
    runtime/backends/  simulated external SaaS (issue tracker, KB, CI/CD)
    runtime/cli/       the `ext` developer CLI (scaffold / validate / test / run)
    runtime/tests/     contract, security, governance and portability tests
    runtime/demos/     runnable proofs of the acceptance criteria
"""
