"""Labelled evaluation set for the pipeline (Phase 10).

`in_kb` = the answer is present in eval/knowledge.txt, so the system SHOULD
answer; otherwise it should refuse with a human handoff.
`language` = expected DetectedLanguage value.
`intent` = expected MessageIntent value (best-effort label; graded only when a
real LLM provider is configured).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class EvalCase:
    question: str
    language: str
    in_kb: bool
    intent: str


CASES: list[EvalCase] = [
    # --- English, answerable ---
    EvalCase("How do I check my account balance?", "en", True, "general_inquiry"),
    EvalCase("Why is my new internet package not activating?", "en", True, "technical_support"),
    EvalCase("How do I port my mobile number to ACME?", "en", True, "account_management"),
    EvalCase("What are your customer support hours?", "en", True, "general_inquiry"),
    EvalCase("How can I recharge my account?", "en", True, "general_inquiry"),
    # --- Roman Urdu, answerable ---
    EvalCase("mera account balance kaise check karun?", "roman-ur", True, "general_inquiry"),
    EvalCase("Mera internet package activate kyun nahi ho raha?", "roman-ur", True, "technical_support"),
    EvalCase("apna number ACME par port karne ka tareeqa batao", "roman-ur", True, "account_management"),
    # --- Urdu script, answerable ---
    EvalCase("میں اپنا بیلنس کیسے چیک کروں؟", "ur", True, "general_inquiry"),
    EvalCase("میرا انٹرنیٹ پیکج کیوں فعال نہیں ہو رہا؟", "ur", True, "technical_support"),
    # --- English, NOT in the KB -> must refuse ---
    EvalCase("Do you sell iPhones on monthly installments?", "en", False, "sales_inquiry"),
    EvalCase("What is the name of your company's CEO?", "en", False, "general_inquiry"),
    EvalCase("How do I activate international roaming before travelling abroad?", "en", False, "technical_support"),
    # --- Roman Urdu, NOT in the KB -> must refuse ---
    EvalCase("main apni SIM kis branch se replace karwa sakta hoon?", "roman-ur", False, "account_management"),
    EvalCase("aap ke paas WhatsApp ka koi special package hai kya?", "roman-ur", False, "sales_inquiry"),
]
