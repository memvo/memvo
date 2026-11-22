# Contributing

Thanks for looking. Memvo is small on purpose: standard library only, one
SQLite file, no network. Changes that keep it that way are the easiest to
merge.

## Setup

```bash
git clone https://github.com/memvo/memvo
cd memvo
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest --cov
```

Coverage must stay at or above 90%. The suite blocks network access, so a
change that opens a socket fails.

## Statement formats

A new bank layout is the most useful contribution. Please:

1. Add a small, **made-up** file to `tests/fixtures/`. Never commit a real
   statement, even with names removed.
2. Add the header names to `_ALIASES` in `src/memvo/importers/csv_rows.py`
   if they are not detected already.
3. Add a test that imports the file and checks a receipt.

## Pull requests

- One topic per pull request, with a line in `CHANGELOG.md` under
  "Unreleased".
- Keep entries verbatim. Anything that rewrites, summarises or guesses at a
  stored row will not be merged.
- New run-time dependencies need a strong reason.
- `main` is protected: every change, including the maintainers', lands
  through a pull request with signed commits and a green test matrix on
  Linux, macOS and Windows plus CodeQL. Force pushes and deletion are blocked.

## Security

Do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).
