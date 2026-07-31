# Deprecations

Deprecations provide a safe migration path away from documented public API or
behavior while preserving compatibility within the current major release
series.

## What requires deprecation

Use a deprecation path for changes to documented public API, especially names
exported from `benchmatrix.__init__` or behavior described in tutorials,
how-to guides, or reference documentation. The same rule applies to stable CLI
commands and options, configuration keys, built-in policy defaults, and
supported serialized-document versions.

Deprecation is not required for:

* private modules such as `_schema.py`;
* private names beginning with `_`;
* undocumented implementation details;
* behavior that is removed immediately for security or serious correctness
    reasons.

## Timing

Deprecated public API remains available until the next major release unless an
urgent security or correctness issue requires earlier removal. Every
deprecation identifies its replacement and is retained in tests until removal.

## Deprecation checklist

1. document the replacement or migration path;
2. add tests that preserve the deprecated behavior until removal;
3. add a changelog entry;
4. include removal timing when known;
5. mention the deprecation in release notes;
6. avoid deprecating private implementation details that were never supported.

## Removal checklist

1. confirm the changelog mentioned the deprecation;
2. confirm the removal timing has arrived or the security/correctness exception
     applies;
3. remove the behavior and tests together;
4. update API docs, tutorials, examples, and compatibility notes;
5. run `make check` and `make test-matrix`.
