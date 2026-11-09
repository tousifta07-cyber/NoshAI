import json
import re
import os
import time
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import ServerError
from pydantic import BaseModel, Field


# ==================================================
# 1. ENVIRONMENT CONFIGURATION
# ==================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]

load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError("GEMINI_API_KEY was not found in .env")

# Reuse one client for all requests.
CLIENT = genai.Client(
    api_key=API_KEY,
    http_options=types.HttpOptions(
        timeout=30_000,
        retry_options=types.HttpRetryOptions(
            attempts=1
        ),
    ),
)


# ==================================================
# 2. STRUCTURED INTENT SCHEMA
# ==================================================

class RecipeIntent(BaseModel):

    action: Literal[
        "search",
        "details",
        "analytics",
        "match",
        "substitute",
        "help"
    ]

    query: Optional[str] = None

    search_in: Optional[
        Literal["all", "title", "ingredients", "instructions"]
    ] = "all"

    recipe_id: Optional[str] = None

    # Exact or clearly identifiable recipe title explicitly
    # mentioned by the user in the current message.
    recipe_title: Optional[str] = None

    recipe_number: Optional[int] = None

    limit: Optional[int] = Field(
        default=5,
        ge=1,
        le=20
    )

    ingredients: list[str] = Field(default_factory=list)

    max_steps: Optional[int] = Field(
        default=None,
        ge=1,
        le=100
    )

    prefer_fewer_steps: bool = False

    nutrition_question: bool = False

    hard_exclusions: list[str] = Field(default_factory=list)
    add_hard_exclusions: list[str] = Field(default_factory=list)
    remove_hard_exclusions: list[str] = Field(default_factory=list)

    clear_hard_exclusions: bool = False

    original_ingredient: Optional[str] = None
    replacement_ingredient: Optional[str] = None

    selected_ingredient_line: Optional[str] = None
    instruction_context: Optional[str] = None


# ==================================================
# 3. INTENT NORMALIZATION
# ==================================================



