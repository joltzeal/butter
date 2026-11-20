-- Codes are the only source of truth; a licence never grants time by itself.
-- `seconds` is added to the licence on each redemption, so two 1-week codes make
-- two weeks regardless of when they are entered.
CREATE TABLE IF NOT EXISTS codes (
  code        TEXT PRIMARY KEY,
  plan        TEXT NOT NULL,
  seconds     INTEGER NOT NULL,
  bound       TEXT,             -- machine fingerprint, NULL until redeemed
  redeemed_at INTEGER,
  revoked     INTEGER NOT NULL DEFAULT 0,
  created_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS codes_bound ON codes(bound);

-- One row per machine: the licence's clock lives here, not in the token.
CREATE TABLE IF NOT EXISTS licences (
  machine     TEXT PRIMARY KEY,
  plan        TEXT NOT NULL,
  exp         INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);
