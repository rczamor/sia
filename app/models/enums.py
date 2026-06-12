import enum


class Pillar(str, enum.Enum):
    CONTEXT_LAYERS = "context_layers"
    PRODUCT_MGMT = "product_mgmt"
    LEADERSHIP = "leadership"


class SourceType(str, enum.Enum):
    ARTICLE = "article"
    PAPER = "paper"
    TWEET = "tweet"
    VIDEO = "video"
    PODCAST = "podcast"
    BOOK = "book"
    OTHER = "other"


class ThoughtType(str, enum.Enum):
    REACTION = "reaction"
    IDEA = "idea"
    CONNECTION = "connection"
    FRAMEWORK = "framework"


class ThoughtMaturity(str, enum.Enum):
    RAW = "raw"
    DEVELOPING = "developing"
    REFINED = "refined"
    PUBLISHED = "published"


class ArtifactType(str, enum.Enum):
    CASE_STUDY = "case_study"
    FRAMEWORK = "framework"
    METHODOLOGY = "methodology"
    ANALYSIS = "analysis"


class ConsolidationType(str, enum.Enum):
    CONNECTION = "connection"
    PATTERN = "pattern"
    THESIS = "thesis"
    CONTRADICTION = "contradiction"
    GAP = "gap"


class ChangeType(str, enum.Enum):
    CREATE = "create"
    UPDATE = "update"
    ENRICH = "enrich"
    CONSOLIDATE = "consolidate"
    MANUAL_EDIT = "manual_edit"


class OperationType(str, enum.Enum):
    INGEST = "ingest"
    CLASSIFY = "classify"
    SUMMARIZE = "summarize"
    EMBED = "embed"
    CONSOLIDATE = "consolidate"
    BUILD = "build"


class PluginCategory(str, enum.Enum):
    LLM = "llm"
    EMBEDDINGS = "embeddings"
    INGESTION = "ingestion"
    LLMOPS = "llmops"
    STORE_BACKEND = "store_backend"
    OPTIMIZATION = "optimization"


class EntityType(str, enum.Enum):
    SOURCE_CONTENT = "source_content"
    MY_THOUGHTS = "my_thoughts"
    EXPERTISE_ARTIFACTS = "expertise_artifacts"
    CONSOLIDATIONS = "consolidations"
