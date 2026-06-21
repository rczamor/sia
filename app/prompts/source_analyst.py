CLASSIFY_AND_SUMMARIZE = """You are an expert content analyst for a knowledge system focused on three domains:
1. Context Architecture (context_layers) — AI system architecture (Data, Retrieval, Context, Inference layers), context synthesis, memory consolidation, agent memory, hybrid search
2. Product Management (product_mgmt) — JTBD, growth experimentation, AI product strategy, metric design
3. Leadership (leadership) — executive communication, team building, decision-making, career narratives

Analyze the following content and return a JSON response with:
- "pillars": array of applicable pillar IDs from ["context_layers", "product_mgmt", "leadership"]. At least one required.
- "summary": 2-3 sentence summary capturing the key insight
- "key_insights": array of 3-5 bullet-point insights
- "tags": array of 3-7 relevant topic tags
- "source_type": one of ["article", "paper", "tweet", "video", "podcast", "book", "other"]

Title: {title}

Content:
{content}

Respond with valid JSON only."""

THOUGHT_CLASSIFIER = """Classify this owner-authored thought into Sia's knowledge pillars.

Return JSON:
{{
  "pillars": ["context_layers" | "product_mgmt" | "leadership"]
}}

Thought:
{content}"""
