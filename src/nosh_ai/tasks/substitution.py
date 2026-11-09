
import argparse
import json
import re
import sqlite3
from pathlib import Path
import sys


# ==================================================
# 1. PROJECT IMPORTS
# ==================================================

SRC_ROOT = Path(__file__).resolve().parents[2]

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from nosh_ai.retrieval import ingredient_matcher as matcher


# ==================================================
# 2. SUPPORTED SUBSTITUTION RULES
# ==================================================

SUBSTITUTION_RULES = {

    ("butter", "olive oil"): {
        "role": "cooking fat",
        "allowed_methods": {
            "pan_cooking",
            "frying",
            "roasting",
            "dressing",
            "marinating",
        },
        "blocked_methods": {
            "baking",
            "creaming",
            "pastry",
        },
        "effects": [
            "The buttery flavor will be reduced.",
            "Olive oil may add its own aroma and flavor.",
            "Butter contains water and milk solids, while olive oil is predominantly fat.",
            "Texture and cooking behaviour may change.",
        ],
        "guidance": (
            "Use olive oil at the selected cooking stage. "
            "Add an appropriate amount gradually. Do not assume "
            "that the original butter quantity is directly "
            "equivalent to olive oil."
        ),
    },

    ("vegetable oil", "canola oil"): {
        "role": "neutral liquid cooking fat",
        "allowed_methods": {
            "pan_cooking",
            "frying",
            "roasting",
            "baking",
            "dressing",
            "marinating",
        },
        "blocked_methods": set(),
        "effects": [
            "Both are commonly used as neutral liquid cooking oils.",
            "A major flavor difference is not necessarily expected.",
            "The result depends on the particular oil and recipe.",
        ],
        "guidance": (
            "Use canola oil at the same cooking stage as the "
            "original vegetable oil. Quantity equivalence has "
            "not been experimentally verified for this recipe."
        ),
    },

    ("canola oil", "vegetable oil"): {
        "role": "neutral liquid cooking fat",
        "allowed_methods": {
            "pan_cooking",
            "frying",
            "roasting",
            "baking",
            "dressing",
            "marinating",
        },
        "blocked_methods": set(),
        "effects": [
            "Both are commonly used as neutral liquid cooking oils.",
            "A major flavor difference is not necessarily expected.",
        ],
        "guidance": (
            "Use vegetable oil at the same cooking stage as the "
            "original canola oil. Check the amount for the recipe."
        ),
    },

    ("lemon juice", "lime juice"): {
        "role": "acid and citrus flavor",
        "allowed_methods": {
            "dressing",
            "marinating",
            "salsa",
            "grilling",
            "simmering",
        },
        "blocked_methods": set(),
        "effects": [
            "Lime juice provides acidity with a different citrus aroma.",
            "The flavor will become more lime-forward.",
            "The final flavor should be adjusted to taste.",
        ],
        "guidance": (
            "Use lime juice at the stage where lemon juice is used. "
            "Add gradually and adjust to taste."
        ),
    },

    ("lime juice", "lemon juice"): {
        "role": "acid and citrus flavor",
        "allowed_methods": {
            "dressing",
            "marinating",
            "salsa",
            "grilling",
            "simmering",
        },
        "blocked_methods": set(),
        "effects": [
            "Lemon juice provides acidity with a different citrus aroma.",
            "The flavor will become more lemon-forward.",
        ],
        "guidance": (
            "Use lemon juice at the stage where lime juice is used. "
            "Adjust gradually to taste."
        ),
    },

    ("white vinegar", "apple cider vinegar"): {
        "role": "acid",
        "allowed_methods": {
            "dressing",
            "marinating",
            "simmering",
        },
        "blocked_methods": set(),
        "effects": [
            "Apple cider vinegar may add a fruitier flavor.",
            "Acidity can vary by product.",
        ],
        "guidance": (
            "Add apple cider vinegar at the same stage as the "
            "original vinegar. Check the product's acidity."
        ),
    },

    ("apple cider vinegar", "white vinegar"): {
        "role": "acid",
        "allowed_methods": {
            "dressing",
            "marinating",
            "simmering",
        },
        "blocked_methods": set(),
        "effects": [
            "White vinegar generally has a sharper, less fruity flavor.",
            "The flavor profile may become less fruity.",
        ],
        "guidance": (
            "Add white vinegar at the same stage as the "
            "original vinegar, adjusting gradually."
        ),
    },
}


# ==================================================
# 3. PREPARATION METHOD DETECTION
# ==================================================

