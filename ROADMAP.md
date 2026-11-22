# Roadmap

What is planned, in the order it is likely to land. Nothing here is promised
by a date. Shipped work moves to [CHANGELOG.md](CHANGELOG.md). Progress is
tracked in the [milestones](https://github.com/memvo/memvo/milestones).

## Next: PDF statements ([0.2](https://github.com/memvo/memvo/milestone/1))

Import text-based PDF statements with the same guarantees as CSV and OFX:
each entry keeps the page and line it came from, and rows that cannot be read
are listed, never guessed. Scanned PDFs (images) are out of scope.

## Then: wallet import from a public address ([0.3](https://github.com/memvo/memvo/milestone/2))

Read the transaction history of a public on-chain address into an account,
with the transaction hash as the receipt. Read-only: Memvo will never ask
for a private key or seed phrase.

## Later ([1.0](https://github.com/memvo/memvo/milestone/3))

- `memvo export`: write any search result back out as CSV with its receipts.
- More bank layouts, driven by
  [statement format requests](https://github.com/memvo/memvo/issues/new?template=statement-format.yml).
- A stable vault schema, so 1.0 can promise that vaults made today still open.

## Not planned

- A hosted or cloud version. Memvo stays a local file.
- Categorising or summarising transactions with a model. Entries stay verbatim.
- Any network access in the core package.
