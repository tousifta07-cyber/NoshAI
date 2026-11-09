
import argparse
import hashlib
import json
import re
import sqlite3
import sys

from pathlib import Path


# ==================================================
# 1. PROJECT CONFIGURATION
# ==================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "recipes.db"
)


# ==================================================
# 2. INGREDIENT NORMALIZATION RULES
# ==================================================

# Only well-established equivalents are mapped.
# Green onion is NOT treated as ordinary bulb onion.
# Garlic powder is NOT treated as fresh garlic.

INGREDIENT_ALIASES = {
    "garbanzo beans": "chickpea",
    "garbanzo bean": "chickpea",
    "chickpeas": "chickpea",
    "aubergines": "eggplant",
    "aubergine": "eggplant",
    "courgettes": "zucchini",
    "courgette": "zucchini",
    "capsicum": "bell pepper",
    "scallions": "green onion",
    "scallion": "green onion",
    "spring onions": "green onion",
    "spring onion": "green onion",
    "groundnuts": "peanut",
    "groundnut": "peanut",
}


FORM_EXCLUSIONS = {

    "garlic": [
        r"\bgarlic\s+(?:powder|salt|seasoning|sauce|butter|oil|paste|spread|blend|mix|pepper)\b",
        r"\bpowdered\s+garlic\b",
        r"\bgranulated\s+garlic\b",
        r"\b(?:dried|dehydrated)\s+garlic\b",
        r"\bgarlic\s+flakes?\b",
        r"\b(?:chile|chili)[-\s]+garlic\s+sauce\b",
        r"\b(?:[a-z-]+\s+){0,3}garlic(?:\s+[a-z-]+){0,2}\s+seasoning\b",
        r"\bonion\s+and\s+garlic\s+spaghetti\s+sauce\b",
        r"\b[a-z-]*garlic[-\s]+marinade\b",
    ],

    "onion": [
        r"\bonion\s+(?:powder|salt|soup\s+mix|flakes?|seasoning|dip|mix)\b",
        r"\bpowdered\s+onions?\b",
        r"\b(?:dry|dried|dehydrated)\s+(?:minced\s+)?onions?\b",
        r"\b(?:green|spring)\s+onions?\b",
        r"\bscallions?\b",
        r"\bshallots?\b",
        r"\bonion\s+and\s+garlic\s+spaghetti\s+sauce\b",
    ],

    "tomato": [
        r"\btomato\s+(?:sauce|paste|puree|purée|powder|juice)\b",
    ],

    "chicken": [
        r"\bchicken\s+(?:broth|stock|bouillon|powder|seasoning|flavou?r)\b",
    ],

    "beef": [
        r"\bbeef\s+(?:broth|stock|bouillon|powder|flavou?r)\b",
    ],

}



ADVERTISEMENT_PATTERN = re.compile(
    r"\bADVERTISEMENT\b",
    re.IGNORECASE
)


