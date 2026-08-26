from backend.rap_c500g_main import build_parser


def test_cli_exposes_test_run_and_sync_without_secret_arguments() -> None:
    parser = build_parser()

    test_args = parser.parse_args(["test", "--duration", "60"])
    run_args = parser.parse_args(["run"])
    sync_args = parser.parse_args(["sync"])

    assert test_args.command == "test"
    assert test_args.duration == 60.0
    assert run_args.command == "run"
    assert sync_args.command == "sync"
    help_text = parser.format_help()
    assert "password" not in help_text.lower()
    assert "rtsp" not in help_text.lower()
