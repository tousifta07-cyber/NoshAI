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

### Conversation 1 â€” Recipe search followed by a dairy restriction

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

### Conversation 2 â€” Evidence-based butter substitution

User: `Replace butter with olive oil in Potage Dame Edmee.`

Observed:
- The substitution planner returned `supported_with_caveats`.
- Evidence was indirect.
- The planner reported 33,282 supporting recipes and 19,429 same-method evidence records.
- It reported zero direct substitution evidence.
- Quantity conversion was not performed.
- The outcome was not experimentally verified.

**Assessment result: PASS WITH CAVEATS for this demonstrated supported case.** The system communicated uncertainty and did not present indirect recipe evidence as a verified cooking experiment.

## 4. Reproducible conversational evaluation set â€” execution still required

The following prompts are included to make the remaining evaluation reproducible. Their final conversational outcomes have not yet been recorded. Do not claim them as passed until they have been run and their actual outputs documented.

### Conversation 3 â€” Aggregate statistics

Prompt: `How many recipes contain both garlic and onion? What percentage of the dataset is that?`

Expected: compute the count against the complete relevant dataset; state the denominator; explain ingredient-name normalization; calculate the percentage programmatically.

Status: **NOT YET RECORDED**.

### Conversation 4 â€” Ranking by instruction steps

Prompt: `Among recipes containing tomato, which five have the fewest instruction steps?`

Expected: retrieve the complete filtered set of tomato recipes; apply a defined instruction-step counting rule; return five ranked recipes with stable IDs; explain when the count is an estimate.

Status: **NOT YET RECORDED**.

### Conversation 5 â€” Ingredient matching with hard constraints

Prompt: `I have eggs, onions, tomatoes, and rice. Suggest five recipes using as many of these as possible, with no peanuts and at most six instruction steps. Prefer recipes that need the fewest additional ingredients.`

Follow-up: `Exclude eggs too.`

Expected: rank eligible existing recipes; show matched, missing, and additional ingredients; enforce the peanut exclusion and six-step maximum; update active criteria after the follow-up; do not silently relax hard restrictions.

Status: **NOT YET RECORDED**.

### Conversation 6 â€” No-match case

Prompt: `Find recipes containing chicken and exclude chicken.`

Expected: return no eligible matches when requested and excluded ingredient conditions conflict; explain why no recipe qualifies; do not silently relax the exclusion.

Status: **NOT YET RECORDED**.

## 5. Ungrounded-answer comparison â€” execution still required

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

## 8. Latest verified evaluation updates

These observations were recorded after the earlier evaluation entries above. Where a later run corrected an earlier failure, both observations are retained rather than silently rewriting the history.

### Conversation 1 â€” Corrected dairy follow-up rerun

User:
1. `Find a penne pasta recipe.`
2. `I cannot have dairy. Refine the previous search.`

Latest observed:
- The initial search returned five penne pasta recipes.
- The follow-up evaluated those five previous results, rather than performing a full-dataset search.
- Two recipes remained eligible.
- Three recipes were removed by the dairy restriction.
- The follow-up used the previous-search-results scope.

**Latest rerun result: PASS for previous-result refinement and the observed dairy filtering.**

The earlier failed run remains documented in Section 3. The successful rerun demonstrates the corrected behavior for this test case; it does not establish perfect dairy detection across the entire dataset.

### Conversation 3 â€” Aggregate statistics

Prompt: `How many recipes contain both garlic and onion? What percentage of the dataset is that?`

Observed:
- Garlic: 37,344 recipes.
- Onion: 40,419 recipes.
- Both garlic and onion: 21,735 recipes.
- Dataset denominator: 125,164 recipes.
- Percentage: 17.3652%.
- Calculation: `21,735 / 125,164 * 100`.
- Counts were computed programmatically using normalized ingredient-name matching and distinct recipe IDs.

**Assessment result: PASS for the observed aggregate calculation.**

### Conversation 5 â€” Ingredient matching with hard constraints and follow-up

Initial prompt:

`I have eggs, onions, tomatoes, and rice. Suggest five recipes using as many of these as possible, with no peanuts and at most six instruction steps. Prefer recipes that need the fewest additional ingredients.`

Observed:
- Evaluated 122,971 recipes.
- 4,259 recipes were blocked by the peanut exclusion.
- 752 qualifying records were found: 748 unique recipes and four duplicate source records.
- The six-step maximum was applied.
- 611 recipes were excluded for exceeding the step limit.
- 65,041 recipes were excluded because their step count could not be reliably verified.
- Five recipes were displayed, with estimated step counts no greater than six.

