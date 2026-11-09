import json
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

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError("GEMINI_API_KEY was not found in .env")

# Reuse one client for all requests.
CLIENT = genai.Client(api_key=API_KEY)


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

def normalize_intent(intent: dict) -> dict:
    """
    Apply deterministic corrections to Gemini's intent.

    Hard exclusions must never be handled by ordinary keyword search.
    """

    intent = dict(intent)

    existing_exclusions = intent.get("hard_exclusions") or []
    added_exclusions = intent.get("add_hard_exclusions") or []

    has_exclusions = bool(
        existing_exclusions or added_exclusions
    )

    if intent.get("action") == "search" and has_exclusions:

        intent["action"] = "match"

    # If Gemini identifies a match request but puts the required
    # ingredient in query, move it into ingredients.
    if (
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

                return normalize_intent(parsed_intent)

            if response.text:

                parsed_intent = RecipeIntent.model_validate_json(
                    response.text
                ).model_dump()

                return normalize_intent(parsed_intent)

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