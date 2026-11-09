# NoshAI Evaluation Report

## Evaluation purpose

This report records observed behavior for the GenAI Intern Assignment. It distinguishes executed checks from planned conversations. A test is not marked as passed unless its result was actually observed.

## 1. Automated tests

A previous full test run completed with:

- **27 tests passed**.
- Runtime: 0.92 seconds.
- Covered files: `test_ingredient_matcher.py` and `test_substitution.py`.

This full test run occurred before the most recent dairy-category helper was added. The full suite has not been rerun after that change.

## 2. Dairy category checks

After adding the dairy-category helper, 13 targeted checks were executed.

Passed examples included whole milk, cheddar cheese, unsalted butter, heavy cream, Greek yogurt, whey protein, and ghee. The checks also confirmed that selected plant-based alternatives such as coconut milk, oat milk, and almond milk were not treated as dairy.

**Result: 13/13 targeted checks passed.** These are text-matching checks only. They do not establish allergy safety.

## 3. Recorded conversational checks

### Conversation 1 — Recipe search followed by a dairy restriction

User:
1. `Find a penne pasta recipe.`
2. `I cannot have dairy. Refine the previous search.`

Observed:
- Initial search returned five penne pasta recipes.
- The follow-up triggered a full scan of 122,971 recipes.
- 77 recipes qualified for penne pasta after the active dairy exclusion.
- A displayed result contained Parmigiano-Reggiano despite the dairy exclusion.

**Assessment result: PARTIAL / FAIL against the exact follow-up example.**

Reason: the follow-up should refine the previous search results; the observed run performed a full-dataset ingredient match instead. The dairy category filter also failed to recognize Parmigiano-Reggiano in the displayed result. This must not be represented as a fully passing follow-up test.

### Conversation 2 — Evidence-based butter substitution

User: `Replace butter with olive oil in Potage Dame Edmee.`

Observed:
- The substitution planner returned `supported_with_caveats`.
- Evidence was indirect.
- The planner reported 33,282 supporting recipes and 19,429 same-method evidence records.
- It reported zero direct substitution evidence.
- Quantity conversion was not performed.
- The outcome was not experimentally verified.

**Assessment result: PASS WITH CAVEATS for this demonstrated supported case.** The system communicated uncertainty and did not present indirect recipe evidence as a verified cooking experiment.

## 4. Reproducible conversational evaluation set — execution still required

The following prompts are included to make the remaining evaluation reproducible. Their final conversational outcomes have not yet been recorded. Do not claim them as passed until they have been run and their actual outputs documented.

### Conversation 3 — Aggregate statistics

Prompt: `How many recipes contain both garlic and onion? What percentage of the dataset is that?`

Expected: compute the count against the complete relevant dataset; state the denominator; explain ingredient-name normalization; calculate the percentage programmatically.

Status: **NOT YET RECORDED**.

### Conversation 4 — Ranking by instruction steps

Prompt: `Among recipes containing tomato, which five have the fewest instruction steps?`

Expected: retrieve the complete filtered set of tomato recipes; apply a defined instruction-step counting rule; return five ranked recipes with stable IDs; explain when the count is an estimate.

Status: **NOT YET RECORDED**.

### Conversation 5 — Ingredient matching with hard constraints

Prompt: `I have eggs, onions, tomatoes, and rice. Suggest five recipes using as many of these as possible, with no peanuts and at most six instruction steps. Prefer recipes that need the fewest additional ingredients.`

Follow-up: `Exclude eggs too.`

Expected: rank eligible existing recipes; show matched, missing, and additional ingredients; enforce the peanut exclusion and six-step maximum; update active criteria after the follow-up; do not silently relax hard restrictions.

Status: **NOT YET RECORDED**.

### Conversation 6 — No-match case

Prompt: `Find recipes containing chicken and exclude chicken.`

Expected: return no eligible matches when requested and excluded ingredient conditions conflict; explain why no recipe qualifies; do not silently relax the exclusion.

Status: **NOT YET RECORDED**.

## 5. Ungrounded-answer comparison — execution still required

Prompt: `What is the exact calorie count of Pat's Simple Penne?`

Expected grounded-system behavior:
- Check whether the local recipe data contains nutrition information.
- State that an exact calorie count cannot be established when the data does not contain it.
- Do not fabricate an exact number.

A one-shot LLM baseline response has not been recorded. Do not claim that a particular baseline answer was observed until it is actually tested.

Status: **NOT YET RECORDED**.

## 6. Known limitations

- The dataset contains incomplete records and noisy ingredient text.
- Ingredient exclusions depend on text present in recipe records.
- Ingredient category matching is not a medical allergy guarantee.
- Some dairy derivatives and less common ingredient names may be missed.
- Quantity comparisons are reported as unverified where source quantities or units do not support a reliable comparison.
- Instruction-step counts are estimates unless the source provides an explicit structured step list.
- Substitution evidence can be indirect and does not prove a cooking outcome.
- The previous-search dairy follow-up requires further correction.

## 7. Reproduction commands

From the repository root, with the virtual environment activated:

```powershell
python -m pytest -v
python src/nosh_ai/chat/assistant.py
```

The chatbot requires a valid `GEMINI_API_KEY` in `.env`. See the root README for dataset setup and installation instructions.
