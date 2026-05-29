# scadforge

prompt → openscad → preview, in a tiny django app.

## setup

```bash
cd openscad
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# install the openscad cli (macOS):
brew install --cask openscad

# optional: enable LLM generation + postgres
cat > .env <<'EOF'
OPENAI_API_KEY=your_key_here
# DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/forge
EOF

python manage.py makemigrations sketches
python manage.py migrate
python manage.py runserver
# open http://127.0.0.1:8000/

# ingest CalTrans standards into Django tables
python manage.py ingest_bridge_standards --limit 10 --skip-embeddings
```

open the built-in database explorer at `/db/` for a sticky, read-only view of
sketches, standards, chunks, and vector state.

without `GEMINI_KEY`, a keyword heuristic produces SCAD for words like
*sphere, cylinder, tube, hex nut, ring, gear, pyramid, block*. with the
key set, prompts go through `gemini-1.5-flash`.

the compose screen now supports either a freeform prompt or a structured
bridge request with type, dimensions, material intent, requested features,
and export targets. the resolved request is stored on each sketch so later
validation, rag retrieval, and component extraction can use the same inputs.

## env (.env)

| key          | default                       | notes                          |
| ------------ | ----------------------------- | ------------------------------ |
| `SECRET_KEY` | dev placeholder               | set for prod                   |
| `DEBUG`      | `1`                           | `0` for prod                   |
| `GEMINI_KEY` | unset                         | enables LLM generation         |
| `OPENAI_API_KEY` | unset                     | enables ChatGPT/OpenAI generation |
| `OPENAI_MODEL` | `gpt-5.5`                  | model used for OpenAI generation |
| `OPENAI_BASE_URL` | OpenAI API              | compatible API endpoint        |
| `OPENAI_EMBED_MODEL` | `text-embedding-3-small` | embeddings model for standards chunks |
| `OPENAI_EMBED_DIM` | `1536` | expected embedding size for pgvector storage |
| `PREFERRED_PROVIDER` | `openai`              | `openai` or `gemini`           |
| `BRIDGE_TEMPLATE_FIRST` | `1`                | reliable seeded bridge MVP     |
| `DATABASE_URL` | unset | postgres DSN, e.g. `postgresql://user:pass@host:5432/db` |
| `POSTGRES_DB` | unset | fallback postgres db name if no `DATABASE_URL` |
| `POSTGRES_USER` | `postgres` | fallback postgres username |
| `POSTGRES_PASSWORD` | unset | fallback postgres password |
| `POSTGRES_HOST` | unset | fallback postgres host |
| `POSTGRES_PORT` | `5432` | fallback postgres port |
| `STANDARDS_STORAGE_DIR` | `standards_store/` | where downloaded CalTrans PDFs are cached |
| `STANDARDS_CHUNK_SIZE` | `1600` | chunk size for extracted standards text |
| `STANDARDS_CHUNK_OVERLAP` | `200` | overlap between adjacent chunks |
| `SCAD_BIN`   | auto                          | path to openscad binary        |
| `RENDER_PX`  | `640`                         | png preview size               |

## postgres first, sqlite fallback

sqlite remains the default for local prototyping. if `DATABASE_URL` or the
`POSTGRES_*` vars are present, django will switch to postgres automatically.
this keeps local setup simple while making it easy to move sketches,
components, and future rag tables onto postgres. when postgres is active,
embedded standards chunks are also mirrored into a `pgvector` table for
similarity search.

## database explorer

visit `/db/` to inspect:

- sketches and export selections
- ingested bridge standards
- extracted text chunks and embedding status
- whether pgvector-backed rows are active

## next rag upgrade path

the standards pipeline now downloads CalTrans PDFs into django-managed records,
extracts text with PyMuPDF, chunks it, and can optionally request embeddings.
OCR is still best-effort and only runs when `pytesseract` is available locally.

current usage:

```bash
python manage.py ingest_bridge_standards --limit 25 --skip-embeddings
python manage.py ingest_bridge_standards --refresh
```

next clean step is:

1. move chunk embeddings from json storage to pgvector-backed columns
2. add approximate nearest-neighbor indexes in postgres
3. retrieve standards context during validation and generation
4. rank chunks against structured bridge requests before model generation

## layout

- [forge/](forge/) — django project
- [sketches/](sketches/) — app: views, forms, model
- [sketches/pipeline/](sketches/pipeline/) — prompt→scad + cli runner
- [renders/](renders/) — created at runtime; png + stl outputs
