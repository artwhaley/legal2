from pathlib import Path

from message_evidence_workstation.app import parse_cli_options
from message_evidence_workstation.app_bootstrap import StartupLoadOptions


def test_cli_dataset_startup_defaults_to_background_embedding() -> None:
    options = parse_cli_options(["--dataset", "donor_datasets\\julie_kramer"])

    assert options.dataset_path == Path("donor_datasets\\julie_kramer")
    assert options.skip_embedding is False
    startup_load = StartupLoadOptions(
        dataset_path=options.dataset_path,
        reload=options.reload_dataset,
        skip_embedding=options.skip_embedding,
    )
    assert startup_load.skip_embedding is False


def test_cli_skip_embedding_explicitly_disables_background_embedding() -> None:
    options = parse_cli_options(
        ["--dataset", "donor_datasets\\julie_kramer", "--skip-embedding"]
    )

    assert options.skip_embedding is True


def test_cli_with_embedding_kept_as_compatibility_alias() -> None:
    options = parse_cli_options(
        ["--dataset", "donor_datasets\\julie_kramer", "--skip-embedding", "--with-embedding"]
    )

    assert options.skip_embedding is False
