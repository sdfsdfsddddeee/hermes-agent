
    
  
        print(f"hermes: {exc.reason}", file=sys.stderr, flush=True)
        code = 1
    if code != 0:
        _record_completion_attempt(root, failed=True)
        raise RuntimeError(
            "source update completion failed; run `hermes update` to finish it"
        )
    clear_completion(root)


def _sync_source_dependencies(root: Path, *, arm: bool, borrowed_from: Path | None = None) -> None:
    """Commit the tree's dependency generation; *arm* also owes the tail afterwards.

    *borrowed_from* names the data root that owns the checkout when this one only borrows
    it: the sync is this root's own, but the checkout's update markers stay the owner's.
    """
    import sys
    import pm
    from pm.client import ensure_tools_for_sync
    from pm.extras import first_generation_selection

    if borrowed_from is not None:
        print(f"hermes: preparing dependencies for this data root (the checkout's updates belong to "
              f"{borrowed_from})...", file=sys.stderr, flush=True)
    elif not arm:
        print("hermes: preparing dependencies for this update...", file=sys.stderr, flush=True)
    refuse_foreign_owned_venv(root)
    if arm:
        # Owed from before the sync commits: a crash between the commit and the
        # tail must leave the tail, not a "current" install with nothing built.
        arm_completion(root)
    # Main-era installs have no PM ledger; carry what their venv held.
    # Established PM installs retain their recorded extras and plugin union instead.
    extras = first_generation_selection(root)
    # Same order as `hermes update`: an interrupted update or a hand-run
    # `git pull` leaves this tree's lockfile ahead of the installed tools.
    ensure_tools_for_sync()
    pm.sync_venv(extras, explicit=True, project_root=root, evict_incompatible_plugins=True)
    collect_superseded_generations(root)
    if borrowed_from is not None:
        return  # The checkout's markers describe the owner's environment, not this one.
    # These can predate the swap. Once PM commits the replacement they
    # must not make early recovery immediately rebuild it a second time.
    for name in (".update-incomplete", ".lazy-refresh-incomplete"):
        (root / name).unlink(missing_ok=True)


def relaunch_command(
    python: Path, root: Path, argv: list[str], original: list[str], module: str | None,
) -> list[str]:
    """Re-enter the same script/module/launcher with the managed interpreter.

    An old venv may use a different Python ABI. Do not add the new generation
    to that interpreter, and do not depend on its obsolete editable finder.
    """
    # Preserve interpreter options, not application flags with the same names.
    options: list[str] = []
    index = 1
    while index < len(original):
        option = original[index]
        if option in ("-c", "-m", "--", "-") or not option.startswith("-"):
            break
        options.append(option)
        index += 1
        if option in ("-W", "-X") and index < len(original):
            options.append(original[index])
            index += 1
    # _hermes_relaunched marks the child this starts (not processes it spawns) for _relaunch_target;
    # a restore re-execs sys.orig_argv and keeps it, which is why that guard re-checks currency.
    prefix = (f"import sys, runpy; sys.path.insert(0, {str(root)!r}); sys.argv = {argv!r}; "
              "sys._hermes_relaunched = True; ")
    if argv[0] == "-m" and original[index:index + 1] == ["-m"]:
        # Python is still locating the module (a package's __init__ imported the bootstrap):
        # argv[0] is "-m" and __main__ has no spec yet, so the module name is on the command line.
        module = original[index + 1]
    if argv[0] == "-c":
        body = f"exec({original[index + 1]!r})"
    elif module and module != "__main__":
        body = f"runpy.run_module({module!r}, run_name='__main__', alter_sys=True)"
    else:
        # distlib .exe launchers are executable zip files with __main__, not
        # importable modules named '__main__'. run_path handles both shapes.
        body = f"runpy.run_path({str(Path(argv[0]).absolute())!r}, run_name='__main__')"
    return [str(python), *options, "-I", "-c", prefix + body]


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hermes_cli.venv_sync")
    parser.add_argument("--project-root", default=None)
    parser.add_argument(
        "--check", action="store_true", help="report; change nothing"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = sync(
        Path(args.project_root) if args.project_root else None, check=args.check
    )

    if args.json:
        print(json.dumps(result))
    else:
        detail = f" ({result['detail']})" if result.get("detail") else ""
        print(f"venv sync: {result['state']}{detail}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
