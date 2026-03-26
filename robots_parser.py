"""
robots_parser.py — Research-grade robots.txt parser and rule evaluator.

Implements the core RFC 9309 semantics used in this project:
  - User-agent group parsing with correct specificity (specific > wildcard)
  - Longest-prefix-match with allow-wins-on-tie
  - Multi-group merging for the same bot

Limitations (not needed for current treatment variable, may be added later):
  - Does NOT support RFC 9309 special pattern characters (* and $)
  - Does NOT support percent-encoding normalization
  These would matter for fine-grained path-level analysis (Step 4 sitemap intensity)
  but not for root-block / has-nonroot-disallow classification.

Standalone module: no HTTP, no pandas, no I/O.
"""


def parse_robots(content: str) -> list:
    """Parse robots.txt content into a list of groups.

    Each group is a dict:
        {"agents": ["gptbot", "claudebot"], "rules": [("disallow", "/"), ("allow", "/public")]}

    - Agent names are lowercased.
    - Directive names are lowercased ("allow" / "disallow").
    - Consecutive User-agent lines before any rules form one group.
    - A blank line or a new User-agent line after rules closes the current group.
    """
    groups = []
    current_agents = []
    current_rules = []
    has_rules = False  # whether we've seen Allow/Disallow in the current group

    for raw_line in content.splitlines():
        # Strip inline comments
        comment_idx = raw_line.find("#")
        if comment_idx != -1:
            line = raw_line[:comment_idx]
        else:
            line = raw_line
        line = line.strip()

        # Blank line closes the current group
        if not line:
            if current_agents:
                groups.append({"agents": current_agents, "rules": current_rules})
                current_agents = []
                current_rules = []
                has_rules = False
            continue

        # Parse directive: field
        colon_idx = line.find(":")
        if colon_idx == -1:
            continue  # skip unparseable lines

        field = line[:colon_idx].strip().lower()
        value = line[colon_idx + 1:].strip()

        if field == "user-agent":
            if has_rules:
                # New user-agent after rules -> close current group, start new one
                if current_agents:
                    groups.append({"agents": current_agents, "rules": current_rules})
                current_agents = [value.lower()]
                current_rules = []
                has_rules = False
            else:
                # Consecutive user-agent line -> same group
                current_agents.append(value.lower())

        elif field in ("disallow", "allow"):
            has_rules = True
            current_rules.append((field, value))

        # Other directives (Sitemap, Crawl-delay, etc.) are ignored

    # Close final group if any
    if current_agents:
        groups.append({"agents": current_agents, "rules": current_rules})

    return groups


def get_applicable_rules(groups: list, bot_aliases: list) -> tuple:
    """Get the effective rules for a bot, merging ALL matching groups.

    Args:
        groups: Output of parse_robots().
        bot_aliases: List of lowercase aliases for the bot (e.g., ["gptbot"]).

    Returns:
        (rules, has_specific_rule, effective_source)
        - rules: list of (directive, path) tuples
        - has_specific_rule: bool
        - effective_source: "specific" | "wildcard" | "none"
    """
    bot_aliases_set = set(bot_aliases)

    # Collect rules from all specific-matching groups
    specific_rules = []
    found_specific_group = False
    for group in groups:
        if bot_aliases_set & set(group["agents"]):
            found_specific_group = True
            specific_rules.extend(group["rules"])

    if found_specific_group:
        return (specific_rules, True, "specific")

    # Fall back: collect rules from all wildcard groups
    wildcard_rules = []
    found_wildcard_group = False
    for group in groups:
        if "*" in group["agents"]:
            found_wildcard_group = True
            wildcard_rules.extend(group["rules"])

    if found_wildcard_group:
        return (wildcard_rules, False, "wildcard")

    return ([], False, "none")


def is_path_blocked(rules: list, path: str = "/") -> bool:
    """Determine if a path is blocked per RFC 9309 longest-match-wins.

    - Prefix-match each rule's path against target path.
    - Longest matching path wins.
    - On tie (same length), Allow beats Disallow.

    Args:
        rules: list of (directive, rule_path) tuples.
        path: the path to check (default "/").

    Returns:
        True if the path is effectively disallowed.
    """
    if not rules:
        return False

    best_length = -1
    best_is_block = False

    for directive, rule_path in rules:
        # Empty Disallow: means allow all
        if directive == "disallow" and rule_path == "":
            continue

        # Empty Allow: is meaningless, skip
        if directive == "allow" and rule_path == "":
            continue

        # RFC 9309: a rule matches if rule_path is a prefix of the target path.
        if not path.startswith(rule_path):
            continue

        match_length = len(rule_path)

        if match_length > best_length:
            best_length = match_length
            best_is_block = (directive == "disallow")
        elif match_length == best_length:
            # Tie: Allow wins
            if directive == "allow":
                best_is_block = False

    return best_is_block


def classify_bot(groups: list, bot_name: str, bot_aliases: list) -> dict:
    """Classify a single bot's access based on parsed robots.txt groups.

    Args:
        groups: Output of parse_robots().
        bot_name: Canonical bot name (e.g., "GPTBot").
        bot_aliases: Lowercase aliases (e.g., ["gptbot"]).

    Returns:
        dict with keys:
            specific_rule: 0|1
            effective_source: "specific"|"wildcard"|"none"
            root_block: 0|1
            has_nonroot_disallow: 0|1
    """
    rules, has_specific, source = get_applicable_rules(groups, bot_aliases)

    root_block = 1 if is_path_blocked(rules, "/") else 0

    # has_nonroot_disallow: heuristic — any Disallow with non-empty, non-root path
    has_nonroot_disallow = 0
    for directive, rule_path in rules:
        if directive == "disallow" and rule_path not in ("", "/"):
            has_nonroot_disallow = 1
            break

    return {
        "specific_rule": 1 if has_specific else 0,
        "effective_source": source,
        "root_block": root_block,
        "has_nonroot_disallow": has_nonroot_disallow,
    }
