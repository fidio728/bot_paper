"""
test_robots_parser.py — Unit tests for robots_parser.py (12 cases).
"""

import sys
import os

# Ensure the module is importable from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from robots_parser import parse_robots, get_applicable_rules, is_path_blocked, classify_bot, extract_sitemap_urls


def test_01_wildcard_disallow_root():
    """Only User-agent: * with Disallow: / -> all bots blocked at root."""
    content = """\
User-agent: *
Disallow: /
"""
    groups = parse_robots(content)
    result = classify_bot(groups, "GPTBot", ["gptbot"])
    assert result["root_block"] == 1
    assert result["effective_source"] == "wildcard"
    assert result["specific_rule"] == 0


def test_02_specific_wins_over_wildcard():
    """Specific bot rules override wildcard entirely."""
    content = """\
User-agent: *
Disallow: /

User-agent: GPTBot
Disallow: /private
"""
    groups = parse_robots(content)
    result = classify_bot(groups, "GPTBot", ["gptbot"])
    # GPTBot has specific rules: only /private is blocked, not root
    assert result["root_block"] == 0
    assert result["specific_rule"] == 1
    assert result["effective_source"] == "specific"
    assert result["has_nonroot_disallow"] == 1

    # ClaudeBot falls back to wildcard: root blocked
    result2 = classify_bot(groups, "ClaudeBot", ["claudebot"])
    assert result2["root_block"] == 1
    assert result2["effective_source"] == "wildcard"


def test_03_allow_wins_on_tie_walmart_fix():
    """Allow: / vs Disallow: / same length -> Allow wins (Walmart bug fix)."""
    content = """\
User-agent: GPTBot
Disallow: /
Allow: /
"""
    groups = parse_robots(content)
    result = classify_bot(groups, "GPTBot", ["gptbot"])
    assert result["root_block"] == 0, "Allow: / should beat Disallow: / on tie"


def test_04_longer_allow_wins():
    """Allow: /public/ vs Disallow: / -> /public/page is allowed."""
    content = """\
User-agent: *
Disallow: /
Allow: /public/
"""
    groups = parse_robots(content)
    rules, _, _ = get_applicable_rules(groups, ["gptbot"])
    # Root is still blocked
    assert is_path_blocked(rules, "/") is True
    # But /public/page is allowed (longer match)
    assert is_path_blocked(rules, "/public/page") is False
    assert is_path_blocked(rules, "/public/") is False
    # /private is blocked
    assert is_path_blocked(rules, "/private/page") is True


def test_05_specific_bot_no_rules():
    """Specific bot listed but no rules -> allowed (empty rules = allow)."""
    content = """\
User-agent: GPTBot

User-agent: *
Disallow: /
"""
    groups = parse_robots(content)
    result = classify_bot(groups, "GPTBot", ["gptbot"])
    # GPTBot has a specific group but no rules -> everything allowed
    assert result["root_block"] == 0
    assert result["specific_rule"] == 1
    assert result["effective_source"] == "specific"


def test_06_empty_disallow():
    """Empty Disallow: means allow all."""
    content = """\
User-agent: *
Disallow:
"""
    groups = parse_robots(content)
    result = classify_bot(groups, "GPTBot", ["gptbot"])
    assert result["root_block"] == 0
    assert result["has_nonroot_disallow"] == 0


def test_07_case_insensitive():
    """Case insensitive: user-agent: GPTBOT matches GPTBot."""
    content = """\
user-agent: GPTBOT
disallow: /
"""
    groups = parse_robots(content)
    result = classify_bot(groups, "GPTBot", ["gptbot"])
    assert result["root_block"] == 1
    assert result["specific_rule"] == 1
    assert result["effective_source"] == "specific"


def test_08_multiple_groups_blank_line():
    """Multiple groups separated by blank lines."""
    content = """\
User-agent: GPTBot
Disallow: /

User-agent: ClaudeBot
Disallow: /private

User-agent: *
Allow: /
"""
    groups = parse_robots(content)
    assert len(groups) == 3

    gpt = classify_bot(groups, "GPTBot", ["gptbot"])
    assert gpt["root_block"] == 1

    claude = classify_bot(groups, "ClaudeBot", ["claudebot"])
    assert claude["root_block"] == 0
    assert claude["has_nonroot_disallow"] == 1

    # Unknown bot falls back to wildcard
    other = classify_bot(groups, "SomeBot", ["somebot"])
    assert other["root_block"] == 0
    assert other["effective_source"] == "wildcard"


def test_09_no_matching_agent_no_wildcard():
    """No matching agent and no wildcard -> allowed."""
    content = """\
User-agent: GPTBot
Disallow: /
"""
    groups = parse_robots(content)
    result = classify_bot(groups, "ClaudeBot", ["claudebot"])
    assert result["root_block"] == 0
    assert result["effective_source"] == "none"
    assert result["specific_rule"] == 0