def clean_display_ingredient(text):
    """
    Clean advertisement markers from ingredient text
    shown to the user.

    Original database values remain unchanged.
    """

    if not isinstance(text, str):
        return ""

    text = ADVERTISEMENT_PATTERN.sub(" ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


PARENTHETICAL_PATTERN = re.compile(
    r"\([^)]*\)"
)

QUANTITY_PATTERN = re.compile(
    r"^\s*(?P<amount>\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?|[¼½¾⅓⅔⅛⅜⅝⅞])\s*(?P<rest>.*)$"
)


FRACTIONS = {
    "¼": 0.25,
    "½": 0.5,
    "¾": 0.75,
    "⅓": 1 / 3,
    "⅔": 2 / 3,
    "⅛": 0.125,
    "⅜": 0.375,
    "⅝": 0.625,
    "⅞": 0.875,
}


# Units map to:
# (dimension, conversion factor, canonical unit)

UNIT_ALIASES = {

    "tsp": ("volume", 4.92892, "ml"),
    "teaspoon": ("volume", 4.92892, "ml"),
    "teaspoons": ("volume", 4.92892, "ml"),

    "tbsp": ("volume", 14.7868, "ml"),
    "tablespoon": ("volume", 14.7868, "ml"),
    "tablespoons": ("volume", 14.7868, "ml"),

    "cup": ("volume", 236.588, "ml"),
    "cups": ("volume", 236.588, "ml"),

    "ml": ("volume", 1.0, "ml"),
    "milliliter": ("volume", 1.0, "ml"),
    "milliliters": ("volume", 1.0, "ml"),
    "millilitre": ("volume", 1.0, "ml"),
    "millilitres": ("volume", 1.0, "ml"),

    "l": ("volume", 1000.0, "ml"),
    "liter": ("volume", 1000.0, "ml"),
    "liters": ("volume", 1000.0, "ml"),
    "litre": ("volume", 1000.0, "ml"),
    "litres": ("volume", 1000.0, "ml"),

    "g": ("weight", 1.0, "g"),
    "gram": ("weight", 1.0, "g"),
    "grams": ("weight", 1.0, "g"),

    "kg": ("weight", 1000.0, "g"),
    "kilogram": ("weight", 1000.0, "g"),
    "kilograms": ("weight", 1000.0, "g"),

    "oz": ("weight", 28.3495, "g"),
    "ounce": ("weight", 28.3495, "g"),
    "ounces": ("weight", 28.3495, "g"),

    "lb": ("weight", 453.592, "g"),
    "lbs": ("weight", 453.592, "g"),
    "pound": ("weight", 453.592, "g"),
    "pounds": ("weight", 453.592, "g"),

    "clove": ("count:clove", 1.0, "clove"),
    "cloves": ("count:clove", 1.0, "clove"),

    "piece": ("count:piece", 1.0, "piece"),
    "pieces": ("count:piece", 1.0, "piece"),

    "can": ("count:can", 1.0, "can"),
    "cans": ("count:can", 1.0, "can"),

    "bunch": ("count:bunch", 1.0, "bunch"),
    "bunches": ("count:bunch", 1.0, "bunch"),

    "sprig": ("count:sprig", 1.0, "sprig"),
    "sprigs": ("count:sprig", 1.0, "sprig"),

    "slice": ("count:slice", 1.0, "slice"),
    "slices": ("count:slice", 1.0, "slice"),

    "head": ("count:head", 1.0, "head"),
    "heads": ("count:head", 1.0, "head"),

    "stalk": ("count:stalk", 1.0, "stalk"),
    "stalks": ("count:stalk", 1.0, "stalk"),

    "stick": ("count:stick", 1.0, "stick"),
    "sticks": ("count:stick", 1.0, "stick"),

    "jar": ("count:jar", 1.0, "jar"),
    "jars": ("count:jar", 1.0, "jar"),

    "bottle": ("count:bottle", 1.0, "bottle"),
    "bottles": ("count:bottle", 1.0, "bottle"),

    "package": ("count:package", 1.0, "package"),
    "packages": ("count:package", 1.0, "package"),

    "packet": ("count:packet", 1.0, "packet"),
    "packets": ("count:packet", 1.0, "packet"),

}


PREPARATION_WORDS = {
    "a", "an", "of", "and", "or", "to", "taste", "as", "needed",
    "optional", "divided", "plus", "for", "garnish", "serving",
    "chopped", "minced", "diced", "sliced", "finely", "coarsely",
    "grated", "shredded", "crushed", "peeled", "deveined", "boneless",
    "skinless", "halved", "quartered", "melted", "softened", "drained",
    "rinsed", "freshly", "fresh", "whole", "large", "medium", "small",
    "thinly", "roughly", "roasted", "cooked", "uncooked", "raw",
    "packed", "heaping", "level", "about", "approximately", "fluid",
}


UNIT_WORDS = set(UNIT_ALIASES)


# ==================================================
# 3. DATABASE CONNECTION
# ==================================================

def get_connection():

    if not DB_PATH.exists():

        raise FileNotFoundError(
            f"Database not found: {DB_PATH}"
        )

    connection = sqlite3.connect(
        DB_PATH,
        timeout=60
    )

    connection.row_factory = sqlite3.Row

    return connection


# ==================================================
# 4. BASIC TEXT AND NUMBER HELPERS
# ==================================================

def parse_number(value):

    """Convert decimals, fractions, mixed fractions and unicode fractions."""

    value = value.strip()

    if value in FRACTIONS:
        return FRACTIONS[value]

    if " " in value:

        whole, fraction = value.split(maxsplit=1)

        numerator, denominator = fraction.split("/", 1)

        return float(whole) + (
            float(numerator) / float(denominator)
        )

    if "/" in value:

        numerator, denominator = value.split("/", 1)

        return float(numerator) / float(denominator)

    return float(value)


def clean_matching_text(text):

    text = str(text).casefold()

    text = ADVERTISEMENT_PATTERN.sub(" ", text)

    text = PARENTHETICAL_PATTERN.sub(" ", text)

    text = text.replace("–", " ").replace("—", " ")

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def singularize_token(token):

    """Small plural normalizer, not a full English stemmer."""

    if len(token) <= 3 or token.endswith("ss"):
        return token

    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"

    if token.endswith(("ches", "shes", "xes", "zes")):
        return token[:-2]

    if token.endswith("oes") and len(token) > 4:
        return token[:-2]

    if token.endswith("s"):
        return token[:-1]

    return token


def apply_aliases(text):

    for alias in sorted(
        INGREDIENT_ALIASES,
        key=len,
        reverse=True
    ):

        canonical = INGREDIENT_ALIASES[alias]

        text = re.sub(
            rf"\b{re.escape(alias)}\b",
            canonical,
            text
        )

    return text


# ==================================================
# 5. PARSE INGREDIENTS AND QUANTITIES
# ==================================================

def parse_ingredient_spec(text):

    """
    Parse an ingredient phrase and an optional quantity/unit.

    Examples:
      2 cloves garlic
      1 1/2 cups chopped onion
      2 garlic cloves
      500 g chicken
      2 large cloves garlic
    """

    if not isinstance(text, str):
        return None

    cleaned = clean_matching_text(text)

    amount = None
    unit = None
    name_text = cleaned

    match = QUANTITY_PATTERN.match(cleaned)

    if match:

        try:

            amount = parse_number(
                match.group("amount")
            )

        except (ValueError, ZeroDivisionError):

            amount = None

        name_text = match.group("rest").strip()

        # Recognize two-word fluid-volume units.
        multi_unit = re.match(
            r"^(?:fluid\s+ounces?|fl\s+oz)\b\s*",
            name_text
        )

        if multi_unit:

            unit = ("volume", 29.5735, "ml")

            name_text = name_text[
                multi_unit.end():
            ].strip()

        else:

            word_matches = list(
                re.finditer(
                    r"[a-zA-Z]+",
                    name_text
                )
            )

            significant_words = [
                word
                for word in word_matches
                if word.group(0).casefold()
                not in PREPARATION_WORDS
            ]

            # Units may appear before the ingredient:
            # "2 large cloves garlic"
            if significant_words:

                first_word = significant_words[0]

                possible_unit = first_word.group(0).casefold()

                if possible_unit in UNIT_ALIASES:

                    unit = UNIT_ALIASES[possible_unit]

                    name_text = name_text[
                        first_word.end():
                    ].strip()

                else:

                    # Units may also appear after the ingredient:
                    # "2 garlic cloves"
                    last_word = significant_words[-1]

                    trailing_unit = last_word.group(0).casefold()

                    if trailing_unit in UNIT_ALIASES:

                        unit = UNIT_ALIASES[trailing_unit]

                        name_text = (
                            name_text[:last_word.start()]
                            + " "
                            + name_text[last_word.end():]
                        ).strip()

                    else:

                        # For example: "2 onions"
                        unit = ("count:item", 1.0, "item")

            else:

                unit = ("count:item", 1.0, "item")

    # Remove simple package/measure descriptions.
    name_text = re.sub(
        r"\b(?:pinch|dash|handful)\s+of\b",
        " ",
        name_text
    )

    name_text = apply_aliases(name_text)

    tokens = re.findall(
        r"[a-z0-9]+",
        name_text
    )

    cleaned_tokens = []

    for token in tokens:

        if token in PREPARATION_WORDS or token in UNIT_WORDS:
            continue

        cleaned_tokens.append(
            singularize_token(token)
        )

    normalized_name = " ".join(cleaned_tokens)

    if not normalized_name:
        return None

    return {
        "original": text,
        "name": normalized_name,
        "amount": amount,
        "unit": unit,
    }


# ==================================================
# 6. INGREDIENT NAME MATCHING
# ==================================================

def ingredient_name_matches(
    requested_spec,
    recipe_line
):

    """Match ingredient names without silently equating different forms."""

    if not recipe_line or not requested_spec:
        return False

    # Keep the original line for form exclusions.
    form_check_text = str(recipe_line).casefold()

    form_check_text = ADVERTISEMENT_PATTERN.sub(
        " ",
        form_check_text
    )

    form_check_text = (
        form_check_text
        .replace("(", " ")
        .replace(")", " ")
    )

    requested_name = requested_spec["name"]

    # Reject distinct forms of a generic ingredient.
    for pattern in FORM_EXCLUSIONS.get(
        requested_name,
        []
    ):

        if re.search(pattern, form_check_text):
            return False

    recipe_spec = parse_ingredient_spec(
        recipe_line
    )

    if recipe_spec is None:
        return False

    requested_tokens = set(
        requested_name.split()
    )

    recipe_tokens = set(
        recipe_spec["name"].split()
    )

    return (
        bool(requested_tokens)
        and requested_tokens.issubset(recipe_tokens)
    )



def _matches_dairy_category(recipe_line):
    """
    Match common dairy ingredients while excluding obvious
    plant-based milk, butter, and cream alternatives.

    This is a text-based category filter, not an allergy guarantee.
    """

    text = str(recipe_line).casefold()

    text = ADVERTISEMENT_PATTERN.sub(" ", text)

    # Remove common plant-based milk alternatives.
    text = re.sub(
        r"\b(?:almond|oat|soy|soya|coconut|rice|cashew|hemp|"
        r"pea|hazelnut|macadamia|flax|potato)\s+milk\b",
        " ",
        text
    )

    # Remove common plant-based butter alternatives.
    text = re.sub(
        r"\b(?:peanut|almond|cashew|sunflower|seed|apple)\s+butter\b",
        " ",
        text
    )

    # Avoid obvious non-dairy cream references.
    text = re.sub(
        r"\b(?:coconut\s+cream|cream\s+of\s+tartar|"
        r"cream\s+of\s+coconut)\b",
        " ",
        text
    )

    dairy_terms = [
        "milk",
        "cheese",
        "butter",
        "cream",
        "yogurt",
        "yoghurt",
        "whey",
        "casein",
        "lactose",
        "ghee",
        "buttermilk",
        "curd",
        "kefir",
        "ricotta",
        "mascarpone",
        "parmesan",
        "mozzarella",
        "cheddar",
        "feta",
        "gouda",
        "brie",
        "provolone",
        "gruyere",
        "halloumi",
        "paneer",
        "fontina",
        "pecorino",
        "stilton",
    ]

    pattern = r"\b(?:" + "|".join(
        re.escape(term) for term in dairy_terms
    ) + r")\b"

    return re.search(pattern, text) is not None


def hard_exclusion_matches(
    exclusion_spec,
    recipe_line
):

    """
    Check the entire ingredient line for prohibited ingredients.

    Parenthetical text is intentionally retained because it may
    contain an allergen warning or ingredient mention.
    """

    if not recipe_line or not exclusion_spec:
        return False

    if exclusion_spec.get("name") == "dairy":
        return _matches_dairy_category(recipe_line)

    text = str(recipe_line).casefold()

    text = ADVERTISEMENT_PATTERN.sub(
        " ",
        text
    )

    text = (
        text
        .replace("(", " ")
        .replace(")", " ")
    )

    text = apply_aliases(text)

    recipe_tokens = {
        singularize_token(token)
        for token in re.findall(r"[a-z0-9]+", text)
    }

    excluded_tokens = set(
        exclusion_spec["name"].split()
    )

    return (
        bool(excluded_tokens)
        and excluded_tokens.issubset(recipe_tokens)
    )


# ==================================================
# 7. QUANTITY COMPARISON
# ==================================================

def assess_quantity(
    requested_spec,
    matching_lines
):

    """
    Compare quantities only when units are compatible.

    If units cannot be safely compared, return not_verified.
    """

    if requested_spec["amount"] is None:

        return "not_requested", None

    requested_unit = requested_spec["unit"]

    if requested_unit is None:

        return "not_verified", None

    requested_dimension, requested_factor, requested_base = (
        requested_unit
    )

    recipe_total = 0.0

    if not matching_lines:

        return "not_verified", None

    for entry in matching_lines:

        recipe_spec = parse_ingredient_spec(
            entry["line"]
        )

        if (
            recipe_spec is None
            or recipe_spec["amount"] is None
            or recipe_spec["unit"] is None
        ):

            return "not_verified", None

        recipe_dimension, recipe_factor, recipe_base = (
            recipe_spec["unit"]
        )

        if (
            recipe_dimension != requested_dimension
            or recipe_base != requested_base
        ):

            return "not_verified", None

        recipe_total += (
            recipe_spec["amount"] * recipe_factor
        )

    requested_total = (
        requested_spec["amount"] * requested_factor
    )

    if recipe_total + 1e-9 >= requested_total:

        return (
            "sufficient",
            recipe_total / requested_factor
        )

    return (
        "insufficient",
        recipe_total / requested_factor
    )


# ==================================================
# 8. ESTIMATE INSTRUCTION STEPS
# ==================================================

def estimate_instruction_steps(instructions):

    """
    Estimate instruction steps using the structure available
    in the source recipe.

    Numbered and bullet steps are stronger evidence.

    Asterisk-prefixed editorial notes are not counted as
    bullet steps.

    Separate lines are estimates, not verified step counts.
    Sentence counts are only proxies.
    """

    if (
        not isinstance(instructions, str)
        or not instructions.strip()
    ):

        return None, "unavailable"

    text = ADVERTISEMENT_PATTERN.sub(
        " ",
        instructions
    ).strip()

    # Remove asterisk-prefixed editorial notes.
    lines = [
        line.strip()
        for line in text.splitlines()
        if (
            line.strip()
            and not re.match(r"^\s*\*\s+", line)
        )
    ]

    if not lines:

        return None, "unavailable"

    text = "\n".join(lines)

    # ----------------------------------------------
    # 1. Detect numbered steps.
    # ----------------------------------------------

    numbered_pattern = re.compile(
        r"(?i)(?<!\S)(?:step\s*)?\d+\s*[.):]\s+"
    )

    numbered_matches = list(
        numbered_pattern.finditer(text)
    )

    starts_with_numbered_step = bool(
        re.match(
            r"(?i)^\s*(?:step\s*)?1\s*[.):]\s+",
            text
        )
    )

    if (
        len(numbered_matches) >= 2
        or starts_with_numbered_step
    ):

        return (
            len(numbered_matches),
            "numbered-step estimate"
        )

    # ----------------------------------------------
    # 2. Detect hyphen or bullet-character steps.
    # An asterisk is deliberately excluded.
    # ----------------------------------------------

    bullet_matches = re.findall(
        r"(?m)^\s*(?:-|–|—|•)\s+\S",
        text
    )

    if bullet_matches:

        return (
            len(bullet_matches),
            "bullet-step estimate"
        )

    # ----------------------------------------------
    # 3. Separate non-empty lines.
    # These are not guaranteed to be cooking steps.
    # ----------------------------------------------

    if len(lines) > 1:

        return (
            len(lines),
            "line-based estimate"
        )

    # ----------------------------------------------
    # 4. Paragraph instructions.
    # Sentence count is only a proxy.
    # ----------------------------------------------

    normalized_text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    sentences = [
        sentence.strip()
        for sentence in re.split(
            r"(?<=[.!?])\s+",
            normalized_text
        )
        if sentence.strip()
    ]

    return (
        max(1, len(sentences)),
        "sentence-count proxy (not verified steps)"
    )


# ==================================================
# 9. RANKING
# ==================================================

def title_quality_rank(title):
    """
    Prefer actual dish titles over preparation-only titles.
    This is a ranking preference, not a recipe exclusion rule.
    """

    normalized_title = (title or "").casefold().strip()

    preparation_prefixes = (
        "how to ",
        "how-to ",
        "boning of ",
        "to bone ",
        "to carve ",
        "to poach ",
        "preparing ",
        "basic technique",
        "technique for ",
    )

    if normalized_title.startswith(preparation_prefixes):
        return 1

    return 0


def ranking_key(result, prefer_fewer_steps):
    """
    Rank recipes by ingredient matching and quantity quality.
    Prefer actual dishes over preparation-only titles when
    the ingredient-match quality is comparable.
    """

    reliable_methods = {
        "numbered-step estimate",
        "bullet-step estimate",
    }

    if (
        prefer_fewer_steps
        and result["step_estimate_method"] in reliable_methods
        and result["estimated_steps"] is not None
    ):
        step_rank = result["estimated_steps"]
    else:
        step_rank = 10**9

    return (
        -result["matched_count"],
        result["missing_count"],
        result["quantity_insufficient_count"],
        result["quantity_unverified_count"],
        -result["quantity_sufficient_count"],
        title_quality_rank(result["title"]),
        step_rank,
        result["additional_count"],
        result["title"].casefold(),
        result["recipe_id"],
    )

# ==================================================
# 10. DUPLICATE RECIPE DETECTION
# ==================================================

def recipe_content_fingerprint(candidate):

    """
    Generate a fingerprint from recipe content.

    Exact duplicates have the same normalized title,
    original ingredient list and original instructions.

    Recipe IDs are intentionally excluded so that
    duplicate source records can be identified.
    """

    try:

        ingredients = json.loads(
            candidate["ingredients_original_json"] or "[]"
        )

    except (json.JSONDecodeError, TypeError):

        ingredients = []

    content = {

        "title": (
            candidate["title"] or ""
        ).strip().casefold(),

        "ingredients": ingredients,

        "instructions": (
            candidate["instructions"] or ""
        ).strip(),

    }

    serialized = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":")
    )

    return hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()



