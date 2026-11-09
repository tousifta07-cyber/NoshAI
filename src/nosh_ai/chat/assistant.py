import argparse
import json
import re
import sqlite3
import statistics
import sys

from pathlib import Path


# ==================================================
# 1. PROJECT CONFIGURATION AND IMPORTS
# ==================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]

SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from nosh_ai.retrieval import ingredient_matcher
from nosh_ai.tasks import substitution
from nosh_ai.chat.intent_parser import parse_intent


DB_PATH = PROJECT_ROOT / "data" / "processed" / "recipes.db"


# ==================================================
# 2. SUPPORTED USER ACTIONS
# ==================================================

SUPPORTED_ACTIONS = {
    "search",
    "details",
    "analytics",
    "match",
    "substitute",
    "help",
}


SEARCH_FIELDS = {
    "all",
    "title",
    "ingredients",
    "instructions",
}


# ==================================================
# 3. BASIC HELPERS
# ==================================================

def parse_ingredients(value):
    try:
        return json.loads(value or "[]")

    except (json.JSONDecodeError, TypeError):
        return []


def build_fts_query(query, search_in="all"):
    """
    Convert a user's search phrase into a safe FTS5 query.

    Every query word must occur in the selected search field.
    """

    if search_in not in SEARCH_FIELDS:
        raise ValueError(
            f"Search field must be one of: {sorted(SEARCH_FIELDS)}"
        )

    words = re.findall(
        r"[a-zA-Z0-9]+",
        str(query).casefold()
    )

    if not words:
        raise ValueError(
            "Enter a search query containing searchable words."
        )

    safe_words = [
        f'"{word}"'
        for word in words
    ]

    word_query = " AND ".join(safe_words)

    if search_in == "all":
        return word_query

    return f"{search_in} : ({word_query})"


def validate_limit(limit):
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError(
            "Limit must be between 1 and 100."
        )

    return limit


# ==================================================
# 4. CONVERSATIONAL ASSISTANT
# ==================================================

