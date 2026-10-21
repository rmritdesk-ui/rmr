"""Offline, fact-conservative editorial patterns. This is not AI generation."""

import re
import unicodedata

VERSION = "editorial-2"
LOCAL_PROVIDERS = {"demonstration", "mock", "local"}


def complete_post(post, hashtags=""):
    return f"{post}\n\n{hashtags}".strip()


def x_weight(text):
    """Conservative X budget: URLs count 23; emoji sequences may overcount.

    NFC and twitter-text single-weight ranges; overcounting joined emoji is
    intentional so we never approve an oversized draft by counting codepoints.
    """
    text = unicodedata.normalize("NFC", text)
    # Only discount unambiguous ASCII-domain URLs. Ambiguous URLs are counted
    # literally (conservative), and sentence punctuation remains countable.
    pattern = r"https?://(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?::[0-9]+)?(?:[/?#][^\s]*)?"
    urls = []
    def replace(match):
        raw = match.group(0)
        url = raw.rstrip('.,!?;:)\"]}')
        if len(url) > 4096:
            return raw
        urls.append(url)
        return raw[len(url):]
    text = re.sub(pattern, replace, text)
    return 23 * len(urls) + sum(
        1 if ord(c) <= 0x10FF or 0x2000 <= ord(c) <= 0x200D
        or 0x2010 <= ord(c) <= 0x201F or 0x2032 <= ord(c) <= 0x2037 else 2
        for c in text
    )


def _brief(payload):
    raw = " ".join(payload.objective.split()).strip(" .")
    lower = raw.lower()
    kind = next((name for name, pattern in (
        ("education", r"\b(educat|tips|explain|teach)"),
        ("invitation", r"\b(invite|invitation|event|join)\b"),
        ("announcement", r"\b(announce|announcement|launch)\b"),
        ("introduction", r"\b(introduce|introduction)\b"),
    ) if re.search(pattern, lower)), "promotion")
    # Strip only recognized instruction wrappers; never infer offerings from
    # tenant purchases, keywords or demographic labels.
    topic = re.sub(r"^(?:please\s+)?(?:write|create|generate)\s+(?:(?:a|an)\s+)?(?:social media\s+)?(?:post|caption|content)\s+(?:about|to\s+promote)\s+", "", raw, flags=re.I)
    topic = re.sub(r"^(?:please\s+)?(?:promote|introduce|announce|highlight|explain|share information about|educate\s+.+?\s+about|invite\s+.+?\s+to)\s+", "", topic, flags=re.I)
    # A second directive is not part of the subject: "Promote X and encourage
    # Y" describes X. Keep noun conjunctions such as "buying and selling".
    directives = r"encourage|ask|tell|remind|persuade|include|mention|highlight|promote|explain|invite|announce|introduce|write|create|generate|emphasize|focus"
    if topic != raw:
        topic = re.split(rf"\s*(?:,\s*(?:and\s+)?|;\s*|\band\s+|\bthen\s+)(?:{directives})\b", topic, maxsplit=1, flags=re.I)[0]
    topic = topic.strip(" .")
    # Unrecognized multi-sentence instructions need human clarification, not
    # an attempted factual paraphrase. Keep the draft useful but conservative.
    uncertain = not topic or len(topic) > 180 or bool(re.search(rf"[.!?]\s|\b({directives}|make sure|use a|tone|while|so that|in order to)\b|\b(and|or|to|for|with)\s*$", topic, re.I))
    if uncertain or not topic:
        topic = "your next steps"
    return kind, topic, uncertain