# ==================================================
# 11. CREATE RECIPE RESULT
# ==================================================

def make_result(
    candidate,
    requested_specs
):

    matched = {}

    matched_positions = set()

    quantity_counts = {
        "sufficient": 0,
        "insufficient": 0,
        "not_verified": 0,
    }

    # ----------------------------------------------
    # Find requested ingredient matches.
    # ----------------------------------------------

    for spec in requested_specs:

        found = []

        for entry in candidate["ingredient_entries"]:

            if ingredient_name_matches(
                spec,
                entry["line"]
            ):

                found.append(entry)

                matched_positions.add(
                    entry["position"]
                )

        if found:

            quantity_status, available_amount = assess_quantity(
                spec,
                found
            )

            if quantity_status in quantity_counts:

                quantity_counts[quantity_status] += 1

            # Clean only the displayed ingredient lines.
            # Quantity checking still uses original text.
            display_lines = []

            for entry in found:

                cleaned_line = clean_display_ingredient(
                    entry["line"]
                )

                if cleaned_line:
                    display_lines.append(cleaned_line)

            matched[spec["original"]] = {

                "lines": display_lines,

                "quantity_status": quantity_status,

                "available_amount_in_requested_unit": available_amount,

            }

    matched_names = set(matched)

    missing = [
        spec["original"]
        for spec in requested_specs
        if spec["original"] not in matched_names
    ]

    if not matched:

        return None

    # ----------------------------------------------
    # Load original ingredient list.
    # ----------------------------------------------

    original_ingredients = []

    if candidate["ingredients_original_json"]:

        try:

            loaded = json.loads(
                candidate["ingredients_original_json"]
            )

            if isinstance(loaded, list):

                original_ingredients = loaded

        except (json.JSONDecodeError, TypeError):

            original_ingredients = []

    # ----------------------------------------------
    # Prepare additional ingredients.
    # Remove advertisement markers from displayed text.
    # ----------------------------------------------

    additional = []

    for index, ingredient in enumerate(original_ingredients):

        if not isinstance(ingredient, str):
            continue

        if not ingredient.strip():
            continue

        if index in matched_positions:
            continue

        cleaned_ingredient = clean_display_ingredient(
            ingredient
        )

        if cleaned_ingredient:
            additional.append(cleaned_ingredient)

    # ----------------------------------------------
    # Estimate instruction steps.
    # ----------------------------------------------

    steps, step_method = estimate_instruction_steps(
        candidate["instructions"]
    )

    matched_count = len(matched)

    # ----------------------------------------------
    # Return recipe result.
    # ----------------------------------------------

    return {

        "recipe_id": candidate["recipe_id"],

        "title": candidate["title"],

        "source_file": candidate["source_file"],

        "instructions": candidate["instructions"],

        "matched_ingredients": matched,

        "missing_ingredients": missing,

        "additional_ingredients": additional,

        "matched_count": matched_count,

        "missing_count": len(missing),

        "coverage": matched_count / len(requested_specs),

        "additional_count": len(additional),

        "estimated_steps": steps,

        "step_estimate_method": step_method,

        "quantity_sufficient_count": quantity_counts["sufficient"],

        "quantity_insufficient_count": quantity_counts["insufficient"],

        "quantity_unverified_count": quantity_counts["not_verified"],

    }