class NoshAssistant:
    """
    Python orchestration layer for Nosh AI.

    Gemini converts natural-language messages into structured intents.
    This class performs the actual operations using Python and SQLite.

    Recipe facts and calculations come from the local database
    and deterministic Python modules.
    """

    def __init__(self, db_path=None):

        self.db_path = Path(db_path or DB_PATH)

        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Recipe database not found: {self.db_path}"
            )

        # Make all imported project modules use the same database.
        ingredient_matcher.DB_PATH = self.db_path

        # Conversation memory.
        self.state = {
            "active_hard_exclusions": [],
            "active_required_ingredients": [],
            "active_max_steps": None,
            "last_results": [],
            "last_search_query": None,
            "last_search_in": "all",
            "selected_recipe_id": None,
            "last_action": None,
            "last_substitution": None,
        }

    # ==================================================
    # 5. DATABASE CONNECTION
    # ==================================================

    def get_connection(self):

        connection = sqlite3.connect(
            self.db_path,
            timeout=60
        )

        connection.row_factory = sqlite3.Row

        return connection

    # ==================================================
    # 6. RECIPE SEARCH - TASK 1
    # ==================================================

    def search_recipes(
        self,
        query,
        search_in="all",
        limit=5
    ):

        limit = validate_limit(limit)

        fts_query = build_fts_query(
            query,
            search_in
        )

        connection = self.get_connection()

        try:

            rows = connection.execute(
                """
                SELECT

                    r.recipe_id,

                    r.title_original,

                    r.source_file,

                    r.ingredients_original_json,

                    r.instructions_original,

                    bm25(
                        recipes_fts,
                        0.0,
                        10.0,
                        5.0,
                        1.0
                    ) AS relevance_score

                FROM recipes_fts

                JOIN recipes AS r

                    ON recipes_fts.recipe_id = r.recipe_id

                WHERE recipes_fts MATCH ?

                    AND r.has_title = 1

                ORDER BY

                    relevance_score ASC,

                    r.recipe_id ASC

                LIMIT ?

                """,

                (fts_query, limit)

            ).fetchall()

            results = []

            for row in rows:

                results.append({

                    "recipe_id": row["recipe_id"],

                    "title": row["title_original"],

                    "source_file": row["source_file"],

                    "ingredients": parse_ingredients(
                        row["ingredients_original_json"]
                    ),

                    "instructions": row["instructions_original"],

                    "relevance_score": row["relevance_score"],

                })

            return {

                "query": query,

                "search_in": search_in,

                "results": results,

                "returned_count": len(results),

                "limit": limit,

            }

        finally:

            connection.close()

    # ==================================================
    # 7. RECIPE DETAILS - TASK 1
    # ==================================================

    def get_recipe_details(self, recipe_id):

        if not recipe_id:
            raise ValueError(
                "A recipe ID is required."
            )

        connection = self.get_connection()

        try:

            row = connection.execute(
                """
                SELECT

                    recipe_id,

                    title_original,

                    source_file,

                    ingredients_original_json,

                    instructions_original,

                    has_title,

                    has_ingredients,

                    has_instructions

                FROM recipes

                WHERE recipe_id = ?

                """,

                (recipe_id,)

            ).fetchone()

            if row is None:
                return None

            return {

                "recipe_id": row["recipe_id"],

                "title": row["title_original"],

                "source_file": row["source_file"],

                "ingredients": parse_ingredients(
                    row["ingredients_original_json"]
                ),

                "instructions": row["instructions_original"],

                "has_title": bool(row["has_title"]),

                "has_ingredients": bool(row["has_ingredients"]),

                "has_instructions": bool(row["has_instructions"]),

            }

        finally:

            connection.close()

    # ==================================================
    # 8. RECIPE ANALYTICS - TASK 1
    # ==================================================


    def analyze_ingredient_pair(self, first, second, limit=10):
        """
        Count distinct recipes containing both requested ingredients.

        Ingredient presence is checked against searchable normalized
        ingredient lines. The percentage denominator is every recipe
        record, including records with incomplete ingredient data.
        """

        limit = validate_limit(limit)

        def make_pattern(term):
            term = str(term).strip().casefold()

            if not term or not re.fullmatch(r"[a-z][a-z -]*", term):
                raise ValueError("Unsupported ingredient term in pair query.")

            if term in {"onion", "onions"}:
                return re.compile(
                    r"\b(?:onions?|scallions?|spring\s+onions?)\b",
                    re.IGNORECASE
                )

            tokens = re.findall(r"[a-z]+", term)
            if not tokens:
                raise ValueError("Invalid ingredient term.")

            phrase = r"\s+".join(re.escape(token) for token in tokens)
            return re.compile(
                r"\b" + phrase + r"\b",
                re.IGNORECASE
            )

        first_pattern = make_pattern(first)
        second_pattern = make_pattern(second)

        first_ids = set()
        second_ids = set()

        connection = self.get_connection()

        try:
            dataset_recipe_count = connection.execute(
                "SELECT COUNT(*) FROM recipes"
            ).fetchone()[0]

            cursor = connection.execute(
                """
                SELECT recipe_id, ingredient_normalized
                FROM recipe_ingredients
                WHERE is_searchable = 1
                  AND ingredient_normalized IS NOT NULL
                  AND ingredient_normalized != ''
                """
            )

            while True:
                batch = cursor.fetchmany(10000)
                if not batch:
                    break

                for row in batch:
                    recipe_id = row["recipe_id"]
                    ingredient_text = row["ingredient_normalized"]

                    if first_pattern.search(ingredient_text):
                        first_ids.add(recipe_id)

                    if second_pattern.search(ingredient_text):
                        second_ids.add(recipe_id)

            both_ids = first_ids.intersection(second_ids)
            both_count = len(both_ids)

            percentage = (
                round(100.0 * both_count / dataset_recipe_count, 4)
                if dataset_recipe_count else None
            )

            sample_ids = sorted(both_ids)[:limit]
            sample = []

            if sample_ids:
                placeholders = ",".join("?" for _ in sample_ids)

                sample_rows = connection.execute(
                    f"""
                    SELECT recipe_id, title_original
                    FROM recipes
                    WHERE recipe_id IN ({placeholders})
                    """,
                    sample_ids
                ).fetchall()

                sample_by_id = {
                    row["recipe_id"]: row["title_original"]
                    for row in sample_rows
                }

                sample = [
                    {
                        "recipe_id": recipe_id,
                        "title": sample_by_id.get(recipe_id)
                    }
                    for recipe_id in sample_ids
                ]

            return {
                "analysis_type": "ingredient_cooccurrence",
                "query": f"recipes containing both {first} and {second}",
                "requested_ingredients": [first, second],
                "ingredient_recipe_counts": {
                    first: len(first_ids),
                    second: len(second_ids),
                },
                "recipes_containing_both": both_count,
                "total_recipes": both_count,
                "dataset_recipe_count": dataset_recipe_count,
                "percentage_of_dataset": percentage,
                "calculation": (
                    f"{both_count} / {dataset_recipe_count} * 100"
                ),
                "statistics_scope": (
                    "All recipe records; ingredient presence is checked "
                    "using searchable ingredient lines."
                ),
                "normalization_method": (
                    "Case-insensitive token-boundary matching on "
                    "ingredient_normalized. Onion includes onion/onions, "
                    "scallion/scallions and spring onion(s). Each recipe "
                    "is counted once per ingredient. This is lexical "
                    "normalization, not a complete culinary ontology."
                ),
                "sample_recipes": sample,
                "sample_limit": limit,
            }

        finally:
            connection.close()

    def analyze_recipes(
        self,
        query,
        search_in="all",
        limit=10
    ):

        """
        Calculate statistics over the complete FTS-filtered set.

        The displayed examples are limited, but the aggregate
        calculations use every qualifying FTS recipe.
        """

        limit = validate_limit(limit)

        pair_match = re.search(
            r"\bboth\s+(.+?)\s+and\s+(.+?)(?:[?.!,;]|$)",
            str(query or ""),
            flags=re.IGNORECASE
        )

        if pair_match:
            return self.analyze_ingredient_pair(
                pair_match.group(1).strip(),
                pair_match.group(2).strip(),
                limit=limit
            )

        fts_query = build_fts_query(
            query,
            search_in
        )

        connection = self.get_connection()

        try:

            # ------------------------------------------
            # Calculate recipe and ingredient statistics.
            # ------------------------------------------

            rows = connection.execute(
                """
                SELECT

                    r.recipe_id,

                    COUNT(
                        DISTINCT CASE
                            WHEN ri.is_searchable = 1
                            THEN ri.position
                        END
                    ) AS ingredient_count

                FROM recipes_fts

                JOIN recipes AS r

                    ON recipes_fts.recipe_id = r.recipe_id

                LEFT JOIN recipe_ingredients AS ri

                    ON r.recipe_id = ri.recipe_id

                WHERE recipes_fts MATCH ?

                    AND r.has_title = 1

                    AND r.has_ingredients = 1

                GROUP BY r.recipe_id

                """,

                (fts_query,)

            ).fetchall()

            counts = [
                row["ingredient_count"]
                for row in rows
            ]

            total_recipes = len(rows)

            if counts:

                average_count = statistics.mean(counts)

                median_count = statistics.median(counts)

            else:

                average_count = None

                median_count = None

            # ------------------------------------------
            # Find frequent normalized ingredient entries.
            # ------------------------------------------

            common_rows = connection.execute(
                """
                SELECT

                    ri.ingredient_normalized,

                    COUNT(DISTINCT r.recipe_id) AS recipe_frequency

                FROM recipes_fts

                JOIN recipes AS r

                    ON recipes_fts.recipe_id = r.recipe_id

                JOIN recipe_ingredients AS ri

                    ON r.recipe_id = ri.recipe_id

                WHERE recipes_fts MATCH ?

                    AND r.has_title = 1

                    AND r.has_ingredients = 1

                    AND ri.is_searchable = 1

                    AND ri.ingredient_normalized != ''

                GROUP BY ri.ingredient_normalized

                ORDER BY

                    recipe_frequency DESC,

                    ri.ingredient_normalized ASC

                LIMIT 10

                """,

                (fts_query,)

            ).fetchall()

            frequent_entries = [

                {

                    "ingredient_entry": row["ingredient_normalized"],

                    "recipe_frequency": row["recipe_frequency"],

                }

                for row in common_rows

            ]

            # ------------------------------------------
            # Return a small sample for inspection.
            # ------------------------------------------

            sample_rows = connection.execute(
                """
                SELECT

                    r.recipe_id,

                    r.title_original,

                    r.source_file

                FROM recipes_fts

                JOIN recipes AS r

                    ON recipes_fts.recipe_id = r.recipe_id

                WHERE recipes_fts MATCH ?

                    AND r.has_title = 1

                    AND r.has_ingredients = 1

                ORDER BY r.recipe_id

                LIMIT ?

                """,

                (fts_query, limit)

            ).fetchall()

            sample = [

                {

                    "recipe_id": row["recipe_id"],

                    "title": row["title_original"],

                    "source_file": row["source_file"],

                }

                for row in sample_rows

            ]

            return {

                "query": query,

                "search_in": search_in,

                "total_recipes": total_recipes,

                "average_ingredient_count": average_count,

                "median_ingredient_count": median_count,

                "frequent_ingredient_entries": frequent_entries,

                "sample_recipes": sample,

                "sample_limit": limit,

                "statistics_scope": (
                    "All recipes matching the FTS query "
                    "with available titles and ingredient data."
                ),

                "aggregation_note": (
                    "Frequent entries are normalized ingredient "
                    "lines, not a fully resolved culinary ontology."
                ),

            }

        finally:

            connection.close()

    # ==================================================
    # 9. RECIPE RESOLUTION
    # ==================================================

    def resolve_recipe_title(self, recipe_title):

        """
        Resolve an explicitly mentioned recipe title.

        Exact title matches are preferred. A partial title is accepted
        only when it identifies exactly one recipe.

        Ambiguous titles are never silently resolved.
        """

        if not recipe_title or not str(recipe_title).strip():
            return None

        title = str(recipe_title).strip()

        connection = self.get_connection()

        try:

            # First: exact case-insensitive title match.
            exact_rows = connection.execute(
                """
                SELECT
                    recipe_id,
                    title_original
                FROM recipes
                WHERE has_title = 1
                    AND LOWER(TRIM(title_original)) = LOWER(TRIM(?))
                LIMIT 3
                """,
                (title,)
            ).fetchall()

            if len(exact_rows) == 1:
                return exact_rows[0]["recipe_id"]

            if len(exact_rows) > 1:

                matches = [
                    row["title_original"]
                    for row in exact_rows
                ]

                raise ValueError(
                    "More than one recipe has that exact title. "
                    "Please provide a more specific title. Matches: "
                    + "; ".join(matches)
                )

            # Second: unique partial title match.
            escaped_title = (
                title
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )

            partial_rows = connection.execute(
                """
                SELECT
                    recipe_id,
                    title_original
                FROM recipes
                WHERE has_title = 1
                    AND LOWER(title_original) LIKE LOWER(?) ESCAPE '\\'
                ORDER BY title_original
                LIMIT 4
                """,
                (f"%{escaped_title}%",)
            ).fetchall()

            if len(partial_rows) == 1:
                return partial_rows[0]["recipe_id"]

            if len(partial_rows) > 1:

                matches = [
                    row["title_original"]
                    for row in partial_rows[:3]
                ]

                raise ValueError(
                    f"The title '{title}' matches multiple recipes. "
                    "Please provide a more specific recipe title. "
                    "Possible matches: "
                    + "; ".join(matches)
                )

            raise ValueError(
                f"I couldn't find a recipe with the title '{title}'. "
                "Search for the recipe first or provide its exact title."
            )

        finally:

            connection.close()

    def resolve_recipe_id(self, intent):

        """
        Resolve a recipe in this priority order:

        1. Explicit recipe title from the current message.
        2. Explicit recipe ID.
        3. Recipe number from the previous results.
        4. Previously selected recipe.

        This prevents a stale selection from overriding a recipe
        explicitly named by the user.
        """

        recipe_title = intent.get("recipe_title")

        if recipe_title:

            recipe_id = self.resolve_recipe_title(recipe_title)

            self.state["selected_recipe_id"] = recipe_id

            return recipe_id

        recipe_id = intent.get("recipe_id")

        if recipe_id:

            self.state["selected_recipe_id"] = recipe_id

            return recipe_id

        recipe_number = intent.get("recipe_number")

        if recipe_number is not None:

            try:

                number = int(recipe_number)

            except (ValueError, TypeError):

                raise ValueError(
                    "Recipe number must be an integer."
                )

            results = self.state["last_results"]

            if not 1 <= number <= len(results):

                raise ValueError(
                    "That recipe number is not available "
                    "in the previous search results."
                )

            recipe_id = results[number - 1]["recipe_id"]

            self.state["selected_recipe_id"] = recipe_id

            return recipe_id

        return self.state["selected_recipe_id"]

    # ==================================================
    # 10. SUBSTITUTION CONTEXT RESOLUTION
    # ==================================================

    @staticmethod
    def _get_ingredient_line_text(entry):

        """
        Extract the original ingredient text from a recipe entry.

        Supports both plain strings and dictionary-style entries.
        """

        if isinstance(entry, str):
            return entry.strip()

        if isinstance(entry, dict):

            for key in (
                "ingredient_original",
                "ingredient",
                "original",
                "text",
                "name",
                "line",
            ):

                value = entry.get(key)

                if isinstance(value, str) and value.strip():
                    return value.strip()

        return ""

    def find_substitution_ingredient_line(
        self,
        recipe,
        original_ingredient,
        selected_line=None
    ):

        """
        Find one exact ingredient line from the selected recipe.

        If the user supplied a line, validate it against the recipe.
        Otherwise, find matching lines locally.

        If multiple lines match, ask the user to choose one.
        """

        if not original_ingredient:
            raise ValueError(
                "Tell me which ingredient you want to replace."
            )

        original_spec = ingredient_matcher.parse_ingredient_spec(
            original_ingredient
        )

        if selected_line:

            exact_line = substitution.select_exact_ingredient_line(
                recipe,
                original_spec,
                selected_line
            )

            return exact_line

        entries = recipe.get("ingredient_entries") or []

        candidates = []

        for entry in entries:

            line = self._get_ingredient_line_text(entry)

            if not line:
                continue

            if substitution.source_line_matches(
                original_spec,
                line
            ):

                if line not in candidates:
                    candidates.append(line)

        if not candidates:

            raise ValueError(
                f"I couldn't find an ingredient line for "
                f"'{original_ingredient}' in this recipe. "
                "Please check the ingredient name or choose another recipe."
            )

        if len(candidates) > 1:

            choices = "\n".join(
                f"- {line}"
                for line in candidates[:10]
            )

            raise ValueError(
                f"I found multiple ingredient lines matching "
                f"'{original_ingredient}' in this recipe:\n"
                f"{choices}\n"
                "Which exact ingredient line should I replace?"
            )

        return candidates[0]

    def find_substitution_instruction_context(
        self,
        recipe,
        original_ingredient,
        replacement_ingredient,
        instruction_context=None
    ):

        """
        Find one exact instruction sentence containing the ingredient.

        The recipe instructions are read from the local recipe record.
        If more than one sentence matches, ask the user to choose.
        """

        instructions = (
            recipe.get("instructions")
            or recipe.get("instructions_original")
            or ""
        )

        if not isinstance(instructions, str) or not instructions.strip():

            raise ValueError(
                "This recipe does not contain usable instructions. "
                "I cannot safely identify where the ingredient is used."
            )

        original_spec = ingredient_matcher.parse_ingredient_spec(
            original_ingredient
        )

        original_name = (
            original_spec.get("name")
            if isinstance(original_spec, dict)
            else None
        )

        if not original_name:
            original_name = str(original_ingredient).strip()

        # If the user or intent parser supplied an exact context,
        # validate it against the original recipe instructions.
        if instruction_context:

            substitution.revise_instruction_context(
                instructions,
                instruction_context,
                original_name,
                replacement_ingredient
            )

            return instruction_context.strip()

        # Split instructions into sentence-like units.
        # Newlines are also treated as boundaries.
        parts = re.findall(
            r"[^.!?\n]+(?:[.!?]+|(?=\n)|$)",
            instructions
        )

        candidates = []

        ingredient_pattern = re.compile(
            rf"\b{re.escape(original_name)}\b",
            flags=re.IGNORECASE
        )

        # Avoid treating compound ingredients such as peanut butter
        # or lobster butter as ordinary butter instructions.
        compound_pattern = re.compile(
            r"\b(?:peanut|almond|cashew|coconut|lobster|"
            r"garlic|herb|cookie|apple)\s+"
            + re.escape(original_name)
            + r"\b|\b"
            + re.escape(original_name)
            + r"\s+flavou?r\b",
            flags=re.IGNORECASE
        )

        for part in parts:

            sentence = part.strip()

            if not sentence:
                continue

            if not ingredient_pattern.search(sentence):
                continue

            if compound_pattern.search(sentence):
                continue

            if sentence not in candidates:
                candidates.append(sentence)

        if not candidates:

            raise ValueError(
                f"I couldn't identify an instruction sentence that "
                f"uses '{original_ingredient}'. "
                "Please provide the exact instruction phrase where "
                "the ingredient is used."
            )

        if len(candidates) > 1:

            choices = "\n".join(
                f"- {sentence}"
                for sentence in candidates[:10]
            )

            raise ValueError(
                f"I found multiple instruction sentences mentioning "
                f"'{original_ingredient}':\n"
                f"{choices}\n"
                "Which exact instruction sentence should I update?"
            )

        selected_context = candidates[0]

        # Validate the locally selected sentence using the existing
        # substitution module before passing it to the planner.
        substitution.revise_instruction_context(
            instructions,
            selected_context,
            original_name,
            replacement_ingredient
        )

        return selected_context

    # ==================================================
    # 11. INGREDIENT MATCHING - TASK 2
    # ==================================================

    def match_ingredients(self, intent):

        previous_action = self.state["last_action"]

        previous_required = list(
            self.state["active_required_ingredients"]
        )

        # ------------------------------------------
        # Update active exclusions first.
        # ------------------------------------------

        if intent.get("clear_hard_exclusions"):

            self.state["active_hard_exclusions"] = []

        elif intent.get("hard_exclusions"):

            self.state["active_hard_exclusions"] = list(
                intent["hard_exclusions"]
            )

        additions = intent.get("add_hard_exclusions", [])

        for exclusion in additions:

            if exclusion not in self.state["active_hard_exclusions"]:

                self.state["active_hard_exclusions"].append(exclusion)

        removals = intent.get("remove_hard_exclusions", [])

        self.state["active_hard_exclusions"] = [
            item
            for item in self.state["active_hard_exclusions"]
            if item not in removals
        ]

        if intent.get("max_steps") is not None:
            self.state["active_max_steps"] = intent["max_steps"]

        incoming_ingredients = intent.get("ingredients") or []

        def ingredient_keys(values):
            keys = set()
            for value in values:
                spec = ingredient_matcher.parse_ingredient_spec(value)
                if spec:
                    keys.add(spec["name"])
                else:
                    keys.add(str(value).strip().casefold())
            return keys

        previous_keys = ingredient_keys(previous_required)
        incoming_keys = ingredient_keys(incoming_ingredients)

        same_matching_followup = (
            previous_action == "match"
            and bool(previous_required)
            and (
                not incoming_ingredients
                or incoming_keys.issubset(previous_keys)
            )
        )

        if incoming_ingredients and not same_matching_followup:
            self.state["active_required_ingredients"] = list(
                incoming_ingredients
            )

        ingredients = list(
            incoming_ingredients
            or self.state["active_required_ingredients"]
        )

        # A newly added exclusion removes that ingredient from the
        # effective required list for an existing matching conversation.
        # The original requirements remain stored so they can be restored
        # if the exclusion is later removed.
        if same_matching_followup and self.state["active_hard_exclusions"]:
            exclusion_specs = [
                ingredient_matcher.parse_ingredient_spec(item)
                for item in self.state["active_hard_exclusions"]
            ]

            excluded_token_sets = [
                set(spec["name"].split())
                for spec in exclusion_specs
                if spec and spec.get("name")
            ]

            effective_ingredients = []

            for ingredient in ingredients:
                spec = ingredient_matcher.parse_ingredient_spec(ingredient)
                requested_tokens = (
                    set(spec["name"].split())
                    if spec and spec.get("name")
                    else {str(ingredient).strip().casefold()}
                )

                conflicts_with_exclusion = any(
                    tokens and tokens.issubset(requested_tokens)
                    for tokens in excluded_token_sets
                )

                if not conflicts_with_exclusion:
                    effective_ingredients.append(ingredient)

            ingredients = effective_ingredients

        # ------------------------------------------
        # Exclusion-only follow-up to a recipe search.
        # ------------------------------------------

        if (
            not ingredients
            and self.state["last_action"] in ("search", "match")
            and self.state["last_search_query"]
            and self.state["last_results"]
            and self.state["active_hard_exclusions"]
        ):

            exclusion_specs = [
                ingredient_matcher.parse_ingredient_spec(item)
                for item in self.state["active_hard_exclusions"]
            ]

            exclusion_specs = [
                item for item in exclusion_specs if item is not None
            ]

            filtered_results = []

            for recipe in self.state["last_results"]:

                ingredient_lines = recipe.get("ingredients", [])

                blocked = any(
                    ingredient_matcher.hard_exclusion_matches(
                        exclusion,
                        line
                    )
                    for exclusion in exclusion_specs
                    for line in ingredient_lines
                )

                if not blocked:
                    filtered_results.append(recipe)

            output = {
                "query": self.state["last_search_query"],
                "search_in": self.state["last_search_in"],
                "results": filtered_results,
                "returned_count": len(filtered_results),
                "limit": len(self.state["last_results"]),
                "recipes_evaluated": len(self.state["last_results"]),
                "recipes_qualifying": len(filtered_results),
                "hard_exclusions": list(
                    self.state["active_hard_exclusions"]
                ),
                "filter_scope": "previous_search_results",
            }

            self.state["last_results"] = filtered_results
            self.state["last_action"] = "match"

            if filtered_results:
                self.state["selected_recipe_id"] = (
                    filtered_results[0]["recipe_id"]
                )

            return output

        if not ingredients:

            raise ValueError(
                "Tell me which ingredients the recipes should contain."
            )

        output = ingredient_matcher.match_recipes(

            ingredients=ingredients,

            hard_exclusions=self.state["active_hard_exclusions"],

            max_missing=intent.get("max_missing"),

            limit=intent.get("limit") or 5,

            prefer_fewer_steps=intent.get(
                "prefer_fewer_steps",
                False
            ),

            max_steps=self.state["active_max_steps"],

        )

        self.state["last_results"] = output["results"]

        self.state["last_action"] = "match"

        if output["results"]:

            self.state["selected_recipe_id"] = (
                output["results"][0]["recipe_id"]
            )

        return output

    # ==================================================
    # 12. SUBSTITUTION - TASK 3
    # ==================================================

    def evaluate_substitution(self, intent):

        """
        Resolve the recipe and substitution context locally.

        Gemini only needs to identify the user's requested ingredient
        and replacement. SQLite supplies the original recipe data.
        """

        recipe_id = self.resolve_recipe_id(intent)

        if not recipe_id:

            raise ValueError(
                "Select a recipe first, provide a recipe title, "
                "or provide a recipe ID."
            )

        original_ingredient = intent.get(
            "original_ingredient"
        )

        replacement_ingredient = intent.get(
            "replacement_ingredient"
        )

        if not original_ingredient:

            raise ValueError(
                "Tell me which ingredient you want to replace."
            )

        if not replacement_ingredient:

            raise ValueError(
                "Tell me which ingredient you want to use instead."
            )

        # Retrieve the complete source recipe locally.
        recipe = substitution.get_source_recipe(recipe_id)

        if recipe is None:

            raise ValueError(
                "The selected recipe could not be retrieved "
                "from the local recipe database."
            )

        # Resolve the exact ingredient line from the recipe.
        selected_ingredient_line = (
            self.find_substitution_ingredient_line(
                recipe=recipe,
                original_ingredient=original_ingredient,
                selected_line=intent.get(
                    "selected_ingredient_line"
                ),
            )
        )

        # Resolve the exact instruction sentence from the recipe.
        instruction_context = (
            self.find_substitution_instruction_context(
                recipe=recipe,
                original_ingredient=original_ingredient,
                replacement_ingredient=replacement_ingredient,
                instruction_context=intent.get(
                    "instruction_context"
                ),
            )
        )

        # Pass the validated, locally retrieved context to the
        # existing deterministic substitution planner.
        result = substitution.build_substitution_plan(

            recipe_id=recipe_id,

            original_ingredient=original_ingredient,

            replacement_ingredient=replacement_ingredient,

            selected_ingredient_line=selected_ingredient_line,

            instruction_context=instruction_context,

            evidence_limit=intent.get("limit") or 5,

        )

        self.state["last_substitution"] = result

        self.state["last_action"] = "substitute"

        return result

    # ==================================================
    # 13. HELP MESSAGE
    # ==================================================

    def help_message(self):

        return (
            "I can help you search recipes, inspect recipe details, "
            "calculate recipe statistics, match ingredients, and "
            "evaluate ingredient substitutions. "
            "You can also add or remove hard ingredient exclusions "
            "during a matching conversation."
        )

    # ==================================================
    # 14. CONVERSATION STATE FOR GEMINI
    # ==================================================

    def get_context_for_llm(self):

        """
        Provide compact conversation context to Gemini.

        Do not send the entire database or entire recipe lists.
        """

        recent_results = []

        for index, recipe in enumerate(
            self.state["last_results"][:5],
            start=1
        ):

            recent_results.append({

                "number": index,

                "recipe_id": recipe["recipe_id"],

                "title": recipe.get(
                    "title",
                    ""
                ),

            })

        return {

            "active_hard_exclusions": (
                self.state["active_hard_exclusions"]
            ),

            "active_required_ingredients": (
                self.state["active_required_ingredients"]
            ),

            "active_max_steps": self.state["active_max_steps"],

            "last_action": self.state["last_action"],

            "last_search_query": self.state["last_search_query"],

            "last_search_in": self.state["last_search_in"],

            "selected_recipe_id": (
                self.state["selected_recipe_id"]
            ),

            "recent_results": recent_results,

        }

    # ==================================================
    # 15. NATURAL-LANGUAGE MESSAGE PROCESSING
    # ==================================================

    def process_message(self, user_message):

        """
        Parse one natural-language message with Gemini, then execute
        the structured intent using the existing Python logic.

        One successful user message normally requires one Gemini API call.
        Recipe retrieval, matching and calculations do not call Gemini.
        """

        if not user_message or not user_message.strip():

            return {
                "ok": False,
                "message": "Please enter a message.",
                "data": None,
                "conversation_context": self.get_context_for_llm(),
            }

        try:

            context = self.get_context_for_llm()

            intent = parse_intent(
                user_message=user_message,
                conversation_context=context,
            )

            result = self.handle_intent(intent)
            result["intent"] = intent

            return result

        except Exception as error:

            return {
                "ok": False,
                "message": (
                    "I couldn't understand or process that request. "
                    f"Technical detail: {type(error).__name__}: {error}"
                ),
                "data": None,
                "conversation_context": self.get_context_for_llm(),
            }

    # ==================================================
    # 16. RESET CONVERSATION
    # ==================================================

    def reset_conversation(self):

        self.state = {

            "active_hard_exclusions": [],

            "active_required_ingredients": [],

            "active_max_steps": None,

            "last_results": [],

            "selected_recipe_id": None,

            "last_action": None,

            "last_substitution": None,

        }

    # ==================================================
    # 17. MAIN INTENT DISPATCHER
    # ==================================================

    def handle_intent(self, intent):

        """
        Execute a validated structured intent.

        This method will be called by the Gemini intent parser.
        """

        if not isinstance(intent, dict):

            return {

                "ok": False,

                "message": "The assistant received an invalid intent.",

                "data": None,

            }

        action = str(
            intent.get("action", "")
        ).strip().casefold()

        if action not in SUPPORTED_ACTIONS:

            return {

                "ok": False,

                "message": (
                    "I could not identify the requested operation. "
                    + self.help_message()
                ),

                "data": None,

            }

        try:

            # --------------------------------------
            # Recipe search.
            # --------------------------------------

            if action == "search":

                output = self.search_recipes(

                    query=intent.get("query", ""),

                    search_in=intent.get("search_in") or "all",

                    limit=intent.get("limit") or 5,

                )

                self.state["last_results"] = output["results"]
                self.state["last_search_query"] = output["query"]
                self.state["last_search_in"] = output["search_in"]

                self.state["last_action"] = "search"

                if output["results"]:

                    self.state["selected_recipe_id"] = (
                        output["results"][0]["recipe_id"]
                    )

                message = (
                    f"I found {output['returned_count']} recipe "
                    f"result(s) for '{output['query']}'."
                )

            # --------------------------------------
            # Recipe details.
            # --------------------------------------

            elif action == "details":

                recipe_id = self.resolve_recipe_id(intent)

                if not recipe_id:

                    raise ValueError(
                        "Provide a recipe ID or select a recipe "
                        "from the previous results."
                    )

                output = self.get_recipe_details(
                    recipe_id
                )

                if output is None:

                    message = (
                        "No recipe was found with that recipe ID."
                    )

                else:

                    self.state["selected_recipe_id"] = recipe_id

                    self.state["last_action"] = "details"

                    if intent.get("nutrition_question"):
                        message = (
                            f"Retrieved the original recipe: "
                            f"{output['title']}. "
                            "Nutritional information, including calories, "
                            "is not available in this recipe dataset. "
                            "I cannot provide a reliable nutritional estimate "
                            "from the available ingredients and instructions."
                        )
                    else:
                        message = (
                            f"Retrieved the original recipe: "
                            f"{output['title']}."
                        )

            # --------------------------------------
            # Recipe analytics.
            # --------------------------------------

            elif action == "analytics":

                output = self.analyze_recipes(

                    query=intent.get("query", ""),

                    search_in=intent.get("search_in") or "all",

                    limit=intent.get("limit") or 10,

                )

                self.state["last_action"] = "analytics"

                if output.get("analysis_type") == "ingredient_cooccurrence":
                    message = (
                        f"{output['recipes_containing_both']:,} recipes "
                        f"contain both {output['requested_ingredients'][0]} "
                        f"and {output['requested_ingredients'][1]}. "
                        f"That is {output['percentage_of_dataset']}% "
                        f"of {output['dataset_recipe_count']:,} recipes."
                    )
                else:
                    message = (
                        f"The complete filtered set contains "
                        f"{output['total_recipes']:,} recipes."
                    )

            # --------------------------------------
            # Ingredient matching.
            # --------------------------------------

            elif action == "match":

                output = self.match_ingredients(intent)

                message = (

                    f"Evaluated {output['recipes_evaluated']:,} "
                    f"recipes. Found {output['recipes_qualifying']:,} "
                    "recipes passing the active filters. "

                    f"Hard exclusions: "
                    f"{output['hard_exclusions']}."

                )

            # --------------------------------------
            # Ingredient substitution.
            # --------------------------------------

            elif action == "substitute":

                output = self.evaluate_substitution(intent)

                message = (
                    f"Substitution decision: {output['status']}."
                )

            else:

                output = None

                message = self.help_message()

            return {

                "ok": True,

                "action": action,

                "message": message,

                "data": output,

                "conversation_context": self.get_context_for_llm(),

            }

        except (
            ValueError,
            FileNotFoundError,
            sqlite3.Error,
            TypeError,
            KeyError
        ) as error:

            return {

                "ok": False,

                "action": action,

                "message": str(error),

                "data": None,

                "conversation_context": self.get_context_for_llm(),

            }