def test_10_walmart_realistic():
    """Real-world Walmart-style robots.txt with Allow overriding Disallow."""
    content = """\
User-agent: *
Disallow: /search
Disallow: /account
Allow: /

User-agent: GPTBot
Disallow: /

User-agent: ClaudeBot
Disallow: /

User-agent: Google-Extended
Disallow: /

User-agent: CCBot
Disallow: /
"""
    groups = parse_robots(content)

    # Wildcard: has non-root disallows but root is NOT blocked
    # because Allow: / ties with implicit default and specific paths block /search, /account
    wildcard_rules, _, _ = get_applicable_rules(groups, ["perplexitybot"])
    assert is_path_blocked(wildcard_rules, "/") is False
    assert is_path_blocked(wildcard_rules, "/search") is True
    assert is_path_blocked(wildcard_rules, "/account/settings") is True

    # GPTBot: specific, root blocked
    gpt = classify_bot(groups, "GPTBot", ["gptbot"])
    assert gpt["root_block"] == 1
    assert gpt["specific_rule"] == 1

    # ClaudeBot: specific, root blocked
    claude = classify_bot(groups, "ClaudeBot", ["claudebot"])
    assert claude["root_block"] == 1

    # PerplexityBot: falls back to wildcard, root NOT blocked
    perp = classify_bot(groups, "PerplexityBot", ["perplexitybot"])
    assert perp["root_block"] == 0
    assert perp["effective_source"] == "wildcard"


def test_11_same_bot_multiple_specific_groups_merged():
    """Same bot in multiple specific groups -> rules must be merged."""
    content = """\
User-agent: GPTBot
Disallow: /private

User-agent: GPTBot
Allow: /public
Disallow: /secret
"""
    groups = parse_robots(content)
    rules, has_specific, source = get_applicable_rules(groups, ["gptbot"])
    assert has_specific is True
    assert source == "specific"
    # Should have 3 rules merged from both groups
    assert len(rules) == 3
    assert ("disallow", "/private") in rules
    assert ("allow", "/public") in rules
    assert ("disallow", "/secret") in rules

    # Root is not blocked (no Disallow: /)
    assert is_path_blocked(rules, "/") is False
    # /private is blocked
    assert is_path_blocked(rules, "/private/stuff") is True
    # /public is allowed
    assert is_path_blocked(rules, "/public/page") is False
    # /secret is blocked
    assert is_path_blocked(rules, "/secret/doc") is True


def test_12_multiple_wildcard_groups_merged():
    """Multiple wildcard groups -> rules must be merged."""
    content = """\
User-agent: *
Disallow: /tmp

User-agent: *
Disallow: /cache
Allow: /public
"""
    groups = parse_robots(content)
    rules, has_specific, source = get_applicable_rules(groups, ["somebot"])
    assert has_specific is False
    assert source == "wildcard"
    # Should have 3 rules merged from both wildcard groups
    assert len(rules) == 3
    assert ("disallow", "/tmp") in rules
    assert ("disallow", "/cache") in rules
    assert ("allow", "/public") in rules

    assert is_path_blocked(rules, "/tmp/file") is True
    assert is_path_blocked(rules, "/cache/data") is True
    assert is_path_blocked(rules, "/public/page") is False
    assert is_path_blocked(rules, "/other") is False


def test_13_wildcard_empty_group_still_wildcard():
    """Wildcard group with no rules -> effective_source must be 'wildcard', not 'none'.
    RFC 9309: empty group implicitly allows everything."""
    content = """\
User-agent: *

User-agent: GPTBot
Disallow: /
"""
    groups = parse_robots(content)
    # SomeBot has no specific group, falls back to wildcard (which has no rules)
    result = classify_bot(groups, "SomeBot", ["somebot"])
    assert result["effective_source"] == "wildcard", \
        f"Expected 'wildcard' but got '{result['effective_source']}'"
    assert result["root_block"] == 0  # empty rules = allow all
    assert result["specific_rule"] == 0

    # GPTBot still gets its specific rules
    gpt = classify_bot(groups, "GPTBot", ["gptbot"])
    assert gpt["effective_source"] == "specific"
    assert gpt["root_block"] == 1


def test_14_wildcard_star():
    """RFC 9309 * wildcard: /*.gif blocks .gif files; /private* blocks /private prefix."""
    rules_gif = [("disallow", "/*.gif")]
    assert is_path_blocked(rules_gif, "/image.gif") is True
    assert is_path_blocked(rules_gif, "/dir/photo.gif") is True
    assert is_path_blocked(rules_gif, "/image.png") is False
    assert is_path_blocked(rules_gif, "/image.gif.txt") is True  # still contains /*.gif match

    rules_priv = [("disallow", "/private*")]
    assert is_path_blocked(rules_priv, "/private/subfolder") is True
    assert is_path_blocked(rules_priv, "/privatecontent") is True
    assert is_path_blocked(rules_priv, "/public") is False
    assert is_path_blocked(rules_priv, "/") is False


