"""Niche tagger v2 (rules). Written on the DEV sample and FROZEN before the TEST sample was drawn.
Labels: congress, insider, earnings_result, earnings_calendar, other. Precedence: congress > insider > earnings_result > earnings_calendar.

Standard library only (Python 3.8+). tag_one(text) -> label; tag(texts) -> list of labels.
Source of truth: Growth EDA2 (topics/niche_rules.py); this copy matches it on all 23,006 clean posts."""
import re
F = re.I | re.S
POL = (r"(congress(?:man|woman|ional)?|senator|\bsen\.\s|\brep\.\s|\brepresentative\s+(?-i:[A-Z])|pelosi|tuberville|mcconnell|marjorie taylor greene|ro khanna|crenshaw|"
       r"politician|lawmaker|house member|stock act|\bptr\b|periodic transaction|capitol trades|congress trades?|\((?:h|s)\)|\b(?-i:[DR])-(?-i:[A-Z]{2})\b|trump)")
TRADE = r"(bought|buys?\b|buying|sold|sells?\b|selling|purchas\w*|disclos\w*|filed|filing|new position|\btrades?\b|\$\d+k\s*[-–]\s*\$\d+k|\$1,001|\$15,001|\$50,001|up to \$)"
C_RX = re.compile(POL + r".{0,120}?" + TRADE + "|" + TRADE + r".{0,80}?" + POL, F)
NOTPOL_RX = re.compile(r"(\bban\b|\bbill\b|legislation|should be (?:banned|illegal)|act would|representative director)", F)
ROLE = r"(ceo|cfo|coo|cto|chief \w+ officer|director|\bdir\b|chairman|chairwoman|president|founder|\bevp\b|\bsvp\b|officer|10% owner|insiders?)"
INS_ACT = r"(bought|buys|buying|purchased|purchases|purchasing|acquired|scoop\w*|picked up|sold|sells|selling|unloaded|dumped|disposed)"
I_RX = re.compile(r"\bform ?4\b|" + ROLE + r".{0,80}?" + INS_ACT + r".{0,60}?(shares|stock|\$\d)|" + INS_ACT + r".{0,40}?shares.{0,60}?" + ROLE, F)
I_GENERIC = re.compile(r"insiders? (?:buy|buying|bought|purchas\w*|sell\w*|sold|sale)", F)
I_EXCL = re.compile(r"insider (?:info|information|trading (?:scandal|probe|charges?|ban))|polymarket|kalshi|lockup|where.{0,12}form 4", F)
EARN = r"(earnings|\beps\b|revenue|sales|net income|results|quarter|\bq[1-4]\b|guidance|guide|interims)"
RESULT = (r"(beat (?:\w+ )?(?:q[1-4] )?(?:estimates|expectations|consensus)|grew (?:q[1-4] |quarterly )?(?:revenue|sales)|quarterly (?:revenue|results)|interims|"
          r"\bvs\.?\s*(?:\$|est|exp|consensus|\d)|versus (?:est|exp|consensus)|\best(?:imate)?s?\b[:.]?\s*\$|\bbeat|miss(?:ed|es)?\b|topped|came in|reported|"
          r"reports? (?:q[1-4]|third|second|first|fourth)|posted|delivered|\byoy\b|y/y|year[- ]over[- ]year|raised (?:its |full[- ]year )?(?:guidance|outlook)|cut (?:its )?(?:guidance|outlook))")
FUTURE = (r"(preview|reports? (?:tomorrow|today|tonight|this week|next week|on (?:mon|tue|wed|thu|fri)\w*|before the (?:open|bell)|after the (?:close|bell))|"
          r"on deck|ahead of|week ahead|this week|next week|expected to report|scheduled to report|scheduled|calendar|implied move|options (?:imply|price|want)|"
          r"earnings (?:this|next) (?:week|mon|tue|wed|thu|fri)|earnings season (?:starts|kicks|begins)|\bbmo\b|\bamc\b|before open|after close|most anticipated|week of)")
E_RX = re.compile(EARN, F); R_RX = re.compile(RESULT, F); FUT_RX = re.compile(FUTURE, F)
EARNWORD = re.compile(r"earnings|\beps\b|reports?\b|results|revenue|interims", F)
CASH = re.compile(r"(?<![\w$])\$[A-Za-z]{1,6}\b")

def tag_one(t: str) -> str:
    t = t or ""
    if C_RX.search(t) and not NOTPOL_RX.search(t) and re.search(r"\$[A-Za-z]{1,6}\b|stock|shares", t, re.I):
        return "congress"
    if not I_EXCL.search(t) and (I_RX.search(t) or (I_GENERIC.search(t) and CASH.search(t) and re.search(r"\$\d|\d", t))):
        return "insider"
    res = len(R_RX.findall(t)); fut = len(FUT_RX.findall(t))
    if E_RX.search(t) and EARNWORD.search(t):
        if res >= 2 and res > fut:
            return "earnings_result"
        if fut >= 1 and re.search(r"earnings|reports?|\beps\b", t, re.I):
            return "earnings_calendar"
        if res >= 1 and re.search(r"\beps\b|revenue|net income|sales|interims", t, re.I) and re.search(r"\d", t):
            return "earnings_result"
    return "other"

def tag(texts):
    return [tag_one(t) for t in texts]
