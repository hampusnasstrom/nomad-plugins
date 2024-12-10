from nomad.config.models.plugins import AppEntryPoint
from nomad.config.models.ui import (
    App,
    Column,
    Columns,
    Filters,
    Menu,
    MenuItemTerms,
    MenuSizeEnum,
    SearchQuantities,
)

schema = 'nomad_plugins.schema_packages.plugin.Plugin'

plugin_app_entry_point = AppEntryPoint(
    name='NOMAD plugins',
    description='App for searching for plugins.',
    app=App(
        label='NOMAD plugins',
        path='plugins',
        category='NOMAD',
        search_quantities=SearchQuantities(
            include=[
                f'*#{schema}',
            ],
        ),
        columns=Columns(
            selected=[
                f'data.name#{schema}',
                f'data.repository#{schema}',
                f'data.on_pypi#{schema}',
            ],
            options={
                f'data.name#{schema}': Column(
                    label='Name',
                ),
                f'data.repository#{schema}': Column(
                    label='Repository',
                ),
                f'data.on_pypi#{schema}': Column(
                    label='On PyPI',
                ),
            },
        ),
        menu=Menu(
            title='Plugins',
            size=MenuSizeEnum.MD,
            items=[
                MenuItemTerms(
                    search_quantity=f'data.authors.name#{schema}',
                    title='Author',
                    show_input=True,
                ),
            ],
        ),
        filters_locked={
            'entry_type': 'Plugin',
        },
    ),
)
