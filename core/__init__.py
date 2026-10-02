"""ClearLegacy core: document extraction, rules, and explanations."""

from core.pii import install_log_masking

install_log_masking()  # no-op unless CLEARLEGACY_PII_MASKING=1