# ==================================================
# 12. FULL-DATASET MATCHING
# ==================================================

def match_recipes(
    ingredients,
    hard_exclusions=None,
    max_missing=None,
    limit=5,
    prefer_fewer_steps=False,
):

    """
    Evaluate every eligible recipe in SQLite.

    No FTS top-k cutoff is used.

    Exact duplicate recipe content is grouped in the
    displayed results while preserving all original IDs.
    """

    if not isinstance(limit, int) or not 1 <= limit <= 100:

        raise ValueError(
            "Limit must be between 1 and 100."
        )

    if max_missing is not None:

        if (
            not isinstance(max_missing, int)
            or max_missing < 0
        ):

            raise ValueError(
                "max_missing must be a non-negative integer."
            )

    if not ingredients:

        raise ValueError(
            "Enter at least one required ingredient."
        )

    # ----------------------------------------------
    # Parse and deduplicate requested ingredients.
    # ----------------------------------------------

    requested_specs = []

    seen_requests = {}

    for raw in ingredients:

        spec = parse_ingredient_spec(raw)

        if spec is None:
            continue

        key = spec["name"]

        if key in seen_requests:

            previous = seen_requests[key]

            if (
                previous["amount"] != spec["amount"]
                or previous["unit"] != spec["unit"]
            ):

                raise ValueError(
                    f"Ingredient '{key}' was requested more than "
                    "once with different quantities. Combine it "
                    "into one ingredient request."
                )

            continue

        seen_requests[key] = spec

        requested_specs.append(spec)

    if not requested_specs:

        raise ValueError(
            "Enter at least one valid ingredient."
        )

    # ----------------------------------------------
    # Parse and deduplicate hard exclusions.
    # ----------------------------------------------

    exclusion_specs = []

    seen_exclusions = set()

    for raw in hard_exclusions or []:

        spec = parse_ingredient_spec(raw)

        if spec is not None and spec["name"] not in seen_exclusions:

            exclusion_specs.append(spec)

            seen_exclusions.add(spec["name"])

    connection = get_connection()

    top_results = []

    # Only map fingerprints that currently occupy
    # one of the top displayed result positions.
    top_results_by_fingerprint = {}

    seen_content_fingerprints = set()

    recipes_evaluated = 0

    recipes_blocked_by_exclusion = 0

    recipes_with_any_match = 0

    recipes_qualifying = 0

    exact_matches = 0

    partial_matches = 0

    unique_qualifying_recipes = 0

    duplicate_source_records = 0

    current = None

    # ----------------------------------------------
    # Finish one recipe after collecting its lines.
    # ----------------------------------------------

    def finish_candidate(candidate):

        nonlocal recipes_evaluated
        nonlocal recipes_blocked_by_exclusion
        nonlocal recipes_with_any_match
        nonlocal recipes_qualifying
        nonlocal exact_matches
        nonlocal partial_matches
        nonlocal unique_qualifying_recipes
        nonlocal duplicate_source_records

        if candidate is None:
            return

        recipes_evaluated += 1

        if recipes_evaluated % 10000 == 0:

            print(
                f"Scanned {recipes_evaluated:,} recipes...",
                file=sys.stderr
            )

        # ------------------------------------------
        # Enforce hard exclusions first.
        # ------------------------------------------

        if exclusion_specs:

            for exclusion in exclusion_specs:

                if any(
                    hard_exclusion_matches(
                        exclusion,
                        entry["line"]
                    )
                    for entry in candidate["ingredient_entries"]
                ):

                    recipes_blocked_by_exclusion += 1

                    return

        # ------------------------------------------
        # Check requested ingredient matches.
        # ------------------------------------------

        result = make_result(
            candidate,
            requested_specs
        )

        if result is None:
            return

        recipes_with_any_match += 1

        # ------------------------------------------
        # Apply maximum missing ingredient filter.
        # ------------------------------------------

        if (
            max_missing is not None
            and result["missing_count"] > max_missing
        ):

            return

        if result["missing_count"] == 0:

            exact_matches += 1

        else:

            partial_matches += 1

        # Count qualifying original source records.
        recipes_qualifying += 1

        # ------------------------------------------
        # Detect exact duplicate recipe content.
        # ------------------------------------------

        fingerprint = recipe_content_fingerprint(
            candidate
        )

        if fingerprint in seen_content_fingerprints:

            duplicate_source_records += 1

            # Add the source ID when the original recipe
            # currently appears in the top results.
            existing = top_results_by_fingerprint.get(
                fingerprint
            )

            if existing is not None:

                duplicate_ids = existing["duplicate_recipe_ids"]

                if candidate["recipe_id"] not in duplicate_ids:

                    duplicate_ids.append(
                        candidate["recipe_id"]
                    )

            return

        seen_content_fingerprints.add(
            fingerprint
        )

        unique_qualifying_recipes += 1

        result["duplicate_recipe_ids"] = [
            candidate["recipe_id"]
        ]

        result["_content_fingerprint"] = fingerprint

        # ------------------------------------------
        # Maintain the top N unique results.
        # ------------------------------------------

        top_results.append(result)

        top_results.sort(
            key=lambda item: ranking_key(
                item,
                prefer_fewer_steps
            )
        )

        if len(top_results) > limit:

            removed = top_results.pop()

            removed_fingerprint = removed[
                "_content_fingerprint"
            ]

            top_results_by_fingerprint.pop(
                removed_fingerprint,
                None
            )

        # Only retain the mapping when the result is
        # still among the displayed top N.
        if any(
            item is result
            for item in top_results
        ):

            top_results_by_fingerprint[fingerprint] = result

    # ----------------------------------------------
    # Stream every eligible recipe and its ingredients.
    # ----------------------------------------------

    try:

        cursor = connection.execute(
            """
            SELECT
                r.recipe_id,
                r.title_original,
                r.source_file,
                r.ingredients_original_json,
                r.instructions_original,
                ri.position,
                ri.ingredient_original,
                ri.is_searchable
            FROM recipes AS r
            LEFT JOIN recipe_ingredients AS ri
                ON r.recipe_id = ri.recipe_id
            WHERE r.has_title = 1
              AND r.has_ingredients = 1
            ORDER BY r.recipe_id, ri.position
            """
        )

        for row in cursor:

            recipe_id = row["recipe_id"]

            # First recipe.
            if current is None:

                current = {

                    "recipe_id": recipe_id,

                    "title": row["title_original"],

                    "source_file": row["source_file"],

                    "ingredients_original_json": row[
                        "ingredients_original_json"
                    ],

                    "instructions": row["instructions_original"],

                    "ingredient_entries": [],

                }

            # Recipe ID changed. Finish previous recipe.
            elif recipe_id != current["recipe_id"]:

                finish_candidate(current)

                current = {

                    "recipe_id": recipe_id,

                    "title": row["title_original"],

                    "source_file": row["source_file"],

                    "ingredients_original_json": row[
                        "ingredients_original_json"
                    ],

                    "instructions": row["instructions_original"],

                    "ingredient_entries": [],

                }

            # Collect searchable ingredient entries.
            if (
                row["ingredient_original"] is not None
                and row["is_searchable"]
            ):

                current["ingredient_entries"].append({

                    "position": row["position"],

                    "line": row["ingredient_original"],

                })

        # Process final recipe.
        finish_candidate(current)

    finally:

        connection.close()

    # Remove internal fingerprint from returned records.
    for result in top_results:

        result.pop(
            "_content_fingerprint",
            None
        )

    return {

        "requested_ingredients": [
            spec["original"]
            for spec in requested_specs
        ],

        "hard_exclusions": [
            spec["original"]
            for spec in exclusion_specs
        ],

        "recipes_evaluated": recipes_evaluated,

        "recipes_blocked_by_exclusion": recipes_blocked_by_exclusion,

        "recipes_with_any_match": recipes_with_any_match,

        "recipes_qualifying": recipes_qualifying,

        "unique_qualifying_recipes": unique_qualifying_recipes,

        "duplicate_source_records": duplicate_source_records,

        "exact_matches": exact_matches,

        "partial_matches": partial_matches,

        "results": top_results,

        "max_missing": max_missing,

        "prefer_fewer_steps": prefer_fewer_steps,

    }


