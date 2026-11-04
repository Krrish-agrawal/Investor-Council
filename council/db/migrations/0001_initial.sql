-- Investor Council schema v0.2 (see docs/DATABASE_SCHEMA.md). 10 tables.
-- Migrations are immutable once applied (checksummed); add 0002_*.sql for changes.
-- CREATE TABLE IF NOT EXISTS keeps a half-applied run (DDL auto-commits in MySQL) re-runnable.

-- ---------- Human-only: the user's portfolio (processed locally) ----------
CREATE TABLE IF NOT EXISTS portfolios (
  id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  name             VARCHAR(120) NOT NULL,
  origin           ENUM('sample','user') NOT NULL,
  csv_sha256       CHAR(64) NOT NULL,
  base_currency    CHAR(3) NOT NULL DEFAULT 'USD',
  price_as_of      DATE NULL,
  price_source     VARCHAR(120) NOT NULL DEFAULT 'user-supplied (CSV)',
  excluded_rows    INT UNSIGNED NOT NULL DEFAULT 0,
  ingest_warnings  JSON NULL,
  created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_portfolio (csv_sha256, origin)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS holdings (
  id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  portfolio_id   BIGINT UNSIGNED NOT NULL,
  ticker         VARCHAR(16) NOT NULL,
  shares         DECIMAL(18,6) NOT NULL,
  price          DECIMAL(18,4) NOT NULL,
  sector         VARCHAR(80) NULL,
  sector_source  ENUM('csv','edgar_sic','unclassified') NOT NULL DEFAULT 'unclassified',
  CONSTRAINT fk_hold_portfolio FOREIGN KEY (portfolio_id) REFERENCES portfolios(id) ON DELETE CASCADE,
  UNIQUE KEY uq_hold (portfolio_id, ticker),
  CONSTRAINT chk_hold_shares CHECK (shares > 0),
  CONSTRAINT chk_hold_price CHECK (price > 0)
) ENGINE=InnoDB;

-- ---------- Session ----------
CREATE TABLE IF NOT EXISTS research_sessions (
  id                   BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  code                 VARCHAR(8) NOT NULL UNIQUE,
  portfolio_id         BIGINT UNSIGNED NOT NULL,
  target_ticker        VARCHAR(16) NOT NULL,
  target_cik           CHAR(10) NULL,
  target_sector        VARCHAR(80) NULL,
  thesis               TEXT NOT NULL,
  stage                TINYINT UNSIGNED NOT NULL DEFAULT 1,
  status               ENUM('OPEN','FINALIZED','ABORTED') NOT NULL DEFAULT 'OPEN',
  shared_summary_json  JSON NOT NULL,
  data_mode            ENUM('FROZEN_SNAPSHOT') NOT NULL DEFAULT 'FROZEN_SNAPSHOT',
  freshness_cfg_json   JSON NOT NULL,
  session_date         DATE NOT NULL,
  created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_sess_portfolio FOREIGN KEY (portfolio_id) REFERENCES portfolios(id),
  CONSTRAINT chk_sess_stage CHECK (stage BETWEEN 1 AND 3)
) ENGINE=InnoDB;

-- ---------- Frozen sources (content-addressed: one row per exact snapshot) ----------
CREATE TABLE IF NOT EXISTS sources (
  id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  source_key       VARCHAR(160) NOT NULL UNIQUE,
  source_type      ENUM('FINANCIAL_STATEMENT','FILING_TEXT','PRICE') NOT NULL,
  source_name      VARCHAR(160) NOT NULL,
  entity_name      VARCHAR(200) NULL,
  url              VARCHAR(1000) NOT NULL,
  cik              CHAR(10) NULL,
  form_type        VARCHAR(16) NULL,
  accession_no     VARCHAR(24) NULL,
  fiscal_year      SMALLINT NULL,
  fiscal_period    VARCHAR(4) NULL,
  period_start     DATE NULL,
  period_end       DATE NULL,
  filed_date       DATE NULL,
  retrieved_at     DATETIME NOT NULL,
  content_sha256   CHAR(64) NOT NULL,
  snapshot_path    VARCHAR(500) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS evidence_refs (
  id                   BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  code                 VARCHAR(12) NOT NULL,
  session_id           BIGINT UNSIGNED NOT NULL,
  source_id            BIGINT UNSIGNED NOT NULL,
  added_by             ENUM('bull','bear') NOT NULL,
  metric_name          VARCHAR(120) NOT NULL,
  taxonomy             VARCHAR(32) NULL,
  concept              VARCHAR(160) NULL,
  unit                 VARCHAR(32) NULL,
  fact_period_start    DATE NULL,
  fact_period_end      DATE NULL,
  fact_fiscal_year     SMALLINT NULL,
  fact_fiscal_period   VARCHAR(4) NULL,
  fact_form            VARCHAR(16) NULL,
  fact_filed_date      DATE NULL,
  fact_accession       VARCHAR(24) NULL,
  value_num            DECIMAL(28,6) NULL,
  quote                TEXT NULL,
  locator              VARCHAR(200) NULL,
  verification         ENUM('VERIFIED','FAILED','PENDING') NOT NULL DEFAULT 'PENDING',
  verification_detail  VARCHAR(300) NULL,
  flag                 ENUM('NONE','STALE','CONFLICT') NOT NULL DEFAULT 'NONE',
  flag_detail          VARCHAR(500) NULL,
  created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_ev_session FOREIGN KEY (session_id) REFERENCES research_sessions(id) ON DELETE CASCADE,
  CONSTRAINT fk_ev_source  FOREIGN KEY (source_id)  REFERENCES sources(id),
  UNIQUE KEY uq_ev (session_id, code),
  CONSTRAINT chk_ev_payload CHECK (quote IS NOT NULL OR value_num IS NOT NULL)
) ENGINE=InnoDB;

-- ---------- Claims (human ruling columns are written by the human CLI only) ----------
CREATE TABLE IF NOT EXISTS claims (
  id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  code           VARCHAR(12) NOT NULL,
  session_id     BIGINT UNSIGNED NOT NULL,
  agent          ENUM('bull','bear') NOT NULL,
  stage          TINYINT UNSIGNED NOT NULL,
  claim_type     ENUM('FACT','ASSUMPTION','UNVERIFIED','GAP') NOT NULL,
  text           TEXT NOT NULL,
  basis          JSON NULL,
  falsifier      TEXT NULL,
  relevance      TEXT NULL,
  rank_in_brief  TINYINT UNSIGNED NULL,
  downgraded     BOOLEAN NOT NULL DEFAULT FALSE,
  human_ruling   ENUM('accept','reject','needs_evidence') NULL,
  human_note     TEXT NULL,
  ruled_at       DATETIME NULL,
  created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_claim_session FOREIGN KEY (session_id) REFERENCES research_sessions(id) ON DELETE CASCADE,
  UNIQUE KEY uq_claim (session_id, code),
  CONSTRAINT chk_claim_falsifier CHECK (claim_type <> 'ASSUMPTION' OR falsifier IS NOT NULL)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS claim_evidence (
  claim_id     BIGINT UNSIGNED NOT NULL,
  evidence_id  BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (claim_id, evidence_id),
  CONSTRAINT fk_ce_claim FOREIGN KEY (claim_id)    REFERENCES claims(id) ON DELETE CASCADE,
  CONSTRAINT fk_ce_ev    FOREIGN KEY (evidence_id) REFERENCES evidence_refs(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- One row per agent per stage; also holds the stage-3 final position.
CREATE TABLE IF NOT EXISTS submissions (
  id                    BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  session_id            BIGINT UNSIGNED NOT NULL,
  agent                 ENUM('bull','bear') NOT NULL,
  stage                 TINYINT UNSIGNED NOT NULL,
  summary               TEXT NULL,
  concessions           JSON NULL,
  still_holds           JSON NULL,
  could_not_establish   JSON NULL,
  submitted_at          DATETIME NOT NULL,
  CONSTRAINT fk_sub_session FOREIGN KEY (session_id) REFERENCES research_sessions(id) ON DELETE CASCADE,
  UNIQUE KEY uq_sub (session_id, agent, stage)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS challenges (
  id                BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  session_id        BIGINT UNSIGNED NOT NULL,
  from_agent        ENUM('bull','bear') NOT NULL,
  target_claim_id   BIGINT UNSIGNED NOT NULL,
  stance            ENUM('disputes','partly_agrees','agrees','needs_evidence') NOT NULL,
  restated          TEXT NOT NULL,
  argument          TEXT NOT NULL,
  counter_evidence  JSON NULL,
  created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_ch_session FOREIGN KEY (session_id)      REFERENCES research_sessions(id) ON DELETE CASCADE,
  CONSTRAINT fk_ch_claim   FOREIGN KEY (target_claim_id) REFERENCES claims(id) ON DELETE CASCADE,
  UNIQUE KEY uq_ch (session_id, from_agent, target_claim_id)
) ENGINE=InnoDB;

-- ---------- Human-only: output ----------
CREATE TABLE IF NOT EXISTS dossiers (
  id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  session_id     BIGINT UNSIGNED NOT NULL,
  version        SMALLINT UNSIGNED NOT NULL DEFAULT 1,
  body_markdown  MEDIUMTEXT NOT NULL,
  template_ver   VARCHAR(16) NOT NULL,
  human_note     TEXT NULL,
  status         ENUM('DRAFT','FINAL') NOT NULL DEFAULT 'DRAFT',
  created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_dos_session FOREIGN KEY (session_id) REFERENCES research_sessions(id) ON DELETE CASCADE,
  UNIQUE KEY uq_dos (session_id, version)
) ENGINE=InnoDB;
