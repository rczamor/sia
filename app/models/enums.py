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


class PostStatus(str, enum.Enum):
    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    PUBLISHED = "published"
    REJECTED = "rejected"


class FactCheckStatus(str, enum.Enum):
    PENDING = "pending"
    PASSED = "passed"
    FLAGGED = "flagged"
    OVERRIDDEN = "overridden"


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
    GENERATE = "generate"
    FACT_CHECK = "fact_check"
    QUALITY_EVAL = "quality_eval"
    CONSOLIDATE = "consolidate"
    DIALOGUE = "dialogue"


class Channel(str, enum.Enum):
    LINKEDIN = "linkedin"
    X = "x"
    NEWSLETTER = "newsletter"


class ExperimentStatus(str, enum.Enum):
    ACTIVE = "active"
    CONCLUDED = "concluded"
    ARCHIVED = "archived"


class PluginCategory(str, enum.Enum):
    PUBLISHING = "publishing"
    INGESTION = "ingestion"
    LLMOPS = "llmops"
    OPTIMIZATION = "optimization"


class EntityType(str, enum.Enum):
    SOURCE_CONTENT = "source_content"
    MY_THOUGHTS = "my_thoughts"
    EXPERTISE_ARTIFACTS = "expertise_artifacts"
    CONSOLIDATIONS = "consolidations"
    GENERATED_POSTS = "generated_posts"
