from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STEP_01B = REPO_ROOT / "skills" / "bmad-story-automator" / "steps-c" / "step-01b-continue.md"
STEP_03A = REPO_ROOT / "skills" / "bmad-story-automator" / "steps-c" / "step-03a-execute-review.md"


class ResumeMatrixTests(unittest.TestCase):
    def test_step_01b_routes_review_and_tea_tokens_to_step_03a(self) -> None:
        text = STEP_01B.read_text(encoding="utf-8")
        self.assertIn(
            '`step-03a-execute-review` or `auto` or `test_automate` or `test_review` or `nfr` or `trace` or `review` → `{executeReviewStep}`',
            text,
        )

    def test_step_03a_handles_review_resume_without_replaying_tea_steps(self) -> None:
        text = STEP_03A.read_text(encoding="utf-8")
        self.assertIn('skip_tea_quality_steps=false', text)
        self.assertIn('review) skip_tea_quality_steps=true ;;', text)
        self.assertIn('if [ "$skip_tea_quality_steps" = "true" ]; then', text)
        self.assertIn('break', text)

    def test_step_03a_advances_current_step_after_each_tea_success(self) -> None:
        text = STEP_03A.read_text(encoding="utf-8")
        self.assertIn('next_quality_step=""', text)
        self.assertIn('--set currentStep="$next_quality_step"', text)
        self.assertIn('--set currentStep=review', text)


if __name__ == "__main__":
    unittest.main()
