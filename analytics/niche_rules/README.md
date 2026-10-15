# Niche tagger (C9)

`niche_rules.py` labels a post's text as one of: `congress`, `insider`, `earnings_result`, `earnings_calendar`, `other`. The rules are checked in that order, and the first match wins.

- **Use:** set `content_type` in the collector from it, replacing the old Grok tags. The old `earnings_beat_miss` tag found only 14% of earnings posts, and 78 of its 173 rows were not about earnings.
- **Quality:** the rules were frozen on a dev sample before the test sample was drawn. On test, recall was 0.52-0.88 at strict precision 0.50-0.65. Treat a label as a tag, not ground truth.
- **Code:** standard library only, Python 3.8+.

```
curl -sO https://asafb2k.github.io/rapidtradeview-media/analytics/niche_rules/niche_rules.py
python -c "import niche_rules as n; print(n.tag_one('\$PLD Q3 results: EPS \$0.86 vs \$0.84 est.'))"   # earnings_result
```
