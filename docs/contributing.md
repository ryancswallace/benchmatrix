# Contributing

Contributions are welcome. For substantial changes, open an issue first so the
problem and direction can be discussed.

Before submitting a pull request:

```bash
make format
make check
```

When the change may differ across Python versions or packaging environments,
also run:

```bash
make test-matrix
```

Pull requests should:

* stay focused on one coherent change;
* include tests for behavior changes;
* update documentation and the changelog when users will notice the change;
* avoid broad lint or type-check suppressions unless there is no cleaner option.

Report security vulnerabilities through the security policy, not a public issue.