METHOD_PATTERNS = {

    "pan_cooking": (
        r"\b(?:saucepan|saucepans|skillet|frying pan|"
        r"sauté|saute|sauteed|pan[- ]?fry|"
        r"cook over medium|stir[- ]fry)\b"
    ),

    "frying": (
        r"\b(?:fry|frying|fried|deep[- ]fry|"
        r"pan[- ]fry|panfry|brown|sear)\b"
    ),

    "roasting": (
        r"\b(?:roast|roasted|roasting)\b"
    ),

    "baking": (
        r"\b(?:bake|baked|baking|pastry|cookies?|cakes?)\b"
    ),

    "creaming": (
        r"\b(?:creaming|creamed)\s+(?:the\s+)?butter\b"
        r"|\bcream\s+(?:the\s+)?butter\b"
        r"|\bbeat\s+(?:the\s+)?butter"
        r"(?:\s+and\s+sugar)?\s+until\s+(?:light|fluffy)\b"
    ),

    "dressing": (
        r"\b(?:dressing|vinaigrette|drizzle)\b"
    ),

    "marinating": (
        r"\b(?:marinade|marinate|marinating)\b"
    ),

    "salsa": (
        r"\bsalsa\b"
    ),

    "grilling": (
        r"\b(?:grill|grilled|grilling|barbecue)\b"
    ),

    "simmering": (
        r"\b(?:simmer|simmered|simmering)\b"
    ),
}


# ==================================================
# 4. TEXT HELPERS
# ==================================================

def clean_text(value):

    if not isinstance(value, str):
        return ""

    value = matcher.ADVERTISEMENT_PATTERN.sub(
        " ",
        value.casefold()
    )

    value = re.sub(r"\s+", " ", value)

    return value.strip()


def normalize_line(value):

    return re.sub(
        r"\s+",
        " ",
        str(value).casefold()
    ).strip()


def extract_preparation_methods(instructions):

    text = clean_text(instructions)

    methods = set()

    for method, pattern in METHOD_PATTERNS.items():

        if re.search(pattern, text, re.IGNORECASE):
            methods.add(method)

    return methods


def build_fts_query(ingredient_spec):

    words = ingredient_spec["name"].split()

    safe_words = [
        f'"{word}"'
        for word in words
    ]

    return (
        "ingredients : ("
        + " AND ".join(safe_words)
        + ")"
    )


# ==================================================
# 5. CHECK EXPLICIT SUBSTITUTION EVIDENCE
# ==================================================

def explicitly_mentions_substitution(
    instructions,
    original_name,
    replacement_name
):

    text = clean_text(instructions)

    original = re.escape(original_name)
    replacement = re.escape(replacement_name)

    patterns = [

        rf"\b{replacement}\b.{{0,80}}\b(?:instead of|in place of)\b.{{0,80}}\b{original}\b",

        rf"\b(?:replace|substitute)\b.{{0,80}}\b{original}\b.{{0,80}}\b(?:with|by|for)\b.{{0,80}}\b{replacement}\b",

        rf"\bsubstitute\b.{{0,80}}\b{replacement}\b.{{0,80}}\bfor\b.{{0,80}}\b{original}\b",

    ]

    return any(
        re.search(pattern, text, re.IGNORECASE)
        for pattern in patterns
    )


# ==================================================
# 6. GET SOURCE RECIPE BY STABLE ID
# ==================================================

def get_source_recipe(recipe_id):

    connection = matcher.get_connection()

    try:

        recipe = connection.execute(
            """
            SELECT
                recipe_id,
                title_original,
                source_file,
                ingredients_original_json,
                instructions_original,
                has_instructions
            FROM recipes
            WHERE recipe_id = ?
            """,
            (recipe_id,)
        ).fetchone()

        if recipe is None:
            return None

        entries = connection.execute(
            """
            SELECT
                position,
                ingredient_original,
                is_searchable
            FROM recipe_ingredients
            WHERE recipe_id = ?
            ORDER BY position
            """,
            (recipe_id,)
        ).fetchall()

        try:

            original_ingredients = json.loads(
                recipe["ingredients_original_json"] or "[]"
            )

        except (json.JSONDecodeError, TypeError):

            original_ingredients = []

        return {

            "recipe_id": recipe["recipe_id"],

            "title": recipe["title_original"],

            "source_file": recipe["source_file"],

            "ingredients_original_json": (
                recipe["ingredients_original_json"]
            ),

            "ingredients": original_ingredients,

            "instructions": recipe["instructions_original"],

            "ingredient_entries": [

                {
                    "position": entry["position"],
                    "line": entry["ingredient_original"],
                }

                for entry in entries

                if (
                    entry["ingredient_original"] is not None
                    and entry["is_searchable"]
                )
            ],

            "has_instructions": bool(
                recipe["has_instructions"]
            ),
        }

    finally:

        connection.close()


# ==================================================
# 7. SPLIT COMBINED INGREDIENT ENTRIES
# ==================================================

