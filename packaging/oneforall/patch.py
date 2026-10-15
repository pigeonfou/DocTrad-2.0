"""Small, reviewable hooks; preserve existing manager code, reject unknown layouts."""
MARKER = '# Independently deployed local applications (DocTrad2 integration v1)'


def patch_common(text):
    if MARKER in text:
        return text
    anchor = "APPS = json.loads((ROOT / 'config/apps.json').read_text())"
    state = "return read_json(VAR / 'state.json', {})"
    services = "return ['oneforall-' + app + '-' + name for name in APPS[app]['services']]"
    if any(text.count(x) != 1 for x in (anchor, state, services)):
        raise ValueError('Unsupported OneForAll common.py; no edit applied')
    text = text.replace(anchor, anchor + '\n' + MARKER + '\nfrom external_apps import extend_catalog, extend_state\nAPPS = extend_catalog(APPS)')
    text = text.replace(state, "return extend_state(read_json(VAR / 'state.json', {}))")
    return text.replace(services, "return APPS[app].get('systemd_services') or ['oneforall-' + app + '-' + name for name in APPS[app]['services']]")


def patch_render(text):
    if MARKER in text:
        return text
    target = '            proxy_pass {upstream};'
    if text.count(target) < 1 or 'def path_locations(' not in text:
        raise ValueError('Unsupported OneForAll render.py; no edit applied')
    before, after = text.split('def path_locations(', 1)
    after = after.replace(target, "            proxy_pass {upstream}{'/' if APPS[app].get('strip_prefix') else ''};", 1)
    return MARKER + '\n' + before + 'def path_locations(' + after


def patch_deploy(text):
    if MARKER in text:
        return text
    anchor = 'def prepare_release(app, sha=None):\n'
    if text.count(anchor) != 1:
        raise ValueError('Unsupported OneForAll deploy.py; no edit applied')
    return text.replace(anchor, anchor + '    ' + MARKER + '\n    from external_apps import refuse_external\n    refuse_external(app, APPS)\n', 1)


def patch_cli(text):
    if MARKER in text:
        return text
    anchor = "    if a.command == 'render':\n"
    if text.count(anchor) != 1:
        raise ValueError('Unsupported OneForAll cli.py; no edit applied')
    guard = "    " + MARKER + "\n    if a.command in ('install','update','backup','restore','uninstall','create-admin','reset-admin','import-legacy','import-models','configure-geometry'):\n        from external_apps import refuse_external\n        for app in apps:\n            refuse_external(app, APPS)\n"
    return text.replace(anchor, guard + anchor, 1)
