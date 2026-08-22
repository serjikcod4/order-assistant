from enum import Enum


class Brand(str, Enum):
    SKF = "SKF"
    FAG = "FAG"
    NSK = "NSK"


class GroundingIssueCode(str, Enum):
    UNGROUNDED_MODEL = "ungrounded_model"
    UNGROUNDED_PRIMARY_BRAND = "ungrounded_primary_brand"
    UNGROUNDED_FALLBACK_BRAND = "ungrounded_fallback_brand"
    UNGROUNDED_QUANTITY = "ungrounded_quantity"
    UNGROUNDED_PRICE = "ungrounded_price"
    AMBIGUOUS_DELIVERY_DEADLINE = "ambiguous_delivery_deadline"
    UNSAFE_CLARIFICATION_CONTENT = "unsafe_clarification_content"
    UNSUPPORTED_BRAND = "unsupported_brand"
    MISSING_MODEL = "missing_model"
    MISSING_QUANTITY = "missing_quantity"
    MISSING_PRIMARY_BRAND = "missing_primary_brand"
    MISSING_PRICE = "missing_price"
    MISSING_DELIVERY_DEADLINE = "missing_delivery_deadline"


class LLMRolloutMode(str, Enum):
    DISABLED = "disabled"
    SHADOW = "shadow"
    REVIEW = "review"


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ExtractionProcessingOutcome(str, Enum):
    SHADOW_PROCESSED = "shadow_processed"
    DRAFT_READY = "draft_ready"
    CLARIFICATION_NEEDED = "clarification_needed"
    NO_MATCH = "no_match"
    LLM_ERROR = "llm_error"


class ExtractionReviewDecision(str, Enum):
    ACCEPTED = "accepted"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class ExtractionCorrectionCode(str, Enum):
    MODEL = "model"
    QUANTITY = "quantity"
    PRIMARY_BRAND = "primary_brand"
    FALLBACK_BRANDS = "fallback_brands"
    MAX_UNIT_PRICE = "max_unit_price"
    DELIVERY_DEADLINE = "delivery_deadline"
    SPLIT_FULFILLMENT = "split_fulfillment"
    OTHER = "other"


class RejectionReason(str, Enum):
    MODEL_MISMATCH = "model_mismatch"
    BRAND_NOT_ALLOWED = "brand_not_allowed"
    INSUFFICIENT_STOCK = "insufficient_stock"
    PRICE_TOO_HIGH = "price_too_high"
    DELIVERY_TOO_LATE = "delivery_too_late"


class OrderProcessingStatus(str, Enum):
    NEEDS_CLARIFICATION = "needs_clarification"
    NO_MATCH = "no_match"
    DRAFT_READY = "draft_ready"


class DraftStatus(str, Enum):
    DRAFT_READY = "draft_ready"
    APPROVED = "approved"
    REJECTED = "rejected"
    ORDER_CREATED = "order_created"


class SubmissionStatus(str, Enum):
    PENDING = "pending"
    UNKNOWN = "unknown"
    SUCCEEDED = "succeeded"
    PERMANENTLY_FAILED = "permanently_failed"


class ERPFailureMode(str, Enum):
    SUCCESS = "success"
    TIMEOUT_BEFORE_CREATION = "timeout_before_creation"
    TIMEOUT_AFTER_CREATION = "timeout_after_creation"
    PERMANENT_FAILURE = "permanent_failure"


class ActorRole(str, Enum):
    VIEWER = "viewer"
    MANAGER = "manager"
    OPERATOR = "operator"
    ADMIN = "admin"


class Permission(str, Enum):
    READ_DRAFT = "read_draft"
    READ_SUBMISSION = "read_submission"
    APPROVE_DRAFT = "approve_draft"
    REJECT_DRAFT = "reject_draft"
    SUBMIT_ORDER = "submit_order"
    RETRY_SUBMISSION = "retry_submission"
    RECONCILE_SUBMISSION = "reconcile_submission"
    READ_EXTRACTION_AUDIT = "read_extraction_audit"
    REVIEW_EXTRACTION = "review_extraction"