# ==================================================
# 13. DISPLAY RESULTS
# ==================================================

def display_results(output):

    print("\n" + "=" * 68)

    print("NOSH AI - INTELLIGENT INGREDIENT MATCHING")

    print("=" * 68)

    print(
        "Required ingredients:",
        output["requested_ingredients"]
    )

    print(
        "Hard exclusions:",
        output["hard_exclusions"] or "None"
    )

    print(
        f"Eligible recipes evaluated: "
        f"{output['recipes_evaluated']:,}"
    )

    print(
        f"Recipes blocked by hard exclusions: "
        f"{output['recipes_blocked_by_exclusion']:,}"
    )

    print(
        f"Recipes with at least one requested ingredient: "
        f"{output['recipes_with_any_match']:,}"
    )

    print(
        f"Recipes passing all active filters: "
        f"{output['recipes_qualifying']:,}"
    )

    print(
        f"Unique qualifying recipe contents: "
        f"{output['unique_qualifying_recipes']:,}"
    )

    print(
        f"Duplicate source records grouped: "
        f"{output['duplicate_source_records']:,}"
    )

    print(
        f"Complete ingredient-name matches: "
        f"{output['exact_matches']:,}"
    )

    print(
        f"Partial ingredient matches: "
        f"{output['partial_matches']:,}"
    )

    if output["max_missing"] is not None:

        print(
            "Maximum missing ingredients allowed:",
            output["max_missing"]
        )

    if output["prefer_fewer_steps"]:

        print(
            "Ranking preference: fewer structured instruction steps "
            "where available."
        )

        print(
            "Unstructured line and sentence estimates do not "
            "control this ranking."
        )

    if output["hard_exclusions"]:

        print(
            "Note: exclusion checks use recipe ingredient text; "
            "they cannot guarantee allergy safety or prevent cross-contact."
        )

    print(
        "\nTop results are ranked after evaluating the full eligible dataset."
    )

    if not output["results"]:

        print(
            "\nNo recipes matched the requested ingredients "
            "under these constraints."
        )

        return

    for index, recipe in enumerate(
        output["results"],
        start=1
    ):

        print("\n" + "-" * 68)

        print(
            f"RESULT {index}: {recipe['title']}"
        )

        print("-" * 68)

        print(
            "Recipe ID:",
            recipe["recipe_id"]
        )

        # Show all IDs belonging to an exact duplicate group.
        duplicate_ids = recipe.get(
            "duplicate_recipe_ids",
            [recipe["recipe_id"]]
        )

        if len(duplicate_ids) > 1:

            print(
                "Other identical source IDs:",
                ", ".join(duplicate_ids[1:])
            )

        print(
            "Source:",
            recipe["source_file"]
        )

        print(
            f"Ingredient coverage: "
            f"{recipe['matched_count']}/"
            f"{recipe['matched_count'] + recipe['missing_count']} "
            f"({recipe['coverage']:.0%})"
        )

        # ------------------------------------------
        # Matched ingredients.
        # ------------------------------------------

        print("\nMatched ingredients:")

        for requested_name, details in (
            recipe["matched_ingredients"].items()
        ):

            print(f"  {requested_name}:")

            for line in details["lines"]:

                print("    -", line)

            status = details["quantity_status"]

            if status == "sufficient":

                print(
                    "    Quantity check: sufficient "
                    "(comparable units)"
                )

            elif status == "insufficient":

                print(
                    "    Quantity check: insufficient "
                    "(comparable units)"
                )

            elif status == "not_verified":

                print(
                    "    Quantity check: not verified; "
                    "name-level match only"
                )

            else:

                print(
                    "    Quantity check: not requested"
                )

        # ------------------------------------------
        # Missing ingredients.
        # ------------------------------------------

        print("\nMissing ingredients:")

        if recipe["missing_ingredients"]:

            for item in recipe["missing_ingredients"]:

                print("  -", item)

        else:

            print(
                "  None; all requested ingredient names were found."
            )

        # ------------------------------------------
        # Additional ingredients.
        # ------------------------------------------

        print(
            f"\nAdditional recipe ingredients "
            f"({recipe['additional_count']}):"
        )

        if recipe["additional_ingredients"]:

            for item in recipe["additional_ingredients"][:10]:

                print("  -", item)

            if recipe["additional_count"] > 10:

                print(
                    f"  ... and "
                    f"{recipe['additional_count'] - 10} more"
                )

        else:

            print("  None")

        # ------------------------------------------
        # Instruction steps.
        # ------------------------------------------

        if recipe["estimated_steps"] is None:

            print(
                "\nInstruction steps: unavailable"
            )

        else:

            print(
                f"\nEstimated instruction steps: "
                f"{recipe['estimated_steps']} "
                f"({recipe['step_estimate_method']})"
            )

        # ------------------------------------------
        # Ranking rationale.
        # ------------------------------------------

        print("\nRanking rationale:")

        print(
            f"  Matched {recipe['matched_count']} "
            f"requested ingredient(s), "
            f"{recipe['missing_count']} missing, "
            f"{recipe['additional_count']} "
            f"additional ingredient line(s)."
        )