# These are editorial suggestions, not claims about the advertiser. Select a
# subject only from the explicit brief, never from tenant purchases or keywords.
SUBJECTS = (
    (r"\b(home buying|homebuying|buying a home)\b", {
        "openings": (
            "Before you fall in love with a listing, think about the life you want around it.",
            "A home search can start with a conversation, not a viewing.",
            "The right questions deserve a place beside your home wish list.",
        ),
        "advice": (
            "consider the budget, location and timing together, rather than treating them as separate decisions",
            "bring questions about the buying process as well as the features you want in a home",
            "separate the things you need from the things you would simply like to have",
        ),
        "captions": (
            "Picture the everyday, not just the front door.",
            "Room for your life. A plan for your search.",
            "Save the inspiration. Write down the questions, too.",
        ),
        "context": "A property wish list is only part of a home-buying brief. Budget, location and timing also need to be considered together.",
    }),
    (r"\b(plumbing|plumber|pipe repair)\b", {
        "openings": (
            "A plumbing repair conversation starts with what you have noticed at home.",
            "Before arranging a plumbing repair, put the symptoms into words.",
            "A useful repair enquiry says more than ‘something is wrong’.",
        ),
        "advice": (
            "note where the problem is, when you noticed it and whether it has changed",
            "describe the symptoms without guessing at the cause, then ask what an assessment involves",
            "ask about the proposed work and its scope before agreeing to a repair",
        ),
        "captions": (
            "A drip, a leak, a question about a repair? Start with what you can describe.",
            "Where is it happening? When did it start? Keep those details handy.",
            "Describe the problem. Ask about the next step.",
        ),
        "context": "A repair enquiry and a diagnosis are not the same thing. Describing the symptoms gives the conversation a starting point without assuming the cause.",
    }),
    (r"\b(software|app development|web development)\b", {
        "openings": (
            "Before the feature list, define the problem your software should solve.",
            "What should people be able to do differently once the software is in place?",
            "A software brief needs priorities, not just possibilities.",
        ),
        "advice": (
            "identify the users, the task they need to complete and what a useful first version would include",
            "distinguish essential workflows from features that can wait",
            "agree on what success would look like before discussing the implementation",
        ),
        "captions": (
            "Start with the problem. Then sketch the product.",
            "One useful workflow is a better starting point than an endless wish list.",
            "From ‘we need an app’ to a brief people can work with.",
        ),
        "context": "A feature list describes what could be built; a project brief should also explain who it serves and why. Those are different conversations, and both belong in planning.",
    }),
    (r"\b(nonprofit|non-profit|volunteer|volunteers|community gathering)\b", {
        "openings": (
            "Interested in getting involved, but not sure where to begin?",
            "A conversation can be a first step towards taking part in your community.",
            "You can ask questions before deciding how to get involved.",
        ),
        "advice": (
            "ask what taking part involves and how it fits the time you can offer",
            "find out about the activities and any arrangements you need to know before attending",
            "share your interests and ask where participation would be welcome",
        ),
        "captions": (
            "Curious about taking part? There is room to start with a question.",
            "Bring your curiosity to the conversation.",
            "Make a little space to explore getting involved.",
        ),
        "context": "An invitation is more useful when people can understand what participation involves. Time commitments, activities and practical arrangements are worth clarifying before making a decision.",
    }),
    (r"\b(catering|restaurant|menus?|dining)\b", {
        "openings": (
            "Planning the menu means thinking about the people around the table.",
            "Before choosing the dishes, consider the occasion.",
            "A menu enquiry can begin with your guests, not just your favourite dish.",
        ),
        "advice": (
            "share the occasion, guest numbers and dietary requirements, then ask which options are available",
            "discuss serving arrangements alongside the menu rather than leaving them until last",
            "confirm dietary needs and ask about suitable options before making your selection",
        ),
        "captions": (
            "The occasion. The guests. Then the menu.",
            "What would suit your table? Start with the people joining it.",
            "Gather the guest details before gathering menu ideas.",
        ),
        "context": "Menu planning is also event planning. Guest numbers, dietary requirements and serving arrangements provide context for discussing dishes without assuming that every option will be available.",
    }),
)


def _writing(topic, kind, audience, formal, warm, variant):
    topic = re.sub(r"^our\s+", "", topic, flags=re.I)
    first_home = bool(re.search(r"\breal estate\b", topic, re.I) and
                      re.search(r"\bfirst[- ]time (?:home )?buyers\b", audience, re.I))
    location = ""
    if first_home:
        # Reuse only the location explicitly present in the extracted subject.
        match = re.search(r"\bin\s+([^,;.!?]+)$", topic, re.I)
        location = f" in {match.group(1)}" if match else ""
        topic = f"a first home purchase{location}"
    subject = SUBJECTS[0][1] if first_home else next((copy for pattern, copy in SUBJECTS if re.search(pattern, topic, re.I)), None)
    generic = subject is None
    if subject is None:
        subject = {
            "openings": (f"Considering {topic}? Start with the details that affect your decision.",
                         f"There is more to discuss about {topic} than a headline can cover.",
                         f"Take a closer look at {topic} before deciding on your next step."),
            "advice": ("share what you are looking for and the questions you would like answered", "explain what you need and clarify what is available",
                       "check the arrangements before making a decision"),
            "captions": (f"A closer look at {topic}.", f"Curious about {topic}?", f"Make time to explore {topic}."),
            "context": f"When considering {topic}, distinguish the information provided from the details you still need to confirm.",
        }
    advice = subject['advice'][variant]
    audience_sentence = (f"For {audience} exploring {topic}, it helps to {advice}." if audience
                         else f"When exploring {topic}, {advice}.")
    framing = {
        "education": f"A practical way to approach {topic} is to {advice}.",
        "invitation": f"If you would like to take part in {topic}, {advice}.",
        "announcement": f"Looking into {topic}? {advice[0].upper() + advice[1:]}.",
        "introduction": f"When asking about {topic}, {advice}.",
        "promotion": f"Exploring {topic}? {advice[0].upper() + advice[1:]}.",
    }[kind]
    opener = subject['openings'][variant]
    # Formal copy leads with the subject; conversational copy leads with a
    # situation. Tone changes the structure, not merely punctuation or emoji.
    if formal:
        opener = f"{topic[0].upper()+topic[1:]}: begin with the information needed to make a decision."
    fb = (
        f"{opener}\n\n{audience_sentence}",
        (f"{audience_sentence}\n\n{subject['openings'][variant]}" if formal else
         f"{audience[0].upper()+audience[1:]+', what' if audience else 'What'} would you want to know about {topic}?\n\n{advice[0].upper()+advice[1:]}."),
        f"{audience_sentence}\n\n{opener}",
    )[variant].strip()
    ig = (
        f"{subject['captions'][variant]}\n\n{framing}",
        f"{subject['captions'][variant]}\n{framing}",
        f"{subject['captions'][variant]}\n\nWhen discussing {topic}, {advice}.",
    )[variant]
    if formal:
        ig = f"{topic[0].upper()+topic[1:]}\n\n{advice[0].upper()+advice[1:]}."
    next_advice = subject['advice'][(variant + 1) % 3]
    third_person_advice = re.sub(r"\byour\b", "their", re.sub(r"\byou\b", "they", next_advice))
    practical = (f"In a conversation about {topic}, {audience} can {third_person_advice}." if audience
                 else f"When discussing {topic}, {next_advice}.")
    li = (
        f"{subject['context']}\n\n{practical}",
        f"{topic[0].upper()+topic[1:]}: start with the decision, not just the options.\n\n{audience_sentence}\n\n{subject['context']}",
        f"{practical}\n\n{subject['openings'][variant]}",
    )[variant]
    short = (f"{topic[0].upper()+topic[1:]}: {advice}.",
             f"Exploring {topic}? {advice[0].upper()+advice[1:]}.",
             f"Questions about {topic}? {advice[0].upper()+advice[1:]}.")[variant]
    if generic:
        short = (f"Have questions about {topic}? Tell us what you would like to know.",
                 f"Let's talk about {topic}. Share what you are looking for.",
                 f"Considering {topic}? Bring your questions to the conversation.")[variant]
    if first_home:
        short = (f"Buying your first home{location}? Tell us what you're looking for, and let's start the conversation.",
                 f"Planning your first home purchase{location}? Bring your questions about the buying process.",
                 f"What would you like to know before buying your first home{location}? Let's talk about your plans.")[variant]
        if formal:
            short = short.replace("Tell us what you're looking for, and let's start the conversation.",
                                  "Discuss your requirements and questions about the buying process.")
    return fb, ig, li, short