Follow-up:

`Exclude eggs too.`

Observed:
- Evaluated 122,971 recipes.
- Active exclusions were peanuts and eggs.
- Required ingredients were reduced to onions, tomatoes, and rice.
- The six-step maximum remained active.
- 444 qualifying records were found: 441 unique recipes and three duplicate source records.
- 254 recipes were excluded for exceeding the step limit.
- 34,188 recipes were excluded because their step count could not be reliably verified.
- Five recipes were displayed, each with an estimated step count no greater than six.

**Assessment result: PASS for the observed multi-turn constraint retention and enforcement.**

Limitation: the step counts are estimates from numbered or bullet instruction formatting, not guaranteed structured step counts. Recipes with unverified counts were conservatively excluded.

### Conversation 6 â€” No-match case

Prompt: `Find recipes containing chicken, but exclude chicken.`

Observed:
- Evaluated 122,971 recipes.
- 18,517 recipes were blocked by the chicken exclusion.
- Zero recipes qualified.
- The system did not relax the conflicting ingredient requirements.

**Assessment result: PASS for the observed no-match behavior.**

## 9. Remaining evaluation work

The following items are still outstanding:

1. Conversation 4: run the tomato-recipe ranking prompt and record the actual five results, their recipe IDs, and the step-count method.
2. One-shot LLM comparison: run the exact-calorie prompt against a standalone LLM and record its actual response. Compare it with the grounded system's response. Do not invent or assume a baseline answer.

## 10. Additional execution note

During the latest ingredient-matching CLI evaluation, the Gemini service briefly returned an unavailable response. The application retried once and subsequently completed the recipe search. This is an observed service-availability limitation, not evidence that the recipe-matching evaluation failed.


## 11. Conversation 4 â€” Tomato recipes with the fewest instruction steps

**User request:** Among recipes containing tomato, which five have the fewest instruction steps?

**Result: PASS**

- Recipes evaluated: 122,971
- Tomato-matching records: 16,724
- Unique qualifying recipes: 16,553
- Duplicate source records: 171
- Results returned: 5
- Intent action: `match`
- Requested ingredient: `tomato`
- `prefer_fewer_steps`: `true`
- `max_steps`: `null`
- All five returned recipes had 2 numbered instruction steps.
- All five used the `numbered-step estimate` method.

The deterministic intent correction successfully prevented the request from being misclassified as analytics. The matcher prioritized the instruction-step ranking preference. Because all five returned recipes had the same estimated count, their relative order was determined by the remaining ranking criteria.

**Limitation:** Numbered-step estimates count explicitly numbered instruction blocks, not every individual cooking action. The result should therefore be described as an estimate.


## 12. One-shot LLM comparison â€” Unsupported calorie estimate

**Question:** How many calories are in exactly one serving of Chicken Enchilada Skillet?

**Standalone model:** Gemini (`gemini-3.5-flash-lite`)

**Setup:**
- No database access
- No retrieval
- No recipe lookup
- One direct generation request

**Standalone response:** 480 calories.

The model justified this estimate using assumed quantities of 2 tortillas, 3 oz chicken, 1 oz cheese, and 80 calories from cooking oil or fats.

**Grounding assessment: UNGROUNDED**

The source recipe lists 12 tortillas, 3 cups of cooked chicken, and 1 cup of cheese. It does not specify serving count, calories, or the assumed cooking-oil quantity. The model supplied unsupported portion assumptions and returned a precise calorie estimate.

**Conclusion:** The one-shot answer demonstrates how a standalone LLM can produce a confident numerical estimate without sufficient source evidence. The value of 480 calories is unsupported by this dataset; it is not claimed to be definitively incorrect.


## 13. Nutrition question — Retrieval and grounding verification

**Question:** How many calories are in one serving of Chicken Enchilada Skillet?

**Parser verification: PASS**
- Detected the question as a nutrition question.
- Extracted the recipe title: Chicken Enchilada Skillet.
- Routed the request to recipe details instead of dataset-wide analytics.

**Chatbot verification: PASS**
- Retrieved the original recipe from the local database.
- Returned the recipe ID and original ingredients and instructions.
- Explicitly stated that nutritional information, including calories, is unavailable.
- Did not generate or present an unsupported calorie estimate.

**Conclusion:** NoshAI correctly retrieves the requested recipe and communicates the dataset limitation rather than inventing nutritional information. This contrasts with the standalone one-shot LLM response documented in Section 12, which returned an unsupported estimate of 480 calories.
