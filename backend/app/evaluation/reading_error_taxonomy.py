"""Versioned vocabulary for tentative IELTS Reading diagnostic hypotheses.

Categories describe possible explanations, not observations or diagnoses.
"""

TAXONOMY_VERSION = "reading-error-dna-v1"

READING_ERROR_CATEGORIES = {
    "passage_location": "原文定位错误",
    "paraphrase_recognition": "同义替换识别不足",
    "vocabulary_meaning": "词汇与句意理解错误",
    "true_false_not_given": "True / False / Not Given 混淆",
    "yes_no_not_given": "Yes / No / Not Given 混淆",
    "over_inference": "过度推断",
    "qualifier_scope": "条件、范围和限定词遗漏",
    "question_instruction": "题目要求理解错误",
    "insufficient_evidence": "证据不足，暂时无法判断",
}
