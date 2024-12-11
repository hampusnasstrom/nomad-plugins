def test_importing_app():
    # this will raise an exception if pydantic model validation fails for th app
    from nomad_plugins.apps import plugin_app_entry_point

    assert plugin_app_entry_point.app.label == 'NOMAD plugins'
