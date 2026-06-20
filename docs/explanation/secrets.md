# Secrets

No credentials should be committed to this repository.

## Local checks

detect-secrets scans repository files through:

```bash
make secrets
```

The baseline is reviewed project state, not a place to hide known credentials.
Additions to `.secrets.baseline` must be reviewed before commit.

## If a secret is found

1. stop using the exposed credential;
2. rotate or revoke it at the provider;
3. remove it from the working tree;
4. decide whether history rewriting or public disclosure is required;
5. update tests or examples to use placeholders that are clearly fake.