def generate(payload, variant=0):
    kind, topic, uncertain = _brief(payload)
    variant = int(variant) % 3
    tone = payload.tone.lower()
    formal = bool(re.search(r"professional|formal|business", tone))
    warm = bool(re.search(r"warm|friendly|conversational|approachable|playful|enthusiastic", tone))
    emoji = warm and not formal and not re.search(r"no emoji|without emoji", tone)
    audience = " ".join(payload.audience.split()).strip(" .")
    if audience.lower() in {"", "the intended audience"}:
        match = re.search(r"\bencourage\s+(.+?)\s+to\s+(?:contact|call|reach out)\b", payload.objective, re.I)
        if match:
            audience = match.group(1).strip()
    if len(audience) > 100 or re.search(r"[.!?]\s", audience):
        audience = ""
    cta = payload.call_to_action.strip() or "Get in touch to discuss your questions."
    fb, ig, li, short = _writing(topic, kind, audience, formal, warm, variant)
    fb = f"{fb}\n\n{cta}"
    ig = f"{'✨ ' if emoji else ''}{ig}\n\n{cta}"
    li = f"{li}\n\n{cta}"
    short = f"{short} {cta}"
    hooks = ("Discuss the details before deciding", "Start with a clear brief", "Bring your questions to the conversation")
    tags = []
    for keyword in payload.keywords[:20]:
        tag = "#" + re.sub(r"[^\w]", "", keyword.strip().lstrip("#"), flags=re.UNICODE)
        if len(tag) > 1 and len(tag) <= 40 and tag.lower() not in {x.lower() for x in tags}:
            tags.append(tag)
    result = {}
    for platform, post, count in (("facebook", fb, 2), ("instagram", ig, 6), ("linkedin", li, 3),
                                  ("x", short, 2)):
        hashtags = " ".join(tags[:count])
        effective_cta = cta
        warning = "Review the brief: complex instructions need a more specific topic." if uncertain else ""
        if platform == "x":
            if x_weight(complete_post(post, hashtags)) > 280:
                hashtags = ""
            if x_weight(post) > 280:
                post = f"Explore {topic}. {cta}"
            if x_weight(post) > 280:
                post = f"{hooks[variant].rstrip('.?!')}. {cta}"
                warning = "The topic is too long for this X draft; review the concise version before publishing."
            if x_weight(post) > 280:
                effective_cta = "Get in touch to discuss your questions."
                post = f"{hooks[variant].rstrip('.?!')}. {effective_cta}"
                warning = "The supplied CTA is too long for X; review the shorter draft CTA."
        hook = post.split('\n', 1)[0]
        result[platform] = {"title": hook, "hook": hook, "post": post, "hashtags": hashtags,
                            "cta": effective_cta, "keywords": payload.keywords, "suggested_visual": payload.suggested_visual,
                            "editorial": {"generator_version": VERSION, "variant": variant,
                                          "requested_cta": payload.call_to_action,
                                          "objective_type": kind, "review_note": warning}}
    return result
