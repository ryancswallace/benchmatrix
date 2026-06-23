# Deprecations

Deprecations should be rare before 1.0, but they are still useful when users need
a safe migration path away from documented public API or behavior.

## What requires deprecation

Use a deprecation path for changes to documented public API, especially names
exported from `benchmatrix.__init__` or behavior described in tutorials,
how-to guides, or reference documentation.

Deprecation is not required for:

* private modules such as `_schema.py`;
* private names beginning with `_`;
* undocumented implementation details;
* behavior that is removed immediately for security or serious correctness
    reasons.

## Timing

Before 1.0, deprecated public API should normally remain available until at least
the next minor release. For example, a deprecation introduced in `0.2.0` should
normally remain through the `0.2.x` line and may be removed in `0.3.0`.

After 1.0, deprecated public API should normally remain available until the next
major release unless release notes document a narrower exception.

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
