CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE groups (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text UNIQUE NOT NULL,            -- 'engineering', 'hr', 'all-staff', 'admins'
  description text
);

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL,                  -- unique case-insensitively, see users_email
  display_name text NOT NULL,
  password_hash text NOT NULL,          -- argon2id
  failed_logins int NOT NULL DEFAULT 0,
  locked_until timestamptz,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX users_email ON users (lower(email));

CREATE TABLE user_groups (
  user_id uuid REFERENCES users ON DELETE CASCADE,
  group_id uuid REFERENCES groups ON DELETE CASCADE,
  PRIMARY KEY (user_id, group_id)
);

CREATE TABLE folders (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  path text UNIQUE NOT NULL,            -- '/sources/hr/policies'
  acl_groups uuid[] NOT NULL,
  last_scanned_at timestamptz
);

CREATE TABLE documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source text NOT NULL,                 -- 'upload' or 'folder'
  folder_id uuid REFERENCES folders,    -- nearest mapped folder, null for uploads
  path text,                            -- file path under the folder, null for uploads
  title text NOT NULL,
  mime_type text NOT NULL,
  size_bytes bigint NOT NULL,
  file_mtime timestamptz,
  content_hash text NOT NULL,
  acl_groups uuid[] NOT NULL DEFAULT '{}',   -- written via effective_acl(), never empty
  status text NOT NULL DEFAULT 'queued',
  indexed_at timestamptz,
  UNIQUE (source, path)
);
CREATE INDEX documents_folder ON documents (folder_id);

CREATE TABLE chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES documents ON DELETE CASCADE,
  position int NOT NULL,
  heading_path text,
  text text NOT NULL,
  token_count int NOT NULL,
  page int,
  acl_groups uuid[] NOT NULL,           -- copy of documents.acl_groups (D15)
  embed_model text NOT NULL,            -- 'BAAI/bge-small-en-v1.5'
  embedding vector(384) NOT NULL,
  tsv tsvector GENERATED ALWAYS AS (
    to_tsvector('english', coalesce(heading_path, '') || ' ' || text) ||
    to_tsvector('simple', text)
  ) STORED
);
CREATE INDEX chunks_embedding_hnsw ON chunks
  USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv);
CREATE INDEX chunks_acl_gin ON chunks USING gin (acl_groups);
CREATE INDEX chunks_document ON chunks (document_id);

CREATE TABLE conversations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users,
  title text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id uuid NOT NULL REFERENCES conversations ON DELETE CASCADE,
  role text NOT NULL,                   -- 'user' or 'assistant'
  content text NOT NULL,
  rewritten_query text,
  citations jsonb NOT NULL DEFAULT '[]',  -- [{n, chunk_id, document_id}]
  flags text[] NOT NULL DEFAULT '{}',   -- 'not_found', 'low_grounding', 'stopped'
  model text,
  prompt_tokens int, output_tokens int,
  queue_ms int, first_token_ms int, latency_ms int,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX messages_conversation ON messages (conversation_id, created_at);

CREATE TABLE feedback (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id uuid NOT NULL REFERENCES messages ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users,
  rating smallint NOT NULL CHECK (rating IN (-1, 1)),
  comment text,
  UNIQUE (message_id, user_id)
);

CREATE TABLE jobs (
  id bigserial PRIMARY KEY,
  kind text NOT NULL,                   -- 'ingest' or 'folder_scan'
  payload jsonb NOT NULL,
  status text NOT NULL DEFAULT 'queued',  -- queued, running, done, failed
  attempts int NOT NULL DEFAULT 0,
  run_after timestamptz NOT NULL DEFAULT now(),
  last_error text
);
CREATE INDEX jobs_ready ON jobs (run_after) WHERE status = 'queued';

CREATE TABLE audit_log (
  id bigserial PRIMARY KEY,
  user_id uuid NOT NULL,
  action text NOT NULL,                 -- 'query', 'view_chunk', 'acl_change', 'login'
  detail jsonb NOT NULL,                -- retrieved chunk ids, groups used
  at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
  id text PRIMARY KEY,                  -- SHA-256 of a random 256-bit token
  user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
  expires_at timestamptz NOT NULL
);

INSERT INTO groups (name, description) VALUES ('admins', 'Administrators, and owners of every document shared with no group');