def test_15_dollar_end_anchor():
    """RFC 9309 $ end anchor: /private/$ blocks exact /private/ but not deeper paths."""
    rules = [("disallow", "/private/$")]
    assert is_path_blocked(rules, "/private/") is True
    assert is_path_blocked(rules, "/private/subfolder") is False
    assert is_path_blocked(rules, "/private/subfolder/page") is False
    assert is_path_blocked(rules, "/private") is False  # no trailing slash


def test_16_star_and_dollar():
    """Combined * and $: /*.pdf$ blocks .pdf files exactly (not .pdf.bak etc.)."""
    rules = [("disallow", "/*.pdf$")]
    assert is_path_blocked(rules, "/report.pdf") is True
    assert is_path_blocked(rules, "/dir/report.pdf") is True
    assert is_path_blocked(rules, "/report.pdf.bak") is False  # $ anchors at end
    assert is_path_blocked(rules, "/report.txt") is False


def test_17_extract_sitemap_urls():
    """extract_sitemap_urls returns correct URLs; handles comments, case, non-sitemap lines."""
    content = """\
User-agent: *
Disallow: /

Sitemap: https://example.com/sitemap.xml
sitemap: https://example.com/sitemap2.xml  # inline comment
Sitemap:   https://example.com/sitemap3.xml
Crawl-delay: 10
"""
    urls = extract_sitemap_urls(content)
    assert len(urls) == 3
    assert "https://example.com/sitemap.xml" in urls
    assert "https://example.com/sitemap2.xml" in urls
    assert "https://example.com/sitemap3.xml" in urls
    # Inline comment stripped
    assert all("inline comment" not in u for u in urls)
    # Non-sitemap lines not included
    assert not any("Disallow" in u or "User-agent" in u or "Crawl" in u for u in urls)


def test_18_wildcard_blocks_root():
    """Disallow: /* should block / (validates Step 3 re-scan rationale)."""
    rules = [("disallow", "/*")]
    assert is_path_blocked(rules, "/") is True
    assert is_path_blocked(rules, "/abc") is True
    assert is_path_blocked(rules, "/abc/def") is True

    # Also via classify_bot
    content = """\
User-agent: GPTBot
Disallow: /*
"""
    groups = parse_robots(content)
    result = classify_bot(groups, "GPTBot", ["gptbot"])
    assert result["root_block"] == 1, "Disallow: /* must block root /"


def test_19_percent_encoding():
    """Unreserved chars decoded before match; reserved chars stay encoded."""
    # %7E is ~ (tilde), an unreserved char — should be equivalent
    rules_tilde = [("disallow", "/%7Eprivate/")]
    assert is_path_blocked(rules_tilde, "/~private/page") is True
    assert is_path_blocked(rules_tilde, "/~private/") is True

    # Reverse: rule uses literal ~, path uses %7E encoding
    rules_literal = [("disallow", "/~private/")]
    assert is_path_blocked(rules_literal, "/%7Eprivate/page") is True

    # %2F is / (forward slash), a RESERVED char — must NOT be decoded
    # Rule /public%2Fpage should NOT match /public/page
    rules_reserved = [("disallow", "/public%2Fpage")]
    assert is_path_blocked(rules_reserved, "/public/page") is False
    # But it should match the literal percent-encoded path
    assert is_path_blocked(rules_reserved, "/public%2Fpage") is True


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_all_tests():
    tests = [
        test_01_wildcard_disallow_root,
        test_02_specific_wins_over_wildcard,
        test_03_allow_wins_on_tie_walmart_fix,
        test_04_longer_allow_wins,
        test_05_specific_bot_no_rules,
        test_06_empty_disallow,
        test_07_case_insensitive,
        test_08_multiple_groups_blank_line,
        test_09_no_matching_agent_no_wildcard,
        test_10_walmart_realistic,
        test_11_same_bot_multiple_specific_groups_merged,
        test_12_multiple_wildcard_groups_merged,
        test_13_wildcard_empty_group_still_wildcard,
        test_14_wildcard_star,
        test_15_dollar_end_anchor,
        test_16_star_and_dollar,
        test_17_extract_sitemap_urls,
        test_18_wildcard_blocks_root,
        test_19_percent_encoding,
    ]
    passed = 0
    failed = 0
    for test_fn in tests:
        name = test_fn.__name__
        try:
            test_fn()
            print(f"  PASS  {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{passed}/{passed + failed} tests passed.")
    if failed:
        print(f"{failed} test(s) FAILED.")
        sys.exit(1)
    else:
        print("All tests passed.")


if __name__ == "__main__":
    run_all_tests()