def split_ingredient_components(line):

    """
    Split a combined ingredient entry into comma/semicolon
    separated components.

    Example:
        Chicken, stock, peas, butter, onion

    becomes:
        Chicken
        stock
        peas
        butter
        onion

    The original database line is never modified here.
    """

    if not isinstance(line, str):
        return []

    return [
        component.strip()
        for component in re.split(r"[,;]", line)
        if component.strip()
    ]


# ==================================================
# 8. SELECT ONE EXACT INGREDIENT COMPONENT
# ==================================================

def select_exact_ingredient_line(
    recipe,
    original_spec,
    selected_line
):

    """
    Select one ingredient entry and identify exactly one
    matching ingredient component inside that entry.

    Supports both:
      - Standalone entries: 2 ounces butter
      - Combined entries: Chicken, stock, peas, butter, onion

    Does not select compound butter products such as
    peanut butter or lobster butter.
    """

    wanted = normalize_line(selected_line)

    exact_matches = [

        entry

        for entry in recipe["ingredient_entries"]

        if normalize_line(entry["line"]) == wanted

    ]

    if not exact_matches:

        return {
            "status": "ingredient_line_not_found",
            "message": (
                "The selected ingredient line does not exactly "
                "match an original ingredient entry in this recipe."
            ),
        }

    if len(exact_matches) > 1:

        return {
            "status": "ambiguous_ingredient_line",
            "message": (
                "The exact ingredient line appears more than once. "
                "A more specific selection is required."
            ),
        }

    entry = exact_matches[0]

    components = split_ingredient_components(
        entry["line"]
    )

    matching_components = [

        component

        for component in components

        if source_line_matches(
            original_spec,
            component
        )

    ]

    if not matching_components:

        if original_spec["name"] == "butter":

            compound_patterns = [
                r"\bpeanut\s+butter\b",
                r"\balmond\s+butter\b",
                r"\bcashew\s+butter\b",
                r"\blobster\s+butter\b",
                r"\bbutter\s+flavou?r\b",
            ]

            contains_compound_butter = any(
                re.search(pattern, component, re.IGNORECASE)
                for component in components
                for pattern in compound_patterns
            )

            if contains_compound_butter:
                return {
                    "status": "compound_ingredient_not_selected",
                    "message": (
                        "The selected ingredient is a compound "
                        "butter product, not ordinary butter. "
                        "It cannot be selected for this substitution."
                    ),
                }

        return {
            "status": "ingredient_name_mismatch",
            "message": (
                "The selected ingredient entry does not contain "
                "the requested ingredient as a recognizable component."
            ),
        }

    if len(matching_components) > 1:

        return {
            "status": "ambiguous_ingredient_component",
            "message": (
                "The selected entry contains more than one matching "
                "ingredient component. A more specific selection "
                "is required."
            ),
        }

    selected_component = matching_components[0]

    selected_spec = matcher.parse_ingredient_spec(
        selected_component
    )

    if selected_spec is None:

        return {
            "status": "invalid_ingredient_component",
            "message": (
                "The selected ingredient component could not be parsed."
            ),
        }

    return {

        "status": "selected",

        "entry": entry,

        "selected_spec": selected_spec,

        "selected_component": selected_component,

    }


# ==================================================
# 9. REPLACE ONLY THE SELECTED COMPONENT
# ==================================================

def replace_selected_ingredient_component(
    original_line,
    selected_component,
    original_name,
    replacement_name
):

    """
    Replace only the requested ingredient name inside its
    selected component.

    Examples:

        butter
        -> olive oil

        6 tablespoons butter
        -> 6 tablespoons olive oil

    Other components in the original line remain unchanged.
    """

    if not isinstance(original_line, str):
        return {
            "success": False,
            "message": "The original ingredient entry is not text.",
        }

    component_matches = list(
        re.finditer(
            re.escape(selected_component),
            original_line,
            re.IGNORECASE
        )
    )

    if len(component_matches) != 1:

        return {
            "success": False,
            "message": (
                "The selected ingredient component does not occur "
                "exactly once in the original entry."
            ),
        }

    component_match = component_matches[0]

    target_pattern = re.compile(
        rf"(?<![a-z]){re.escape(original_name)}(?![a-z])",
        re.IGNORECASE
    )

    target_matches = list(
        target_pattern.finditer(selected_component)
    )

    if len(target_matches) != 1:

        return {
            "success": False,
            "message": (
                "The requested ingredient name does not occur "
                "exactly once inside the selected component."
            ),
        }

    revised_component = target_pattern.sub(
        replacement_name,
        selected_component,
        count=1
    )

    revised_line = (
        original_line[:component_match.start()]
        + revised_component
        + original_line[component_match.end():]
    )

    return {
        "success": True,
        "revised_line": revised_line,
    }


# ==================================================
# 10. REVISE ONLY THE SELECTED INSTRUCTION CONTEXT
# ==================================================

