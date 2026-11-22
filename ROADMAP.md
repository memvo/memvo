# Roadmap

What is planned, in the order it is likely to land. Nothing here is promised
by a date. Shipped work moves to [CHANGELOG.md](CHANGELOG.md); PDF statements
shipped in 0.2.0a1. Progress is tracked in the
[milestones](https://github.com/memvo/memvo/milestones).

## Next: wallet import from a public address ([0.3](https://github.com/memvo/memvo/milestone/2))

Read the transaction history of a public on-chain address into an account,
with the transaction hash as the receipt. Read-only: Memvo will never ask
for a private key or seed phrase.

## Later ([1.0](https://github.com/memvo/memvo/milestone/3))

- `memvo export`: write any search result back out as CSV with its receipts.
- More bank layouts, driven by
  [statement format requests](https://github.com/memvo/memvo/issues/new?template=statement-format.yml).
- A stable vault schema, so 1.0 can promise that vaults made today still open.

## How the order after 0.3 is chosen

Once the $MEMVO coin is live on Robinhood Chain, its holders vote on which
item from the Later list ships next. The vote runs on
[memvo.pro/vote](https://memvo.pro/vote); until the coin is live there is
nothing to vote on.

- The option with the most weight when a vote closes becomes the next
  milestone, after the one in progress.
- Weight is the voter's balance at one snapshot block, set when the vote opens.
- Voters sign a message with their wallet. No transaction, no gas, never a key.
- The liquidity pool, burn address, launchpad contract and team wallets are
  not counted.
- Only items from the Later list are on a ballot. Nothing under Not planned
  can be voted in.
- The vote sets the order of work only. It does not control the code,
  releases or any funds, and the package works the same without the coin.
- Every signed vote is public, and anyone can recount the result from the
  chain with the script linked on the vote page.

## Not planned

- A hosted or cloud version. Memvo stays a local file.
- Categorising or summarising transactions with a model. Entries stay verbatim.
- Any network access in the core package.
