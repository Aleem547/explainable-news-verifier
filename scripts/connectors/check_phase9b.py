"""Offline Phase 9B configuration smoke test; never prints API keys."""

from apps.api.connectors.registry import ConnectorConfiguration


def main() -> None:
    config = ConnectorConfiguration.from_environment()
    enabled = config.enabled_providers()
    print("Phase 9B connector configuration (no network request performed):")
    print(f"NewsAPI configured: {'newsapi' in enabled}")
    print(f"Google Fact Check configured: {'google_factcheck' in enabled}")
    print("No live searches run. No API keys displayed.")


if __name__ == "__main__":
    main()