# ==================================================
# 14. COMMAND-LINE INTERFACE
# ==================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Rank recipes using required ingredients "
            "and hard exclusions."
        )
    )

    parser.add_argument(
        "--ingredient",
        nargs="+",
        required=True,
        help=(
            'Required ingredients. Quote multiword items, '
            'e.g. "bell pepper".'
        )
    )

    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        help=(
            "Hard exclusions, e.g. "
            "--exclude peanuts shellfish."
        )
    )

    parser.add_argument(
        "--max-missing",
        type=int,
        default=None,
        help=(
            "Optional maximum number of requested "
            "ingredients allowed to be missing."
        )
    )

    parser.add_argument(
        "--prefer-fewer-steps",
        action="store_true",
        help=(
            "Prefer recipes with fewer numbered or "
            "bullet-structured instruction steps."
        )
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help=(
            "Number of top-ranked recipes to display (1-100)."
        )
    )

    args = parser.parse_args()

    try:

        output = match_recipes(

            ingredients=args.ingredient,

            hard_exclusions=args.exclude,

            max_missing=args.max_missing,

            limit=args.limit,

            prefer_fewer_steps=args.prefer_fewer_steps,

        )

        display_results(output)

    except (
        ValueError,
        FileNotFoundError,
        sqlite3.Error
    ) as error:

        parser.error(str(error))


if __name__ == "__main__":

    main()
