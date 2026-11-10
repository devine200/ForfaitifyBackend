"""Fallback Didit workflow ids when env vars are empty. Prefer DIDIT_*_WORKFLOW_ID."""

# Business Verification (KYB) — merchants. Overridden by DIDIT_KYB_WORKFLOW_ID /
# DIDIT_TEST_KYB_WORKFLOW_ID when set. Test workflows should include a Liveness step.
KYB_WORKFLOW_ID = "8ab1d167-8632-4a9a-a141-c1a7a628d87e"
