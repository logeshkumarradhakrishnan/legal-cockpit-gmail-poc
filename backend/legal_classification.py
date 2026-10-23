"""Rule sets transcribed from the Legal Email Classification document.

The stakeholder list intentionally contains organization names, not email domains:
the source document says domains still need to be collected from stakeholders.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).casefold()


def contains(term: str, text: str) -> bool:
    term = normalize(term)
    if term.isascii() and re.fullmatch(r"[a-z0-9][a-z0-9 .&/-]*", term):
        # Phrase-aware boundaries avoid matching short terms inside unrelated words.
        return re.search(rf"(?<![\w]){re.escape(term)}(?![\w])", text, flags=re.I) is not None
    return term in text


# Category labels and keyword sets from section 3 of pasted.txt.
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Contract Management, Legal Review Required": (
        "contract", "agreement", "MSA", "master service agreement", "SOW", "statement of work",
        "amendment", "addendum", "legal review", "terms and conditions", "NDA",
        "non-disclosure agreement", "vendor agreement", "partnership agreement", "procurement contract",
        "renewal", "execution copy", "signature required", "breach of contract", "termination notice",
        "default notice", "indemnity claim", "force majeure", "SLA breach", "liquidated damages",
        "bank guarantee", "encashment", "invoke the guarantee", "performance guarantee", "blacklist",
        "debarment", "vendor default", "non-performance", "deficiency in service", "contract expiry",
        "breach notice", "rectify within", "termination for cause", "termination for convenience",
        "dispute resolution clause", "escalation matrix",
    ),
    "Litigation, High Legal Risk": (
        "lawsuit", "litigation", "legal notice", "court order", "dispute", "arbitration", "settlement",
        "claim", "damages", "indemnification", "breach", "notice of default", "subpoena", "hearing",
        "notice under section", "summons", "hereby served", "without prejudice", "cause of action",
        "suit filed", "plaint", "written statement", "arbitral tribunal", "injunction", "stay order",
        "writ petition", "public interest litigation", "PIL", "advocate", "on behalf of our client",
        "learned counsel", "hon'ble court", "hon'ble tribunal", "case no.", "petition no.", "order dated",
        "next date of hearing", "listed for hearing",
    ),
    "Compliance & Regulatory": (
        "compliance", "regulatory", "audit", "policy violation", "SOX", "GDPR", "DPDPA", "HIPAA",
        "PCI-DSS", "ISO 27001", "investigation", "non-compliance", "compliance review", "risk assessment",
        "circular no.", "CAR", "civil aviation requirement", "advisory no.", "compliance report",
        "statutory compliance", "mandatory compliance", "in exercise of powers conferred", "notification no.",
        "gazette notification", "amendment to", "regulation", "guideline", "directive", "F.No.",
        "show cause", "why action should not be taken", "explain within", "penalty", "fine imposed",
        "violation of", "warning notice", "cease and desist", "punitive action", "suspension of license",
        "revocation", "draft regulation", "invites comments", "public consultation", "stakeholder consultation",
        "comments are invited on",
    ),
    "Intellectual Property": ("patent", "trademark", "copyright", "intellectual property", "IP infringement",
        "licensing", "trade secret", "proprietary information", "source code ownership"),
    "Employment Legal": ("termination", "disciplinary action", "grievance", "harassment complaint",
        "workplace investigation", "labor law", "employment contract", "severance", "whistleblower", "equal opportunity"),
    "Privacy & Data Protection": ("personal data", "PII", "sensitive personal information", "data breach",
        "privacy notice", "consent", "confidential", "restricted", "internal only", "data protection", "data subject request"),
    "Corporate Legal": ("merger", "acquisition", "due diligence", "shareholder", "board resolution",
        "corporate governance", "investment", "joint venture", "transaction"),
    "Attorney-Client Privileged": ("attorney", "counsel", "law firm", "advocate", "privileged",
        "attorney-client privilege", "legal opinion", "outside counsel"),
    "Tax & Statutory Demand": ("assessment order", "demand notice", "tax notice", "GST notice", "income tax",
        "TDS", "show cause under section", "recovery notice", "attachment notice", "intimation under section"),
    "Licensing & Regulatory Clearance": ("license renewal", "permit expiry", "NOC", "no objection certificate",
        "certificate of registration", "authorization", "registration renewal", "clearance", "consent to operate", "consent to establish"),
    "RTI / Statutory Disclosure": ("right to information", "RTI application", "information sought under", "section 6(1)", "section 7"),
    "Environmental Compliance": ("environmental clearance", "EIA", "pollution control", "green tribunal", "NGT", "emission", "effluent"),
    "Land & Property Legal": ("land acquisition", "encroachment", "lease deed", "eviction", "property dispute", "khata", "revenue records", "mutation"),
    "International Aviation & Regulatory": ("ICAO", "IATA", "IOSA", "USOAP", "Annex 17", "Annex 19", "state letter", "ACI",
        "ACI Asia-Pacific", "SARPs", "standard and recommended practice", "international obligation", "bilateral air services agreement",
        "IATA Clearing House", "IATA dispute", "WHO", "international health regulations", "corrective action plan", "audit finding"),
    "Media & Reputational Risk": ("seeking your response", "for publication", "going to press", "deadline for comment", "right to reply",
        "on the record", "off the record", "investigative story", "sources indicate", "allegations against", "defamatory", "retraction",
        "demand a correction", "sub judice", "press statement required", "media query", "journalist", "exclusive story"),
    "Passenger Legal Risk": ("injured", "injury", "fell", "slipped", "fracture", "hospitalized", "medical negligence", "wheelchair accident",
        "escalator accident", "allergic reaction", "died", "death", "medical emergency not attended", "disability", "discrimination",
        "denied boarding due to", "refused wheelchair", "RPwD Act", "rights of persons with disabilities", "reduced mobility",
        "denied assistance", "humiliated", "racial", "religious", "gender-based", "legal action", "will sue", "consumer court",
        "consumer forum", "file a case", "lawyer", "compensation claim", "defamation", "human rights commission", "national commission",
        "district commission", "lost baggage worth", "stolen from checked baggage", "denied boarding compensation",
        "flight cancellation compensation", "theft", "security lapse", "privacy violation", "CCTV footage request", "posted on twitter",
        "viral", "media", "press", "going public", "social media"),
}

# The source says any personal-matter match is excluded. POSH is listed as
# "POSH – related", so keep that phrase-specific rather than excluding every POSH complaint.
PERSONAL_EXCLUSIONS = (
    "home loan", "mortgage", "refinance", "personal loan", "my mortgage", "loan officer", "escrow account",
    "personal tax return", "personal taxes", "1040", "irs personal", "family matter", "personal banking",
    "credit card statement", "personal insurance policy", "life insurance quote", "car loan", "auto loan",
    "personal injury (self)", "posh-related", "posh related", "posh – related",
)
NEGATIVE_EXCLUSIONS = ("webinar", "training program", "newsletter", "unsubscribe", "save the date",
                       "conference invitation", "certificate of appreciation")
URGENCY_KEYWORDS = ("urgent", "immediate action required", "within 7 days", "within 15 days", "within 30 days",
                    "final notice", "last opportunity", "reminder", "failure to respond")
LEGACY_LEGAL_KEYWORDS = ("legal notice", "termination", "breach", "liquidated damages", "indemnity", "arbitration", "summons", "subpoena", "regulatory", "non-compliance", "cease and desist", "data breach", "penalty", "litigation", "dispute", "कानूनी नोटिस", "अनुबंध", "मुकदमा", "समझौता", "ಕಾನೂನು ಸೂಚನೆ", "ಒಪ್ಪಂದ", "ದಾವೆ")
SENSITIVE_KEYWORDS = ("posh", "sexual harassment", "whistleblower", "whistle-blower", "retaliation",
                      "protected disclosure", "यौन उत्पीड़न")

# Names only, because the source explicitly says stakeholder domains are still to be collected.
STAKEHOLDER_NAMES = {
    "DGCA": ("DGCA", "Directorate General of Civil Aviation"),
    "BCAS": ("BCAS", "Bureau of Civil Aviation Security"),
    "AAI": ("Airports Authority of India",), "AERA": ("AERA", "Airports Economic Regulatory Authority"),
    "TDSAT": ("TDSAT",), "MoCA": ("Ministry of Civil Aviation", "MoCA"),
    "APHO": ("Airport Health Organization", "APHO"), "ICAO": ("ICAO", "International Civil Aviation Organization"),
    "IATA": ("IATA", "International Air Transport Association"), "ACI": ("Airports Council International", "ACI Asia-Pacific"),
    "WHO": ("WHO", "World Health Organization"), "WCO": ("WCO", "World Customs Organization"),
    "Income Tax Department": ("Income Tax Department",), "CBIC/GST": ("CBIC", "GST authorities"),
    "MCA/ROC": ("Ministry of Corporate Affairs", "Registrar of Companies", "MCA", "ROC"),
    "CCI": ("Competition Commission of India", "CCI"), "DRI": ("Directorate of Revenue Intelligence", "DRI"),
    "PESO": ("PESO",), "FSSAI": ("FSSAI",), "MoEFCC": ("MoEFCC", "Ministry of Environment"),
    "NGT": ("National Green Tribunal", "NGT"), "KSPCB": ("KSPCB",), "KIADB": ("KIADB",),
    "BESCOM": ("BESCOM",), "Karnataka Labour Department": ("Karnataka Labour Department",),
    "Karnataka High Court": ("High Court of Karnataka",), "NCLT": ("NCLT",),
}


def analyze(email) -> dict:
    text = normalize("\n".join([email.subject, email.sender, email.body] + [a.text or "" for a in email.attachments]))
    personal = [k for k in PERSONAL_EXCLUSIONS if contains(k, text)]
    negative = [k for k in NEGATIVE_EXCLUSIONS if contains(k, text)]
    category_matches = {category: [k for k in keywords if contains(k, text)]
                        for category, keywords in CATEGORY_KEYWORDS.items()}
    category_matches = {c: hits for c, hits in category_matches.items() if hits}
    urgency = [k for k in URGENCY_KEYWORDS if contains(k, text)]
    sensitive = [k for k in SENSITIVE_KEYWORDS if contains(k, text)]
    stakeholder = [name for name, aliases in STAKEHOLDER_NAMES.items()
                   if any(contains(alias, normalize(email.sender)) for alias in aliases)]
    # Prioritize formal litigation and regulator notices; otherwise use the category with most keyword hits.
    order = ["Litigation, High Legal Risk", "Tax & Statutory Demand", "Compliance & Regulatory",
             "International Aviation & Regulatory", "Passenger Legal Risk", "Contract Management, Legal Review Required"]
    # Best fit is primarily driven by the number of category-specific signals;
    # the explicit high-risk ordering breaks ties rather than overriding stronger evidence.
    ranked = sorted(category_matches, key=lambda c: (-len(category_matches[c]),
                                                       order.index(c) if c in order else 99, c))
    legacy = [k for k in LEGACY_LEGAL_KEYWORDS if contains(k, text)]
    return {"personal_exclusions": personal, "negative_exclusions": negative,
            "category_matches": category_matches, "legacy_legal_matches": legacy,
            "suggested_category": ranked[0] if ranked else ("General legal" if legacy else None),
            "urgency_matches": urgency, "sensitive_matches": sensitive, "stakeholder_matches": stakeholder}