def extract_explicit_max_steps(user_message: str | None) -> int | None:
    """Extract an explicitly requested maximum number of recipe steps."""

    if not user_message:
        return None

    number_words = {
        "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8,
        "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
        "thirteen": 13, "fourteen": 14, "fifteen": 15,
        "sixteen": 16, "seventeen": 17, "eighteen": 18,
        "nineteen": 19, "twenty": 20,
    }

    count_pattern = (
        r"(?P<count>\d+|"
        + "|".join(number_words)
        + r")"
    )

    patterns = [
        r"(?:at most|no more than|up to)\s+"
        + count_pattern
        + r"\s+(?:(?:instruction|cooking)\s+)?steps?\b",

        count_pattern
        + r"\s+or fewer\s+(?:(?:instruction|cooking)\s+)?steps?\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, user_message, re.IGNORECASE)

        if match:
            raw_count = match.group("count").casefold()
            count = (
                int(raw_count)
                if raw_count.isdigit()
                else number_words[raw_count]
            )

            if 1 <= count <= 100:
                return count

    return None


def normalize_intent(
    intent: dict,
    conversation_context: dict | None = None,
    user_message: str | None = None,
) -> dict:
    """
    Apply deterministic corrections to Gemini's intent.

    Hard exclusions must never be handled by ordinary keyword search.
    """

    intent = dict(intent)

    explicit_max_steps = extract_explicit_max_steps(user_message)
    if explicit_max_steps is not None:
        intent["max_steps"] = explicit_max_steps

    # Deterministically recognize a preference for fewer instruction steps.
    # This is a ranking preference, not a hard maximum.
    latest_message = (user_message or "").casefold()

    fewer_steps_patterns = (
        r"\bfewest\s+(?:instruction\s+)?steps?\b",
        r"\bleast\s+(?:instruction\s+)?steps?\b",
        r"\bprefer\s+fewer\s+(?:instruction\s+)?steps?\b",
        r"\bfewer\s+(?:instruction\s+)?steps?\b",
        r"\bminimum\s+(?:number\s+of\s+)?steps?\b",
    )

    if any(
        re.search(pattern, latest_message)
        for pattern in fewer_steps_patterns
    ):
        intent["prefer_fewer_steps"] = True

        # A request to rank recipes by instruction steps is a
        # recipe-matching request, not a dataset-statistics request.
        if intent.get("action") == "analytics":
            intent["action"] = "match"

        # Preserve the ingredient requested by the user.
        if not intent.get("ingredients") and intent.get("query"):
            intent["ingredients"] = [intent["query"]]
            intent["query"] = None

    # Detect nutrition questions about a named recipe.
    nutrition_terms = (
        "calorie", "calories", "nutrition", "nutritional",
        "protein", "carbohydrate", "carbs", "fat", "fats",
        "sugar", "sodium"
    )

    nutrition_question = any(
        re.search(r"\b" + re.escape(term) + r"\b", latest_message)
        for term in nutrition_terms
    )

    if nutrition_question:
        intent["nutrition_question"] = True

        # Extract the title after common nutrition question wording.
        title_patterns = (
            r"\b(?:servings?\s+of)\s+(.+?)\s*[?.!]*$",
            r"\b(?:in|for)\s+(?:one|a|an|the)\s+servings?\s+of\s+(.+?)\s*[?.!]*$",
            r"\b(?:calories?|nutrition|protein|carbs?|fat|sugar|sodium)\s+(?:in|for)\s+(.+?)\s*[?.!]*$",
        )

        if not intent.get("recipe_title"):
            for pattern in title_patterns:
                title_match = re.search(pattern, latest_message)
                if title_match:
                    intent["recipe_title"] = title_match.group(1).strip()
                    break

        if intent.get("recipe_title") or intent.get("recipe_id"):
            intent["action"] = "details"

    existing_exclusions = intent.get("hard_exclusions") or []
    added_exclusions = intent.get("add_hard_exclusions") or []

    has_exclusions = bool(
        existing_exclusions or added_exclusions
    )

    if intent.get("action") == "search" and has_exclusions:

        intent["action"] = "match"

    # Detect an exclusion-only follow-up to a previous search.
    # A remembered search query must not become a new required ingredient.
    context = conversation_context or {}
    latest_message = (user_message or "").casefold()

    previous_search_exists = bool(
        context.get("last_action") in {"search", "match"}
        and context.get("last_search_query")
        and context.get("recent_results")
    )

    proposed_ingredients = (
        intent.get("ingredients")
        or ([intent.get("query")] if intent.get("query") else [])
    )

    excluded_terms = {
        str(item).strip().casefold()
        for item in (
            existing_exclusions + added_exclusions
        )
    }

    explicitly_requested_ingredient = any(
        str(term).strip()
        and str(term).strip().casefold() not in excluded_terms
        and str(term).strip().casefold() in latest_message
        for term in proposed_ingredients
    )

    exclusion_only_followup = (
        intent.get("action") == "match"
        and previous_search_exists
        and has_exclusions
        and not explicitly_requested_ingredient
    )

    if exclusion_only_followup:
        intent["ingredients"] = []
        intent["query"] = None

    # Otherwise, convert a new match query into required ingredients.
    elif (
        intent.get("action") == "match"
        and not intent.get("ingredients")
        and intent.get("query")
    ):
        intent["ingredients"] = [intent["query"]]
        intent["query"] = None

    # Safe defaults for downstream Python functions.
    if intent.get("action") in {"search", "analytics"}:

        if not intent.get("search_in"):
            intent["search_in"] = "all"

    if intent.get("action") in {
        "search", "match", "substitute"
    }:

        if intent.get("limit") is None:
            intent["limit"] = 5

    if intent.get("action") == "analytics":

        if intent.get("limit") is None:
            intent["limit"] = 10

    # Normalize empty recipe titles to None.
    if not intent.get("recipe_title"):
        intent["recipe_title"] = None

    return intent


# ==================================================
# 4. GEMINI INTENT PARSER
# ==================================================

def parse_intent(
    user_message: str,
    conversation_context: dict | None = None
):
    """
    Convert natural-language requests into structured intents.

    Gemini interprets the request.
    Python and SQLite execute recipe operations.
    """

    if not user_message or not user_message.strip():

        raise ValueError("User message cannot be empty.")

    context = json.dumps(
        conversation_context or {},
        ensure_ascii=False,
        default=str
    )

    prompt = f"""
You are the intent parser for Nosh AI, a recipe assistant.

Your ONLY job is to convert the user's request into the RecipeIntent schema.

SUPPORTED ACTIONS:

- search: Find recipes using keywords.
- details: Retrieve a specific recipe.
- analytics: Calculate statistics over matching recipes.
- match: Find recipes containing requested ingredients and obeying exclusions.
- substitute: Evaluate an ingredient substitution in a specific recipe.
- help: Explain available capabilities.

IMPORTANT RULES:

1. Return structured intent only. Do not answer the recipe question.
2. Never invent recipe IDs or recipe facts.
3. Preserve ingredient names and quantities as stated.
4. Distinguish hard exclusions from ordinary preferences.
5. Use conversation context to resolve follow-ups.
6. Do not remove existing exclusions unless explicitly requested.
7. Use add_hard_exclusions to add exclusions.
8. Use remove_hard_exclusions to remove exclusions.
9. Use clear_hard_exclusions only when asked to clear all exclusions.

10. For substitution, extract:
    - original_ingredient
    - replacement_ingredient
    - recipe_title, if the user explicitly names a recipe
    - recipe_id, if the user explicitly provides an ID
    - recipe_number, if the user refers to a numbered previous result

11. Do not invent selected_ingredient_line or instruction_context.
    Leave them null unless the user explicitly provides them.
    Python will retrieve and validate the original recipe's ingredient
    lines and instructions from the local database.

12. If information is missing, do not guess.

13. Choose the most appropriate action.

14. Requests requiring specific ingredients must use MATCH.

15. Requests containing "without", "exclude", "avoid",
    or "do not contain" must use MATCH.

16. Put required ingredients in the ingredients field.

17. Put excluded ingredients in add_hard_exclusions.

18. Questions asking "how many" or requesting dataset statistics
    should use ANALYTICS.

19. Ordinary keyword searches without ingredient constraints
    should use SEARCH.

20. RECIPE TITLE EXTRACTION:
    If the user's latest message explicitly mentions a recipe title,
    extract the complete title into recipe_title.
    Do not put an ingredient name or a generic phrase into recipe_title.
    Do not invent or guess a recipe title.
    If the user does not mention a recipe title in the latest message,
    leave recipe_title null.

21. EXPLICIT TITLE PRIORITY:
    If the user names a recipe in the latest message, extract that title
    even if conversation context contains a different selected recipe.
    The explicitly named recipe must take priority over the old selection.

22. FOLLOW-UP SUBSTITUTION:
    If the user previously selected a recipe and now says something like
    "replace butter with olive oil", use action substitute and extract
    the original and replacement ingredients.
    Leave recipe_title null if no title is mentioned in the latest message.
    Python will use the selected recipe from conversation context.

23. SUBSTITUTION EXAMPLES:

    User: "Replace butter with olive oil"
    action: substitute
    original_ingredient: "butter"
    replacement_ingredient: "olive oil"
    recipe_title: null

    User: "Replace butter with olive oil in Potage Dame Edmee"
    action: substitute
    original_ingredient: "butter"
    replacement_ingredient: "olive oil"
    recipe_title: "Potage Dame Edmee"

    User: "In recipe number 2, replace butter with olive oil"
    action: substitute
    original_ingredient: "butter"
    replacement_ingredient: "olive oil"
    recipe_number: 2

24. MAXIMUM INSTRUCTION STEPS:
    When the user explicitly requests a hard maximum such as
    "at most six steps", set max_steps to that integer.
    If the user only prefers fewer steps, leave max_steps null.

CONVERSATION CONTEXT:
{context}

USER'S LATEST MESSAGE:
{user_message}
"""

    # ==================================================
    # 5. API REQUEST WITH LIMITED RETRY
    # ==================================================

    for attempt in range(2):

        try:

            response = CLIENT.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=RecipeIntent,
                    temperature=0
                )
            )

            if response.parsed is not None:

                parsed_intent = response.parsed.model_dump()

                return normalize_intent(parsed_intent, conversation_context, user_message)

            if response.text:

                parsed_intent = RecipeIntent.model_validate_json(
                    response.text
                ).model_dump()

                return normalize_intent(parsed_intent, conversation_context, user_message)

            raise ValueError(
                "Gemini returned an empty intent response."
            )

        except ServerError:

            # Retry only once after a temporary server error.
            if attempt == 0:

                print(
                    "Gemini temporarily unavailable. "
                    "Retrying once after 5 seconds..."
                )

                time.sleep(5)

            else:
                raise