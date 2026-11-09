# NoshAI — Conversational Recipe Assistant

NoshAI is a conversational recipe assistant built for the GenAI Intern Assignment. It searches, analyzes, matches, and adapts recipes from the Recipe Box dataset.

The system is designed to ground recipe answers in retrieved records and calculate supported dataset statistics programmatically instead of asking an LLM to guess.

## Features

### Task 1 — Recipe search and factual Q&A
- Search recipes by title, ingredients, and instructions using SQLite FTS5.
- Retrieve recipe records using stable recipe IDs.
- Display recipe titles, ingredients, and instructions.
- Parse conversational requests and retain relevant session context.
- Calculate supported recipe statistics from the local database.

### Task 2 — Ingredient-based recipe matching
- Match requested ingredients against existing recipes.
- Normalize selected ingredient synonyms where justified.
- Apply hard ingredient exclusions before accepting a recipe.
- Report matched, missing, and additional ingredients.
- Provide match coverage, ranking information, and estimated instruction-step counts.
- Report when quantity sufficiency cannot be verified.

### Task 3 — Evidence-based ingredient substitution
- Evaluate supported ingredient substitutions in recipe context.
- Use recipes in the local dataset as supporting evidence.
- Show supporting recipe evidence and distinguish direct from indirect evidence.
- Return revised ingredient information and relevant instruction changes for supported substitutions.
- Explain uncertainty and likely effects rather than presenting predictions as verified outcomes.

## Technology

- Python 3.12
- SQLite and SQLite FTS5
- Google Gemini API for structured conversational intent parsing
- Pydantic
- python-dotenv
- ijson
- pytest

## Project structure

```text
NoshAI/
├── data/
│   ├── raw/
│   │   └── extracted/
│   └── processed/
├── evaluation/
│   └── evaluation_report.md
├── src/
│   └── nosh_ai/
│       ├── chat/
│       ├── data/
│       ├── database/
│       ├── retrieval/
│       └── tasks/
├── tests/
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

The raw dataset and generated SQLite database are intentionally not committed to this repository.

## Dataset

Source: https://eightportions.com/datasets/Recipes/

The project uses all three dataset JSON files:

- `recipes_raw_nosource_ar.json`
- `recipes_raw_nosource_epi.json`
- `recipes_raw_nosource_fn.json`

The local dataset audit recorded 125,164 recipes:

- AR: 39,802
- EPI: 25,323
- FN: 60,039

Dataset attribution:

> Contains information from Recipe Box (https://eightportions.com/datasets/Recipes/) which is made available under the ODC Attribution License (https://opendatacommons.org/licenses/by/1-0/).

### Dataset setup

1. Download the Recipe Box dataset from the source website.
2. Create `data/raw/extracted` in the repository.
3. Extract or copy the three JSON files listed above into `data/raw/extracted`.
4. Keep the original source files unchanged.

Expected paths:

```text
data/raw/extracted/recipes_raw_nosource_ar.json
data/raw/extracted/recipes_raw_nosource_epi.json
data/raw/extracted/recipes_raw_nosource_fn.json
```

## Installation

Python 3.12 is recommended.

### Windows PowerShell

```powershell
git clone https://github.com/YOUR_USERNAME/NoshAI.git
cd NoshAI

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt

Copy-Item .env.example .env
```

Open `.env` and add your Google Gemini API key:

```text
GEMINI_API_KEY=your_actual_api_key
GEMINI_MODEL=gemini-3.7-flash
```

The current intent-parser configuration defaults to `gemini-3.7-flash` when `GEMINI_MODEL` is not supplied. Use a model identifier enabled for your Google AI Studio API key if that default is unavailable to your account.

Do not commit `.env` or share the API key.

If PowerShell blocks virtual-environment activation, invoke the environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Dataset ingestion

After placing all three JSON files in `data/raw/extracted`, run:

```powershell
python src/nosh_ai/data/ingest.py
```

The ingestion script creates:

```text
data/processed/recipes.db
```

It also writes ingestion and verification reports under `data/processed`.

Do not run ingestion again when the database is already populated. The script requires an explicit `--reset` option to rebuild existing imported records. Use that option only when you intentionally want to rebuild the database.

## Run the chatbot

From the repository root:

```powershell
python src/nosh_ai/chat/assistant.py
```

The chatbot accepts conversational requests in the terminal. Enter `exit` to quit and `reset` to clear conversation memory.

Example requests:

```text
Find a penne pasta recipe.
Show me the details of the first recipe.
Find recipes containing chicken but exclude peanuts.
Replace butter with olive oil in Potage Dame Edmee.
How many recipes contain garlic and onion?
```

The exact questions supported depend on the available dataset and implemented functionality.

## Run automated tests

```powershell
python -m pytest -v
```

The current test suite contains ingredient-matching and substitution tests.

## Evaluation

See `evaluation/evaluation_report.md` for recorded automated checks, manual conversational checks, reproducible evaluation prompts, and known limitations. The report distinguishes observed results from tests that remain to be executed.

## Design decisions

- SQLite FTS5 provides local full-text retrieval.
- Original recipe fields are retained separately from searchable normalized text.
- Ingredient aliases are used only where equivalence is justified.
- Ingredient matching reports explicit match information and ranking signals.
- Statistics are calculated from database records rather than generated by the LLM.
- Substitution recommendations use local recipe evidence and label indirect evidence.
- Unsupported facts should be reported as unavailable instead of fabricated.

## Known limitations

- The source dataset contains incomplete records, noisy text, and advertisement markers.
- Ingredient exclusions depend on text present in recipe records and cannot guarantee allergen safety.
- Some ingredient synonyms and dairy derivatives may not yet be recognized.
- Quantity sufficiency is not always verifiable from source data.
- Instruction-step counts are estimates based on the available instruction text and are not necessarily verified cooking steps.
- Substitution support is limited to implemented ingredient rules. Predictions about taste and texture are not experimentally verified.
- In the observed dairy follow-up example, the assistant scanned the full dataset rather than only filtering the previous five displayed results, and one result containing Parmigiano-Reggiano was not excluded. See the evaluation report.

## AI tool disclosure

AI coding assistance was used for planning, debugging suggestions, code-review support, and documentation preparation. The implementation was reviewed and executed locally. The developer is responsible for understanding and explaining the retrieval, matching, ranking, computation, and substitution logic.

## Dataset license and attribution

The Recipe Box dataset is made available under the ODC Attribution License. Retain the attribution above when redistributing work derived from the dataset. Consult the dataset source for the original terms.
