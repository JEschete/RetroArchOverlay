import argparse
from pathlib import Path

from .plugin_tools import PluginTemplateConfig, SUPPORTED_LICENSES, create_plugin, update_plugin


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or update a uniform RAO_<game> plugin")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="create a new plugin repository")
    create.add_argument("--game-name", required=True)
    create.add_argument("--slug", required=True)
    create.add_argument("--output-root", type=Path, default=Path("plugins"))
    create.add_argument("--copyright-holder", required=True)
    create.add_argument("--license", choices=SUPPORTED_LICENSES, default="MIT")
    create.add_argument("--plugin-id", default="")
    create.add_argument("--ra-game-id", type=int)
    create.add_argument("--core", action="append", default=[])
    create.add_argument("--content-hint", action="append", default=[])
    create.add_argument("--content-hash", action="append", default=[])
    create.add_argument("--decomp-url", default="")
    create.add_argument("--decomp-revision", default="")
    create.add_argument("--decomp-required-file", action="append", default=[])
    create.add_argument("--decomp-required", action="store_true")
    create.add_argument("--install-decomp", action="store_true")
    create.add_argument("--init-git", action="store_true")

    update = subparsers.add_parser("update", help="update license or decomp metadata")
    update.add_argument("repository", type=Path)
    update.add_argument("--copyright-holder")
    update.add_argument("--license", choices=SUPPORTED_LICENSES)
    update.add_argument("--decomp-url")
    update.add_argument("--decomp-revision")
    update.add_argument("--decomp-required-file", action="append")
    update.add_argument("--decomp-required", action=argparse.BooleanOptionalAction)
    update.add_argument("--install-decomp", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "create":
        if args.install_decomp and not args.decomp_url:
            parser.error("--install-decomp requires --decomp-url")
        repository = create_plugin(
            PluginTemplateConfig(
                game_name=args.game_name,
                slug=args.slug,
                output_root=args.output_root,
                copyright_holder=args.copyright_holder,
                license_expression=args.license,
                plugin_id=args.plugin_id,
                ra_game_id=args.ra_game_id,
                cores=tuple(args.core),
                content_hints=tuple(args.content_hint),
                content_hashes=tuple(args.content_hash),
                decomp_url=args.decomp_url,
                decomp_revision=args.decomp_revision,
                decomp_required_files=tuple(args.decomp_required_file),
                decomp_required=args.decomp_required,
            ),
            initialize_git=args.init_git or args.install_decomp,
        )
        if args.install_decomp:
            update_plugin(repository, install_decomp=True)
        print(repository)
        return
    manifest = update_plugin(
        args.repository,
        decomp_url=args.decomp_url,
        decomp_revision=args.decomp_revision,
        decomp_required_files=tuple(args.decomp_required_file)
        if args.decomp_required_file is not None
        else None,
        decomp_required=args.decomp_required,
        license_expression=args.license,
        copyright_holder=args.copyright_holder,
        install_decomp=args.install_decomp,
    )
    print(f"Updated {manifest.display_name} ({manifest.plugin_id})")


if __name__ == "__main__":
    main()