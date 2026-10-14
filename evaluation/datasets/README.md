# Evaluation dataset

The fixed course for the team benchmark has **not been selected or reviewed**. Do not treat the app's local demo course or generated questions as a benchmark. Select one publicly accessible course with a video/transcript, slides, and textbook chapter, record exact source URLs/licences here, then build and manually review 50–60 items. At least 10–15 items must be off-material refusals; figure and multi-chunk items need explicit human source checks.

The builder writes only `unreviewed` items. Review is a human action. Evaluation runners must filter for `review_status == "approved"`; never report draft items as ground truth. No approved JSONL dataset is bundled because no team-reviewed course labels are available.

Each JSONL record has: `id`, `question`, `reference_answer`, `ground_truth_chunk_ids`, `source_locations`, `category`, `expected_behavior`, and `review_status`. Valid categories are `factual`, `conceptual`, `multi-chunk`, `figure-based`, and `off-material`.