# ==================================================
# 18. COMMAND-LINE CHAT INTERFACE
# ==================================================

def print_result(result, show_intent=False):

    print("\nNOSH AI")
    print("=" * 60)
    print(result.get("message", "No response."))

    if show_intent and result.get("intent"):

        print("\nPARSED INTENT")

        print(json.dumps(
            result["intent"],
            indent=2,
            ensure_ascii=False,
            default=str
        ))

    if result.get("data") is not None:

        print("\nRESULT DATA")

        print(json.dumps(
            result["data"],
            indent=2,
            ensure_ascii=False,
            default=str
        ))


def main():

    parser = argparse.ArgumentParser(
        description="Nosh AI conversational recipe assistant."
    )

    parser.add_argument(
        "--intent-json",
        help="Run a manually supplied structured intent (testing only)."
    )

    parser.add_argument(
        "--message",
        help="Process one natural-language message and exit."
    )

    parser.add_argument(
        "--show-intent",
        action="store_true",
        help="Also display the structured intent returned by Gemini."
    )

    args = parser.parse_args()

    try:

        assistant = NoshAssistant()

        # Backward-compatible manual JSON testing.
        if args.intent_json:

            intent = json.loads(args.intent_json)

            result = assistant.handle_intent(intent)

            print_result(result)

            return

        # Process one natural-language request.
        if args.message:

            result = assistant.process_message(args.message)

            print_result(
                result,
                show_intent=args.show_intent
            )

            return

        # Interactive chat: this single assistant instance preserves
        # conversation state until the user exits or resets the chat.
        print("=" * 60)
        print("NOSH AI - CONVERSATIONAL RECIPE ASSISTANT")
        print("=" * 60)
        print("Ask me to search recipes, match ingredients,")
        print("inspect details, calculate statistics, or evaluate substitutions.")
        print("Commands: 'reset' clears conversation memory; 'exit' quits.")
        print("")

        while True:

            try:

                user_message = input("You: ").strip()

            except (EOFError, KeyboardInterrupt):

                print("\nNosh AI: Goodbye!")

                break

            if not user_message:
                continue

            command = user_message.casefold()

            if command in {"exit", "quit", "bye"}:

                print("Nosh AI: Goodbye!")

                break

            if command == "reset":

                assistant.reset_conversation()

                print(
                    "Nosh AI: Conversation memory has been reset.\n"
                )

                continue

            result = assistant.process_message(user_message)

            print_result(result)

            print()

    except (
        ValueError,
        FileNotFoundError,
        sqlite3.Error,
        json.JSONDecodeError
    ) as error:

        parser.error(str(error))


if __name__ == "__main__":

    main()