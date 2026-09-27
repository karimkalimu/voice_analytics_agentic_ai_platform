import json


OPTIONS = ("rms", "count_nouns", "count_adjectives", "sentiment", "topic_mentions")


def validate_layer2_options(options):
    if (not isinstance(options, list) or len(options) > len(OPTIONS)
            or any(not isinstance(option, str) or option not in OPTIONS for option in options)
            or len(set(options)) != len(options)):
        raise ValueError("Invalid layer2 options")
    return options


def parse_layer2_options(metadata: dict[str, str]):
    if "layer2_options" not in metadata:
        return []
    try:
        options = json.loads(metadata["layer2_options"])
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid layer2_options metadata") from exc
    return validate_layer2_options(options)


def validate_layer2_config(config, options: list[str]):
    if (not isinstance(config, dict) or set(config) - {"count_nouns", "topic_mentions"}
            or set(config) - set(options)):
        raise ValueError("Invalid Layer 2 configuration")
    result = {}
    if "count_nouns" in options:
        noun_config = config.get("count_nouns", {})
        if (not isinstance(noun_config, dict) or set(noun_config) - {"unique_only"}
                or not isinstance(noun_config.get("unique_only", False), bool)):
            raise ValueError("Invalid Layer 2 configuration")
        result["count_nouns"] = {"unique_only": noun_config.get("unique_only", False)}
    if "topic_mentions" in options:
        topic_config = config.get("topic_mentions")
        if (not isinstance(topic_config, dict) or set(topic_config) != {"topic"}
                or not isinstance(topic_config["topic"], str)):
            raise ValueError("Invalid Layer 2 configuration")
        topic = topic_config["topic"].strip()
        if not topic or len(topic) > 100:
            raise ValueError("Invalid Layer 2 configuration")
        result["topic_mentions"] = {"topic": topic}
    return result


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate Layer 2 configuration key")
        result[key] = value
    return result


def parse_layer2_config(metadata: dict[str, str], options: list[str]):
    if "layer2_config" not in metadata:
        return validate_layer2_config({}, options)
    try:
        config = json.loads(metadata["layer2_config"], object_pairs_hook=unique_object)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid layer2_config metadata") from exc
    return validate_layer2_config(config, options)


def validate_original_name(name):
    if (not isinstance(name, str) or not name or len(name) > 255
            or name in (".", "..") or "/" in name or "\\" in name
            or not name.isprintable()):
        raise ValueError("Invalid filename metadata")
    return name