def revise_instruction_context(
    instructions,
    instruction_context,
    original_name,
    replacement_name
):

    if not isinstance(instructions, str) or not instructions.strip():

        return {
            "success": False,
            "status": "instructions_unavailable",
            "message": "The source recipe has no usable instructions.",
        }

    if not instruction_context or not instruction_context.strip():

        return {
            "success": False,
            "status": "instruction_context_required",
            "message": (
                "Provide an exact phrase from the original "
                "instructions to identify the intended use."
            ),
        }

    context_matches = list(
        re.finditer(
            re.escape(instruction_context),
            instructions,
            re.IGNORECASE
        )
    )

    if not context_matches:

        return {
            "success": False,
            "status": "instruction_context_not_found",
            "message": (
                "The supplied instruction context was not found "
                "in the original recipe."
            ),
        }

    if len(context_matches) > 1:

        return {
            "success": False,
            "status": "ambiguous_instruction_context",
            "message": (
                "The supplied instruction context appears more "
                "than once. Provide a longer, more specific phrase."
            ),
        }

    match = context_matches[0]

    original_context = match.group(0)

    target_pattern = re.compile(
        rf"(?<![a-z]){re.escape(original_name)}(?![a-z])",
        re.IGNORECASE
    )

    target_matches = list(
        target_pattern.finditer(original_context)
    )

    if not target_matches:

        return {
            "success": False,
            "status": "ingredient_not_in_instruction_context",
            "message": (
                "The original ingredient name does not appear "
                "inside the selected instruction context."
            ),
        }

    if len(target_matches) > 1:

        return {
            "success": False,
            "status": "ambiguous_ingredient_use",
            "message": (
                "The selected instruction context contains "
                "multiple occurrences of the original ingredient. "
                "Provide a narrower phrase."
            ),
        }

    revised_context = target_pattern.sub(
        replacement_name,
        original_context,
        count=1
    )

    revised_instructions = (
        instructions[:match.start()]
        + revised_context
        + instructions[match.end():]
    )

    return {

        "success": True,

        "status": "updated",

        "revised_instructions": revised_instructions,

        "updated_context": revised_context,

        "original_context": original_context,
    }


# ==================================================
# 11. LOCAL RECIPE EVIDENCE SEARCH
# ==================================================

def search_local_evidence(
    replacement_spec,
    original_spec,
    source_methods,
    limit=5
):

    fts_query = build_fts_query(
        replacement_spec
    )

    connection = matcher.get_connection()

    evidence = []

    evidence_candidate_count = 0
    matching_recipe_count = 0
    same_method_count = 0
    direct_evidence_count = 0

    current = None

    def finish_candidate(candidate):

        nonlocal matching_recipe_count
        nonlocal same_method_count
        nonlocal direct_evidence_count

        if candidate is None:
            return

        matching_lines = [

            entry

            for entry in candidate["ingredient_entries"]

            if matcher.ingredient_name_matches(
                replacement_spec,
                entry["line"]
            )
        ]

        if not matching_lines:
            return

        matching_recipe_count += 1

        candidate_methods = extract_preparation_methods(
            candidate["instructions"]
        )

        shared_methods = (
            source_methods & candidate_methods
        )

        explicit = explicitly_mentions_substitution(
            candidate["instructions"],
            original_spec["name"],
            replacement_spec["name"]
        )

        if explicit and shared_methods:

            evidence_type = (
                "explicit substitution statement "
                "with similar preparation method"
            )

            direct_evidence_count += 1
            same_method_count += 1

        elif explicit:

            evidence_type = (
                "explicit substitution statement "
                "in a different preparation method; "
                "not directly transferable"
            )

        elif shared_methods:

            evidence_type = (
                "indirect evidence: similar preparation method"
            )

            same_method_count += 1

        else:

            evidence_type = (
                "indirect evidence: replacement ingredient usage only"
            )

        item = {

            "recipe_id": candidate["recipe_id"],

            "title": candidate["title"],

            "source_file": candidate["source_file"],

            "matching_ingredient_lines": [
                entry["line"]
                for entry in matching_lines
            ],

            "preparation_methods": sorted(
                candidate_methods
            ),

            "shared_methods": sorted(
                shared_methods
            ),

            "evidence_type": evidence_type,

            "explicit_substitution": explicit,
        }

        evidence.append(item)

    try:

        evidence_candidate_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM recipes_fts
            JOIN recipes AS r
                ON recipes_fts.recipe_id = r.recipe_id
            WHERE recipes_fts MATCH ?
              AND r.recipe_id != ?
              AND r.has_title = 1
              AND r.has_ingredients = 1
              AND r.has_instructions = 1
            """,
            (
                fts_query,
                original_spec["source_recipe_id"]
            )
        ).fetchone()[0]

        cursor = connection.execute(
            """
            WITH candidates AS (
                SELECT
                    recipe_id,
                    bm25(
                        recipes_fts,
                        0.0,
                        10.0,
                        5.0,
                        1.0
                    ) AS relevance_score
                FROM recipes_fts
                WHERE recipes_fts MATCH ?
            )
            SELECT
                c.recipe_id,
                c.relevance_score,
                r.title_original,
                r.source_file,
                r.instructions_original,
                ri.position,
                ri.ingredient_original,
                ri.is_searchable
            FROM candidates AS c
            JOIN recipes AS r
                ON c.recipe_id = r.recipe_id
            LEFT JOIN recipe_ingredients AS ri
                ON r.recipe_id = ri.recipe_id
            WHERE r.recipe_id != ?
              AND r.has_title = 1
              AND r.has_ingredients = 1
              AND r.has_instructions = 1
            ORDER BY
                c.relevance_score ASC,
                c.recipe_id ASC,
                ri.position ASC
            """,
            (
                fts_query,
                original_spec["source_recipe_id"]
            )
        )

        for row in cursor:

            recipe_id = row["recipe_id"]

            if current is None:

                current = {
                    "recipe_id": recipe_id,
                    "title": row["title_original"],
                    "source_file": row["source_file"],
                    "instructions": row["instructions_original"],
                    "ingredient_entries": [],
                }

            elif recipe_id != current["recipe_id"]:

                finish_candidate(current)

                current = {
                    "recipe_id": recipe_id,
                    "title": row["title_original"],
                    "source_file": row["source_file"],
                    "instructions": row["instructions_original"],
                    "ingredient_entries": [],
                }

            if (
                row["ingredient_original"] is not None
                and row["is_searchable"]
            ):

                current["ingredient_entries"].append({

                    "position": row["position"],

                    "line": row["ingredient_original"],

                })

        finish_candidate(current)

    finally:

        connection.close()

    evidence.sort(
        key=lambda item: (
            not bool(item["shared_methods"]),
            not item["explicit_substitution"],
            -len(item["shared_methods"]),
            item["title"].casefold(),
            item["recipe_id"],
        )
    )

    return {

        "candidate_count": evidence_candidate_count,

        "matching_recipe_count": matching_recipe_count,

        "same_method_count": same_method_count,

        "direct_evidence_count": direct_evidence_count,

        "evidence": evidence[:limit],
    }


# ==================================================
# 12. BUILD LINE-SPECIFIC SUBSTITUTION PLAN
# ==================================================

def build_substitution_plan(
    recipe_id,
    original_ingredient,
    replacement_ingredient,
    selected_ingredient_line,
    instruction_context,
    evidence_limit=5
):

    if (
        not isinstance(evidence_limit, int)
        or not 1 <= evidence_limit <= 100
    ):

        raise ValueError(
            "Evidence limit must be between 1 and 100."
        )

    original_spec = matcher.parse_ingredient_spec(
        original_ingredient
    )

    replacement_spec = matcher.parse_ingredient_spec(
        replacement_ingredient
    )

    if original_spec is None or replacement_spec is None:

        raise ValueError(
            "Enter valid original and replacement ingredients."
        )

    original_name = original_spec["name"]
    replacement_name = replacement_spec["name"]

    if original_name == replacement_name:

        raise ValueError(
            "The original and replacement ingredients must differ."
        )

    # ----------------------------------------------
    # Retrieve the original recipe.
    # ----------------------------------------------

    recipe = get_source_recipe(recipe_id)

    if recipe is None:

        return {
            "status": "recipe_not_found",
            "message": "No recipe exists with that recipe ID.",
            "revised_ingredients": None,
            "revised_instructions": None,
        }

    # ----------------------------------------------
    # Select one ingredient component.
    # ----------------------------------------------

    selection = select_exact_ingredient_line(
        recipe,
        original_spec,
        selected_ingredient_line
    )

    if selection["status"] != "selected":

        return {

            "status": selection["status"],

            "recipe_id": recipe_id,

            "recipe_title": recipe["title"],

            "message": selection["message"],

            "revised_ingredients": None,

            "revised_instructions": None,
        }

    selected_entry = selection["entry"]
    selected_component = selection["selected_component"]

    # ----------------------------------------------
    # Revise only the exact instruction phrase.
    # ----------------------------------------------

    instruction_update = revise_instruction_context(
        recipe["instructions"],
        instruction_context,
        original_name,
        replacement_name
    )

    if not instruction_update["success"]:

        return {

            "status": instruction_update["status"],

            "recipe_id": recipe_id,

            "recipe_title": recipe["title"],

            "selected_ingredient_line": selected_entry["line"],

            "message": instruction_update["message"],

            "revised_ingredients": None,

            "revised_instructions": None,
        }

    # ----------------------------------------------
    # Detect cooking context.
    # ----------------------------------------------

    source_methods = extract_preparation_methods(
        instruction_update["original_context"]
    )

    # ----------------------------------------------
    # Search local evidence.
    # ----------------------------------------------

    original_spec["source_recipe_id"] = recipe_id

    local_evidence = search_local_evidence(
        replacement_spec,
        original_spec,
        source_methods,
        limit=evidence_limit
    )

    rule = SUBSTITUTION_RULES.get(
        (original_name, replacement_name)
    )

    # ----------------------------------------------
    # Evaluate substitution support.
    # ----------------------------------------------

    status = None
    reason = None

    if rule is None:

        status = "unsupported_substitution_pair"

        reason = (
            "This ingredient pair does not have a predefined "
            "culinary-role rule. The system will not invent "
            "a substitution."
        )

    elif not source_methods:

        status = "insufficient_preparation_context"

        reason = (
            "The source instructions do not provide enough "
            "preparation-method information to evaluate "
            "the substitution."
        )

    elif source_methods & rule["blocked_methods"]:

        status = "incompatible_preparation_context"

        reason = (
            "The source recipe includes a preparation method "
            "for which this substitution rule is not supported."
        )

    elif not source_methods & rule["allowed_methods"]:

        status = "unsupported_preparation_context"

        reason = (
            "The source recipe's cooking method does not "
            "match the methods supported by this substitution rule."
        )

    elif (
        local_evidence["same_method_count"] == 0
        and local_evidence["direct_evidence_count"] == 0
    ):

        status = "insufficient_local_evidence"

        reason = (
            "The local dataset does not contain enough supporting "
            "evidence for the proposed replacement in a comparable "
            "preparation context."
        )

    else:

        status = "supported_with_caveats"

        if local_evidence["direct_evidence_count"]:

            reason = (
                "The local dataset contains explicit substitution "
                "references. The outcome for this particular recipe "
                "has still not been experimentally verified."
            )

        else:

            reason = (
                "The local dataset contains recipes using the "
                "replacement ingredient with a similar preparation "
                "method. This is indirect evidence, not proof."
            )

    # ----------------------------------------------
    # Build common result.
    # ----------------------------------------------

    result = {

        "status": status,

        "reason": reason,

        "recipe_id": recipe["recipe_id"],

        "recipe_title": recipe["title"],

        "source_file": recipe["source_file"],

        "original_ingredient": original_ingredient,

        "replacement_ingredient": replacement_ingredient,

        "selected_ingredient_line": selected_entry["line"],

        "selected_ingredient_component": selected_component,

        "selected_ingredient_position": selected_entry["position"],

        "instruction_context": instruction_context,

        "source_preparation_methods": sorted(source_methods),

        "supporting_recipe_count": (
            local_evidence["matching_recipe_count"]
        ),

        "same_method_evidence_count": (
            local_evidence["same_method_count"]
        ),

        "direct_substitution_evidence_count": (
            local_evidence["direct_evidence_count"]
        ),

        "evidence": local_evidence["evidence"],

        "revised_ingredients": None,

        "revised_instructions": None,

        "predicted_effects": [],

        "quantity_note": (
            "No automatic quantity conversion is performed. "
            "The replacement amount must be determined for "
            "the specific recipe."
        ),

        "experimental_verification": (
            "Not performed. Predicted effects are not verified outcomes."
        ),

        "safety_note": (
            "Recipe data cannot establish allergy safety, medical "
            "suitability, or absence of cross-contact."
        ),
    }

    # ----------------------------------------------
    # Refuse unsupported substitutions.
    # ----------------------------------------------

    if status != "supported_with_caveats":
        return result

    # ----------------------------------------------
    # Update only the selected ingredient component.
    # ----------------------------------------------

    revised_ingredients = list(
        recipe["ingredients"]
    )

    position = selected_entry["position"]

    if position >= len(revised_ingredients):

        result["status"] = "ingredient_position_mismatch"

        result["reason"] = (
            "The selected database ingredient position does not "
            "match the original ingredient list. No revision was made."
        )

        return result

    original_list_entry = revised_ingredients[position]

    if not isinstance(original_list_entry, str):

        result["status"] = "unsupported_ingredient_entry_format"

        result["reason"] = (
            "The original ingredient entry is not a text value. "
            "No revision was made."
        )

        return result

    ingredient_update = replace_selected_ingredient_component(
        original_line=original_list_entry,
        selected_component=selected_component,
        original_name=original_name,
        replacement_name=replacement_name
    )

    if not ingredient_update["success"]:

        result["status"] = "ingredient_component_update_failed"

        result["reason"] = ingredient_update["message"]

        return result

    revised_ingredients[position] = (
        ingredient_update["revised_line"]
    )

    # ----------------------------------------------
    # Build revised instructions.
    # ----------------------------------------------

    revised_instructions = (
        instruction_update["revised_instructions"]
        + "\n\n"
        + "PROPOSED SUBSTITUTION NOTE:\n"
        + rule["guidance"]
    )

    result["revised_ingredients"] = revised_ingredients

    result["revised_instructions"] = revised_instructions

    result["culinary_role"] = rule["role"]

    result["predicted_effects"] = rule["effects"]

    result["quantity_note"] = (
        "The selected ingredient quantity has not been converted. "
        "If the original component included a quantity, it is retained "
        "as a reference only. Determine an appropriate replacement "
        "amount for the recipe."
    )

    return result


# ==================================================
# 13. FIND SOURCE RECIPES
# ==================================================

def source_line_matches(spec, line):

    """
    Avoid treating compound butter products as ordinary butter
    during source discovery and component selection.
    """

    if spec["name"] == "butter":

        compound_patterns = [

            r"\bpeanut\s+butter\b",

            r"\balmond\s+butter\b",

            r"\bcashew\s+butter\b",

            r"\blobster\s+butter\b",

            r"\bbutter\s+flavou?r\b",
        ]

        for pattern in compound_patterns:

            if re.search(
                pattern,
                line,
                re.IGNORECASE
            ):

                return False

    return matcher.ingredient_name_matches(
        spec,
        line
    )


def find_source_candidates(
    ingredient,
    limit=10
):

    if not isinstance(limit, int) or not 1 <= limit <= 100:

        raise ValueError(
            "Limit must be between 1 and 100."
        )

    spec = matcher.parse_ingredient_spec(
        ingredient
    )

    if spec is None:

        raise ValueError(
            "Enter a valid ingredient."
        )

    fts_query = build_fts_query(spec)

    connection = matcher.get_connection()

    results = []
    current = None

    def finish_candidate(candidate):

        if candidate is None:
            return

        matches = [

            entry["line"]

            for entry in candidate["ingredient_entries"]

            if source_line_matches(
                spec,
                entry["line"]
            )
        ]

        if matches:

            results.append({

                "recipe_id": candidate["recipe_id"],

                "title": candidate["title"],

                "source_file": candidate["source_file"],

                "matching_lines": matches,
            })

    try:

        cursor = connection.execute(
            """
            WITH candidates AS (
                SELECT
                    recipe_id,
                    bm25(
                        recipes_fts,
                        0.0,
                        10.0,
                        5.0,
                        1.0
                    ) AS relevance_score
                FROM recipes_fts
                WHERE recipes_fts MATCH ?
            )
            SELECT
                c.recipe_id,
                c.relevance_score,
                r.title_original,
                r.source_file,
                ri.position,
                ri.ingredient_original,
                ri.is_searchable
            FROM candidates AS c
            JOIN recipes AS r
                ON c.recipe_id = r.recipe_id
            LEFT JOIN recipe_ingredients AS ri
                ON r.recipe_id = ri.recipe_id
            WHERE r.has_title = 1
              AND r.has_ingredients = 1
            ORDER BY
                c.relevance_score ASC,
                c.recipe_id ASC,
                ri.position ASC
            """,
            (fts_query,)
        )

        for row in cursor:

            recipe_id = row["recipe_id"]

            if current is None:

                current = {
                    "recipe_id": recipe_id,
                    "title": row["title_original"],
                    "source_file": row["source_file"],
                    "ingredient_entries": [],
                }

            elif recipe_id != current["recipe_id"]:

                finish_candidate(current)

                if len(results) >= limit:
                    break

                current = {
                    "recipe_id": recipe_id,
                    "title": row["title_original"],
                    "source_file": row["source_file"],
                    "ingredient_entries": [],
                }

            if (
                row["ingredient_original"] is not None
                and row["is_searchable"]
            ):

                current["ingredient_entries"].append({

                    "position": row["position"],

                    "line": row["ingredient_original"],
                })

        if len(results) < limit:
            finish_candidate(current)

    finally:

        connection.close()

    return results[:limit]


# ==================================================
# 14. DISPLAY SOURCE SEARCH RESULTS
# ==================================================

def display_source_candidates(results):

    print("\n" + "=" * 68)

    print("NOSH AI - SOURCE RECIPE SEARCH")

    print("=" * 68)

    if not results:

        print("No matching source recipes found.")

        return

    for index, recipe in enumerate(results, start=1):

        print("\n" + "-" * 68)

        print(f"RESULT {index}: {recipe['title']}")

        print("Recipe ID:", recipe["recipe_id"])

        print("Source:", recipe["source_file"])

        print("Ingredient evidence:")

        for line in recipe["matching_lines"]:

            print("  -", line)


# ==================================================
# 15. DISPLAY SUBSTITUTION RESULTS
# ==================================================

def display_substitution_result(result):

    print("\n" + "=" * 68)

    print("NOSH AI - EVIDENCE-BASED SUBSTITUTION")

    print("=" * 68)

    print("Decision:", result["status"])

    if "recipe_title" in result:
        print("Recipe:", result["recipe_title"])

    if "recipe_id" in result:
        print("Recipe ID:", result["recipe_id"])

    if "selected_ingredient_line" in result:

        print(
            "Selected ingredient line:",
            result["selected_ingredient_line"]
        )

    if "selected_ingredient_component" in result:

        print(
            "Selected ingredient component:",
            result["selected_ingredient_component"]
        )

    if "instruction_context" in result:

        print(
            "Selected instruction context:",
            result["instruction_context"]
        )

    if "original_ingredient" in result:

        print(
            "Original ingredient:",
            result["original_ingredient"]
        )

    if "replacement_ingredient" in result:

        print(
            "Proposed replacement:",
            result["replacement_ingredient"]
        )

    print("\nDecision explanation:")

    print(result.get("reason", result.get("message", "")))

    if "source_preparation_methods" not in result:
        return

    print(
        "\nSource preparation methods:",
        result["source_preparation_methods"]
    )

    print("\nLOCAL DATASET EVIDENCE")

    print(
        "Recipes containing proposed replacement:",
        result["supporting_recipe_count"]
    )

    print(
        "Recipes with similar preparation methods:",
        result["same_method_evidence_count"]
    )

    print(
        "Explicit substitution references:",
        result["direct_substitution_evidence_count"]
    )

    if result["evidence"]:

        for index, item in enumerate(
            result["evidence"],
            start=1
        ):

            print("\nEvidence", index)

            print("Title:", item["title"])

            print("Recipe ID:", item["recipe_id"])

            print("Evidence type:", item["evidence_type"])

            print(
                "Replacement ingredient lines:",
                item["matching_ingredient_lines"]
            )

            print(
                "Preparation methods:",
                item["preparation_methods"]
            )

            print(
                "Shared methods:",
                item["shared_methods"]
            )

    else:

        print("No supporting local recipes found.")

    if result["revised_ingredients"] is not None:

        print("\nPROPOSED UPDATED INGREDIENTS")

        for line in result["revised_ingredients"]:
            print(" -", line)

        print("\nPROPOSED REVISED INSTRUCTIONS")

        print(result["revised_instructions"])

        print("\nPREDICTED EFFECTS")

        for effect in result["predicted_effects"]:
            print(" -", effect)

    else:

        print(
            "\nNo revised recipe was generated because "
            "the substitution did not pass the evidence checks."
        )

    print("\nQUANTITY NOTE")

    print(result["quantity_note"])

    print("\nVERIFICATION NOTE")

    print(result["experimental_verification"])

    print("\nSAFETY NOTE")

    print(result["safety_note"])


# ==================================================
# 16. COMMAND-LINE INTERFACE
# ==================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Evaluate line-specific ingredient substitutions "
            "using the local Recipe Box dataset."
        )
    )

    parser.add_argument(
        "--find-ingredient",
        help=(
            "Find recipes containing an ingredient. "
            "Example: --find-ingredient butter"
        )
    )

    parser.add_argument(
        "--recipe-id",
        help="Stable recipe ID of the recipe to adapt."
    )

    parser.add_argument(
        "--replace",
        help="Original ingredient name to replace."
    )

    parser.add_argument(
        "--replace-line",
        help=(
            "Exact original ingredient entry to replace, "
            'e.g. "2 ounces butter".'
        )
    )

    parser.add_argument(
        "--with",
        dest="replacement",
        help="Proposed replacement ingredient."
    )

    parser.add_argument(
        "--instruction-context",
        help=(
            "Exact phrase from the instructions identifying "
            'the selected use, e.g. "Saute in butter".'
        )
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of supporting recipes to display."
    )

    args = parser.parse_args()

    try:

        if args.find_ingredient:

            results = find_source_candidates(
                args.find_ingredient,
                args.limit
            )

            display_source_candidates(results)

            return

        required_arguments = [
            args.recipe_id,
            args.replace,
            args.replace_line,
            args.replacement,
            args.instruction_context,
        ]

        if not all(required_arguments):

            parser.error(
                "Provide --recipe-id, --replace, "
                "--replace-line, --with and "
                "--instruction-context, or use "
                "--find-ingredient."
            )

        result = build_substitution_plan(

            recipe_id=args.recipe_id,

            original_ingredient=args.replace,

            replacement_ingredient=args.replacement,

            selected_ingredient_line=args.replace_line,

            instruction_context=args.instruction_context,

            evidence_limit=args.limit,
        )

        display_substitution_result(result)

    except (
        ValueError,
        FileNotFoundError,
        sqlite3.Error
    ) as error:

        parser.error(str(error))


if __name__ == "__main__":
    main()
